import boto3
import paramiko
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import textwrap
import os
from paramiko import SFTPClient

CONFIG = {
    "ami_id": "ami-0a313d6098716f372",  # Standard Ubuntu 22.04 LTS (Phase 1 AMI)
    "key_name": "<aws-key-pair-name>",  # Replace with your AWS key pair name
    "security_groups": ["<aws-security-group-name>"],  # Using Security Group Name
    "region": "us-east-1",
    "local_key_path": "./aws-key.pem",  # Replace with path to your .pem key file
    "compression_iterations": 30,
    "video_url": "./test_videos/big_buck_bunny_240p_20mb.mp4",
    "codec": "vp9",
    "max_vcpus": 32 # lowered to avoid throttling
}

instance_configs = [
    # New C-family (Compute Optimized)
    {"InstanceType": "c5.large", "vCPUs": 2, "ExpectedCPU": "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz"},
    {"InstanceType": "c5.xlarge", "vCPUs": 4, "ExpectedCPU": "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz"},
    {"InstanceType": "c5.2xlarge", "vCPUs": 8, "ExpectedCPU": "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz"},
    {"InstanceType": "c5.4xlarge", "vCPUs": 16, "ExpectedCPU": "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz"},

    # New M-family (General Purpose)
    {"InstanceType": "m5.large", "vCPUs": 2, "ExpectedCPU": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz"},
    {"InstanceType": "m5.xlarge", "vCPUs": 4, "ExpectedCPU": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz"},
    {"InstanceType": "m5.2xlarge", "vCPUs": 8, "ExpectedCPU": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz"},
    {"InstanceType": "m5.4xlarge", "vCPUs": 16, "ExpectedCPU": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz"},
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def generate_dockerfile(codec, thread_count, iterations):
    codec_flag = {
        "h264": "libx264",
        "h265": "libx265",
        "vp9": "libvpx-vp9"
    }[codec]
    ext = "mp4" if codec in ["h264", "h265"] else "webm"

    return textwrap.dedent(f"""
        FROM ubuntu:22.04
        ENV DEBIAN_FRONTEND=noninteractive
        # Install FFmpeg on standard AMI
        RUN apt-get update && apt-get install -y wget bc ffmpeg
        WORKDIR /app
        COPY original_video.mp4 /app/original_video.mp4
        RUN echo '#!/bin/bash' > /app/run.sh && \\
            echo 'set -e' >> /app/run.sh && \\
            echo 'echo "Starting compression at $(date)"' >> /app/run.sh && \\
            echo 'ffmpeg -i /app/original_video.mp4 -t 30 -c copy /app/original_video_30.mp4' >> /app/run.sh && \\
            echo 'for i in $(seq 1 {iterations}); do' >> /app/run.sh && \\
            echo '  echo "🚀 Starting iteration $i with {thread_count} threads at $(date +%H:%M:%S)"' >> /app/run.sh && \\
            echo '  start=$(date +%s.%N)' >> /app/run.sh && \\
            echo '  ffmpeg -i /app/original_video_30.mp4 -c:v {codec_flag} -crf 28 -threads {thread_count} /app/compressed_{thread_count}t_$i.{ext} 1>/dev/null 2>/dev/null' >> /app/run.sh && \\
            echo '  end=$(date +%s.%N)' >> /app/run.sh && \\
            echo '  duration=$(echo "$end - $start" | bc)' >> /app/run.sh && \\
            echo '  echo "✅ Iteration $i with {thread_count} threads completed in ${{duration}}s"' >> /app/run.sh && \\
            echo '  echo "Compression $i ({thread_count} threads): ${{duration}} seconds"' >> /app/run.sh && \\
            echo 'done' >> /app/run.sh && \\
            echo 'echo "All compressions completed!"' >> /app/run.sh && \\
            chmod +x /app/run.sh
        CMD ["/bin/bash", "/app/run.sh"]
    """)

def run_for_instance(instance_config):
    instance_type = instance_config["InstanceType"]
    expected_cpu = instance_config.get("ExpectedCPU")
    codec = CONFIG["codec"]
    ec2 = boto3.client('ec2', region_name=CONFIG['region'])

    # 1. Launch Instance (One per type)
    log(f"🚀 Launching {instance_type} (FASE 2) - Will run tests for threads: 1, 3, 5, 10")
    response = ec2.run_instances(
        ImageId=CONFIG['ami_id'],
        InstanceType=instance_type,
        KeyName=CONFIG['key_name'],
        SecurityGroups=CONFIG['security_groups'],
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{
            'ResourceType': 'instance',
            'Tags': [{'Key': 'Name', 'Value': f'anon-Phase2-{instance_type}'}]
        }]
    )
    instance_id = response['Instances'][0]['InstanceId']
    log(f"🆔 Instance ID: {instance_id}")
    launched_instances.append(instance_id)
    ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
    instance = ec2.describe_instances(InstanceIds=[instance_id])
    public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']
    log(f"🌐 Public IP: {public_ip}")

    time.sleep(30)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(public_ip, username="ubuntu", key_filename=CONFIG['local_key_path'])

    # 2. Verify CPU
    stdin, stdout, stderr = ssh.exec_command("cat /proc/cpuinfo | grep 'model name' | head -1")
    cpu_model = stdout.read().decode().strip().split(": ")[-1]
    log(f"🔍 CPU Model: {cpu_model}")

    if expected_cpu and cpu_model != expected_cpu:
        log("❌ CPU model does not match expected. Terminating and retrying...")
        ec2.terminate_instances(InstanceIds=[instance_id])
        if instance_id in launched_instances:
            launched_instances.remove(instance_id)
        time.sleep(10)
        log(f"🔁 Retrying {instance_type}...")
        return run_for_instance(instance_config)
    
    log(f"✅ CPU Verified: {cpu_model}")

    # 2b. Upload Video to Host
    sftp = ssh.open_sftp()
    log(f"[{instance_type}] 📦 Uploading local video to instance...")
    sftp.put(CONFIG["video_url"], "/home/ubuntu/original_video.mp4")
    # Also ensure we have a clean logs dir on instance just in case
    ssh.exec_command("rm -f /home/ubuntu/*.log")
    sftp.close()

    # 3. Install Docker on Host (Once per instance)
    log(f"🐳 Installing Docker on {instance_type}...")
    # These commands are executed once to set up Docker
    docker_setup_cmds = [
        "sudo apt-get update -y",
        "sudo apt-get install -y docker.io",
        "sudo usermod -aG docker ubuntu",
        "sudo chmod 666 /var/run/docker.sock",
        "sudo systemctl restart docker"
    ]
    for cmd in docker_setup_cmds:
        log(f"[{instance_type}] ➤ {cmd}")
        stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
        # Wait for installation to complete - reading stdout/stderr forces wait
        o = stdout.read()
        e = stderr.read()
        if e:
            log(f"⚠️  Docker setup stderr: {e.decode()[:200]}...") # Log partial error if any
        stdout.channel.recv_exit_status()


    # 4. Run Benchmark Loops (Sequential on same instance)
    codecs = ["h264", "h265", "vp9"]
    thread_counts = [1, 3, 5, 10]
    
    for codec in codecs:
        for thread_count in thread_counts:
            log(f"▶️  Running {codec} benchmark on {instance_type} with {thread_count} threads...")
            log_filename = f"compression_{instance_type}_{codec}_{thread_count}thread.log"
            
            dockerfile = generate_dockerfile(codec, thread_count, CONFIG['compression_iterations'])
            
            # Create unique directory for this run to avoid conflicts if needed, but simple overwrite is fine mainly
            cmd = f"cat > Dockerfile << 'EOF'\n{dockerfile}\nEOF"
            stdin, stdout, stderr = ssh.exec_command(cmd)
            stdout.channel.recv_exit_status()

            cmds = [
                f"sudo docker build -t compressor_{codec}_{thread_count} .",
                f"sudo docker run --rm compressor_{codec}_{thread_count} | tee /home/ubuntu/{log_filename}"
            ]

            for cmd in cmds:
                log(f"[{instance_type} - {codec} - {thread_count}t] ➤ {cmd}")
                stdin, stdout, stderr = ssh.exec_command(cmd)
                
                # Stream output
                while True:
                    line = stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if line:
                        log(f"[{instance_type} - {codec} - {thread_count}t] {line}")
                
                exit_status = stdout.channel.recv_exit_status()
                if exit_status != 0:
                    log(f"❌ Error executing command: {cmd}")
                    error_msg = stderr.read().decode()
                    log(f"Stderr: {error_msg}")

            # Download log for this thread count
            sftp = ssh.open_sftp()
            local_log_path = os.path.join("logs", log_filename)
            os.makedirs("logs", exist_ok=True)
            try:
                sftp.get(f"/home/ubuntu/{log_filename}", local_log_path)
                log(f"📄 Saved log to {local_log_path}")
            except Exception as e:
                log(f"❌ Failed to download log: {e}")
            sftp.close()

    ssh.close()
    
    # 5. Terminate Instance
    log(f"🧹 Terminating instance {instance_id}...")
    ec2.terminate_instances(InstanceIds=[instance_id])
    if instance_id in launched_instances:
        launched_instances.remove(instance_id)
    log(f"✅ Instance {instance_id} terminated")
    return instance_config["vCPUs"], instance_id

import signal
import sys

# Global list to track instances launched by this script run
launched_instances = []

def cleanup(signum, frame):
    log("\n🛑 Interrupted! Terminating launched instances...")
    if launched_instances:
        ec2 = boto3.client('ec2', region_name=CONFIG['region'])
        ec2.terminate_instances(InstanceIds=launched_instances)
        log(f"✅ Terminated {len(launched_instances)} instances: {launched_instances}")
    sys.exit(1)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def get_existing_vcpus():
    ec2 = boto3.client('ec2', region_name=CONFIG['region'])
    filters = [
        {'Name': 'instance-state-name', 'Values': ['running', 'pending']},
        {'Name': 'tag:Name', 'Values': ['anon*']}
    ]
    response = ec2.describe_instances(Filters=filters)
    
    total_vcpus = 0
    # Map instance type to vCPU count from config
    vcpu_map = {c['InstanceType']: c['vCPUs'] for c in instance_configs}
    
    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            itype = instance['InstanceType']
            # Default to 2 if unknown (safe assumption for small types) or fetch from map
            vcpus = vcpu_map.get(itype, 2) 
            total_vcpus += vcpus
            log(f"⚠️  Found existing instance {instance['InstanceId']} ({itype}) - {vcpus} vCPUs")
            
    return total_vcpus

def main():
    log(f"🚀 Starting full batch for Phase 2 (AMI Customizada)")
    
    # Check existing usage
    active_vcpus = get_existing_vcpus()
    log(f"ℹ️  Initial Active vCPUs: {active_vcpus}/{CONFIG['max_vcpus']}")
    
    if active_vcpus >= CONFIG['max_vcpus']:
        log("❌ Error: Existing instances already exceed or meet vCPU limit!")
        return

    futures = []
    with ThreadPoolExecutor(max_workers=10) as executor: # Increased workers
        # Keep track of submitted configs to avoid re-submitting
        submitted_configs = set()
        
        # Loop until all configs are submitted and all futures are done
        while len(submitted_configs) < len(instance_configs) or futures:
            # Try to submit new tasks if capacity allows
            submitted_in_this_pass = False
            for config in instance_configs:
                if config["InstanceType"] not in submitted_configs:
                    if active_vcpus + config["vCPUs"] <= CONFIG["max_vcpus"]:
                        log(f"Submitting {config['InstanceType']} (vCPUs: {config['vCPUs']}). Current active vCPUs: {active_vcpus}")
                        futures.append(executor.submit(run_for_instance, config))
                        active_vcpus += config["vCPUs"]
                        submitted_configs.add(config["InstanceType"])
                        submitted_in_this_pass = True
            
            # If we couldn't submit anything new, or if we are just waiting for the current batch to finish
            if not submitted_in_this_pass and futures:
                # Wait for at least one future to complete to free up vCPUs
                # Note: as_completed yields futures as they complete. We take the first one.
                # We need to be careful not to consume all completed futures at once if we want to check submission eligibility frequentlly,
                # but here we just need to free up SOME space.
                
                # Using return_when=FIRST_COMPLETED logic with wait() would be better but Executor uses threads.
                # We can simulate this by waiting on the first result from as_completed iterator
                
                # Create iterator
                iterator = as_completed(futures)
                try:
                    done_future = next(iterator)
                    used_vcpus, instance_id = done_future.result()
                    active_vcpus -= used_vcpus
                    log(f"Task for instance {instance_id} completed, {used_vcpus} vCPUs freed. New active vCPUs: {active_vcpus}")
                    
                    # Remove from futures list
                    futures.remove(done_future)
                    if instance_id in launched_instances:
                            launched_instances.remove(instance_id)

                except StopIteration:
                    pass # Should not happen if futures is not empty

    log(f"✅ Finished batch for Phase 2")

if __name__ == "__main__":
    main()
