#!/usr/bin/env python3
"""
Phase 3.2 — Horizontal Scaling: 10× m5.large processing 10-min video (1 min each).
Hardcoded script, no parameters needed.
"""
import os
import time
import sys
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import boto3
import paramiko

INPUT_VIDEO = "./artifact/artifacts/test_videos/video_repetido_10min.mp4"
INSTANCE_TYPE = "m5.large"
EXPECTED_CPU = "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz"
THREADS = 5
CODEC = "libx264"
BITRATE = "2M"
PRESET = "slow"
NUM_PARTS = 10
MAX_WORKERS = 5  # 5 instances × 2 vCPUs = 10 vCPUs (within limit)

PARTS_DIR = "./artifact/artifacts2/phase3_scaling/video_parts_m5"
COMPRESSED_DIR = "./artifact/artifacts2/phase3_scaling/compressed_parts_m5"

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

def split_video():
    log("Starting video split...", "Setup")
    os.makedirs(PARTS_DIR, exist_ok=True)
    os.makedirs(COMPRESSED_DIR, exist_ok=True)

    if not os.path.exists(INPUT_VIDEO):
        log(f"ERROR: Input video not found: {INPUT_VIDEO}", "Setup")
        return False

    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", INPUT_VIDEO],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip())
    part_duration = duration / NUM_PARTS
    log(f"Video duration: {duration:.1f}s, splitting into {NUM_PARTS} parts of {part_duration:.1f}s each", "Setup")

    for i in range(NUM_PARTS):
        output_file = f"{PARTS_DIR}/part_{i:02d}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-i", INPUT_VIDEO, "-ss", str(i * part_duration),
            "-t", str(part_duration), "-c", "copy", output_file
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"  Part {i:02d} created", "Setup")

    log("Video split complete.", "Setup")
    return True

def process_part(part_index):
    context = f"Part {part_index:02d}"
    ec2 = boto3.client('ec2', region_name=AWS_CONFIG['region'])
    instance_id, ssh_client = None, None

    try:
        log(f"Launching {INSTANCE_TYPE}...", context)
        response = ec2.run_instances(
            ImageId=AWS_CONFIG['ami_id'], InstanceType=INSTANCE_TYPE,
            KeyName=AWS_CONFIG['key_name'], SecurityGroups=AWS_CONFIG['security_groups'],
            MinCount=1, MaxCount=1
        )
        instance_id = response['Instances'][0]['InstanceId']
        ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
        instance = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']
        log(f"Instance ready. IP: {public_ip}", context)

        time.sleep(30)

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(public_ip, username="ubuntu", key_filename=AWS_CONFIG['local_key_path'])

        # Install ffmpeg
        log("Installing ffmpeg...", context)
        for cmd in ["sudo apt-get update -y", "sudo apt-get install -y ffmpeg"]:
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            stdout.channel.recv_exit_status()
        log("ffmpeg installed.", context)

        stdin, stdout, stderr = ssh_client.exec_command("cat /proc/cpuinfo | grep 'model name' | head -1")
        cpu_model = stdout.read().decode().strip().split(": ")[-1]
        log(f"CPU: {cpu_model}", context)
        if EXPECTED_CPU and cpu_model != EXPECTED_CPU:
            log(f"WARNING: CPU mismatch! Expected {EXPECTED_CPU}, got {cpu_model}", context)

        sftp = ssh_client.open_sftp()
        try:
            part_file = f"{PARTS_DIR}/part_{part_index:02d}.mp4"
            log("Uploading segment...", context)
            sftp.put(part_file, "/home/ubuntu/input.mp4")

            cmd = f"ffmpeg -i /home/ubuntu/input.mp4 -c:v {CODEC} -preset {PRESET} -b:v {BITRATE} -threads {THREADS} -y /home/ubuntu/output.mp4"
            log("Running compression...", context)
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                raise RuntimeError(f"FFmpeg failed: {stderr.read().decode()[-200:]}")

            local_output = f"{COMPRESSED_DIR}/part_{part_index:02d}_compressed.mp4"
            sftp.get("/home/ubuntu/output.mp4", local_output)
            log("Done!", context)
        finally:
            sftp.close()
    except Exception as e:
        log(f"ERROR: {str(e)}", context)
        raise
    finally:
        if ssh_client:
            try: ssh_client.close()
            except: pass
        if instance_id:
            ec2.terminate_instances(InstanceIds=[instance_id])
            log("Instance terminated.", context)

def run():
    log(f"=== Phase 3.2 Horizontal Scaling: {NUM_PARTS}x {INSTANCE_TYPE} ===")
    log(f"Codec: {CODEC}, Threads: {THREADS}, Preset: {PRESET}")
    log(f"Max concurrent workers: {MAX_WORKERS}")

    total_start = time.time()

    if not split_video():
        return

    split_end = time.time()
    log(f"SPLIT TIME: {split_end - total_start:.2f}s", "Summary")

    parallel_start = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(process_part, range(NUM_PARTS))
    parallel_end = time.time()

    total_end = time.time()
    total_time = total_end - total_start
    parallel_time = parallel_end - parallel_start

    log("=" * 60)
    log(f"RESULTS — {NUM_PARTS}x {INSTANCE_TYPE} Horizontal")
    log(f"  Total Time:    {total_time:.2f}s ({total_time/60:.2f} min)")
    log(f"  Split Time:    {split_end - total_start:.2f}s")
    log(f"  Parallel Time: {parallel_time:.2f}s ({parallel_time/60:.2f} min)")
    log("=" * 60)


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

    log_filename = "m5_large_horizontal.log"
    with open(log_filename, "w") as logfile:
        tee = Tee(sys.__stdout__, logfile)
        sys.stdout = sys.stderr = tee
        try:
            run()
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
