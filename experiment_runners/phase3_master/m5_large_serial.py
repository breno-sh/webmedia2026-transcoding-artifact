#!/usr/bin/env python3
"""
Phase 3.2 — Serial Baseline: 1× m5.large processing full 10-min video.
Hardcoded script, no parameters needed.
"""
import os
import time
import sys
from datetime import datetime
import boto3
import paramiko

INPUT_VIDEO = "./artifact/artifacts/test_videos/video_repetido_10min.mp4"
INSTANCE_TYPE = "m5.large"
EXPECTED_CPU = "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz"
THREADS = 5
CODEC = "libx264"
BITRATE = "2M"
PRESET = "slow"

AWS_CONFIG = {
    "ami_id": "ami-0a313d6098716f372",  # Standard Ubuntu 22.04 LTS
    "key_name": "<aws-key-pair-name>",
    "security_groups": ["<aws-security-group-name>"],
    "region": "us-east-1",
    "local_key_path": "./artifact/artifacts2/aws-key.pem",
}

def log(msg, context=None):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    context_info = f" [{context}]" if context else ""
    print(f"[{timestamp}]{context_info} {msg}")

def run():
    context = f"{INSTANCE_TYPE}-Serial"
    ec2 = boto3.client('ec2', region_name=AWS_CONFIG['region'])
    instance_id, ssh_client = None, None

    log(f"=== Phase 3.2 Serial Baseline: 1x {INSTANCE_TYPE} ===")
    log(f"Codec: {CODEC}, Threads: {THREADS}, Preset: {PRESET}")
    log(f"Video: {INPUT_VIDEO}")

    if not os.path.exists(INPUT_VIDEO):
        log(f"ERROR: Input video not found: {INPUT_VIDEO}", context)
        return

    total_start = time.time()

    try:
        # --- SETUP PHASE ---
        setup_start = time.time()

        log("Launching EC2 instance...", context)
        response = ec2.run_instances(
            ImageId=AWS_CONFIG['ami_id'], InstanceType=INSTANCE_TYPE,
            KeyName=AWS_CONFIG['key_name'], SecurityGroups=AWS_CONFIG['security_groups'],
            MinCount=1, MaxCount=1
        )
        instance_id = response['Instances'][0]['InstanceId']
        log(f"Instance {instance_id} launched. Waiting...", context)

        ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
        instance = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']
        log(f"Instance ready. IP: {public_ip}", context)

        time.sleep(30)

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(public_ip, username="ubuntu", key_filename=AWS_CONFIG['local_key_path'])
        log("SSH connected.", context)

        # Install ffmpeg
        log("Installing ffmpeg...", context)
        for cmd in ["sudo apt-get update -y", "sudo apt-get install -y ffmpeg"]:
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                log(f"WARNING: '{cmd}' exit code {exit_status}", context)
        log("ffmpeg installed.", context)

        # CPU check
        stdin, stdout, stderr = ssh_client.exec_command("cat /proc/cpuinfo | grep 'model name' | head -1")
        cpu_model = stdout.read().decode().strip().split(": ")[-1]
        log(f"CPU: {cpu_model}", context)
        if EXPECTED_CPU and cpu_model != EXPECTED_CPU:
            log(f"WARNING: CPU mismatch! Expected {EXPECTED_CPU}, got {cpu_model}", context)

        # Upload video
        log("Uploading 10-minute video...", context)
        sftp = ssh_client.open_sftp()
        sftp.put(INPUT_VIDEO, "/home/ubuntu/input.mp4")
        sftp.close()
        log("Upload complete.", context)

        setup_end = time.time()
        setup_time = setup_end - setup_start
        log(f"SETUP TIME: {setup_time:.2f}s ({setup_time/60:.2f} min)", context)

        # --- ENCODING PHASE ---
        encoding_start = time.time()

        cmd = f"ffmpeg -i /home/ubuntu/input.mp4 -c:v {CODEC} -preset {PRESET} -b:v {BITRATE} -threads {THREADS} -y /home/ubuntu/output.mp4"
        log(f"Running: {cmd}", context)

        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        exit_status = stdout.channel.recv_exit_status()
        if exit_status != 0:
            err = stderr.read().decode()
            log(f"ERROR: FFmpeg failed (exit {exit_status}): {err[-200:]}", context)
            return

        encoding_end = time.time()
        encoding_time = encoding_end - encoding_start
        log(f"ENCODING TIME: {encoding_time:.2f}s ({encoding_time/60:.2f} min)", context)

    except Exception as e:
        log(f"ERROR: {str(e)}", context)
        raise
    finally:
        total_end = time.time()
        total_time = total_end - total_start

        if ssh_client:
            try: ssh_client.close()
            except: pass
        if instance_id:
            ec2.terminate_instances(InstanceIds=[instance_id])
            log("Instance terminated.", context)

        log("=" * 60, context)
        log(f"RESULTS — {INSTANCE_TYPE} Serial", context)
        log(f"  Total Time:    {total_time:.2f}s ({total_time/60:.2f} min)", context)
        try:
            log(f"  Setup Time:    {setup_time:.2f}s ({setup_time/60:.2f} min)", context)
            log(f"  Encoding Time: {encoding_time:.2f}s ({encoding_time/60:.2f} min)", context)
            log(f"  Setup %:       {(setup_time/total_time)*100:.1f}%", context)
        except:
            pass
        log("=" * 60, context)


if __name__ == "__main__":
    class Tee:
        def __init__(self, *files):
            self.files = files
        def write(self, data):
            for f in self.files:
                f.write(data)
                f.flush()
        def flush(self):
            for f in self.files:
                f.flush()

    log_filename = "m5_large_serial.log"
    with open(log_filename, "w") as logfile:
        tee = Tee(sys.__stdout__, logfile)
        sys.stdout = sys.stderr = tee
        try:
            run()
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
