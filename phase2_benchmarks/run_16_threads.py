import boto3
import paramiko
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import textwrap
import os

CONFIG = {
    "ami_id": "ami-0a313d6098716f372",
    "key_name": "<aws-key-pair-name>",
    "security_groups": ["<aws-security-group-name>"],
    "region": "us-east-1",
    "local_key_path": "./aws-key.pem",
    "compression_iterations": 30,
    "video_url": "https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_320x180.mp4"
}

instance_configs = [
    {"InstanceType": "c5.4xlarge", "vCPUs": 16, "ExpectedCPU": "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz"},
    {"InstanceType": "m5.4xlarge", "vCPUs": 16, "ExpectedCPU": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz"}
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def generate_dockerfile(codec, thread_count, iterations, video_url):
    codec_flag = {
        "h264": "libx264",
        "h265": "libx265",
        "vp9": "libvpx-vp9"
    }[codec]
    ext = "mp4" if codec in ["h264", "h265"] else "webm"

    return textwrap.dedent(f"""
        FROM ubuntu:22.04
        ENV DEBIAN_FRONTEND=noninteractive
        RUN apt-get update && apt-get install -y wget bc ffmpeg
        WORKDIR /app
        RUN echo '#!/bin/bash' > /app/run.sh && \\
            echo 'set -e' >> /app/run.sh && \\
            echo 'wget {video_url} -O /app/original_video.mp4 --no-check-certificate' >> /app/run.sh && \\
            echo 'ffmpeg -i /app/original_video.mp4 -t 30 -c copy /app/original_video_30.mp4' >> /app/run.sh && \\
            echo 'for i in $(seq 1 {iterations}); do' >> /app/run.sh && \\
            echo '  start=$(date +%s.%N)' >> /app/run.sh && \\
            echo '  ffmpeg -i /app/original_video_30.mp4 -c:v {codec_flag} -crf 28 -threads {thread_count} /app/compressed_{thread_count}t_$i.{ext} 1>/dev/null 2>/dev/null' >> /app/run.sh && \\
            echo '  end=$(date +%s.%N)' >> /app/run.sh && \\
            echo '  duration=$(echo "$end - $start" | bc)' >> /app/run.sh && \\
            echo '  echo "Compression $i ({thread_count} threads): ${{duration}} seconds"' >> /app/run.sh && \\
            echo 'done' >> /app/run.sh && \\
            echo 'echo "All compressions completed!"' >> /app/run.sh && \\
            chmod +x /app/run.sh
        CMD ["/bin/bash", "/app/run.sh"]
    """)

def run_for_instance(instance_config):
    instance_type = instance_config["InstanceType"]
    expected_cpu = instance_config.get("ExpectedCPU")
    ec2 = boto3.client('ec2', region_name=CONFIG['region'])

    log(f"🚀 Launching {instance_type}")
    response = ec2.run_instances(
        ImageId=CONFIG['ami_id'],
        InstanceType=instance_type,
        KeyName=CONFIG['key_name'],
        SecurityGroups=CONFIG['security_groups'],
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[{'ResourceType': 'instance', 'Tags': [{'Key': 'Name', 'Value': f'anon-Phase2-16T-{instance_type}'}]}]
    )
    instance_id = response['Instances'][0]['InstanceId']
    log(f"🆔 Instance ID: {instance_id}")
    ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
    instance = ec2.describe_instances(InstanceIds=[instance_id])
    public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']

    time.sleep(30)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(public_ip, username="ubuntu", key_filename=CONFIG['local_key_path'])

    log(f"🐳 Installing Docker on {instance_type}...")
    for cmd in ["sudo apt-get update -y", "sudo apt-get install -y docker.io", "sudo usermod -aG docker ubuntu", "sudo chmod 666 /var/run/docker.sock", "sudo systemctl restart docker"]:
        stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
        stdout.channel.recv_exit_status()

    codecs = ["h264", "h265", "vp9"]
    thread_counts = [16]
    
    for codec in codecs:
        for thread_count in thread_counts:
            log(f"▶️  Running {codec} benchmark on {instance_type} with {thread_count} threads...")
            log_filename = f"compression_{instance_type}_{codec}_{thread_count}thread.log"
            dockerfile = generate_dockerfile(codec, thread_count, CONFIG['compression_iterations'], CONFIG['video_url'])
            
            cmd = f"cat > Dockerfile << 'EOF'\n{dockerfile}\nEOF"
            stdin, stdout, stderr = ssh.exec_command(cmd)
            stdout.channel.recv_exit_status()

            cmds = [
                f"sudo docker build -t compressor_{codec}_{thread_count} .",
                f"sudo docker run --rm compressor_{codec}_{thread_count} | tee /home/ubuntu/{log_filename}"
            ]
            for c in cmds:
                log(f"[{instance_type} - {codec} - {thread_count}t] ➤ {c}")
                stdin, stdout, stderr = ssh.exec_command(c)
                while True:
                    line = stdout.readline()
                    if not line: break
                    line = line.strip()
                    if line and "Compression" in line:
                        log(f"[{instance_type} - {codec} - {thread_count}t] {line}")
                stdout.channel.recv_exit_status()

            sftp = ssh.open_sftp()
            os.makedirs("logs_16t", exist_ok=True)
            local_log_path = os.path.join("logs_16t", log_filename)
            try:
                sftp.get(f"/home/ubuntu/{log_filename}", local_log_path)
                log(f"📄 Saved log to {local_log_path}")
            except Exception as e:
                log(f"❌ Failed to download log: {e}")
            sftp.close()

    ssh.close()
    log(f"🧹 Terminating {instance_id}")
    ec2.terminate_instances(InstanceIds=[instance_id])

def main():
    log(f"🚀 Starting 16-thread benchmark for 4xlarge instances")
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_for_instance, config) for config in instance_configs]
        for f in futures:
            f.result()
    log(f"✅ Finished 16-thread benchmark")

if __name__ == "__main__":
    main()
