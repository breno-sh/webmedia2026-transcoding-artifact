#!/usr/bin/env python3
"""
Phase 3.2 OPTIMIZED — Horizontal: 10× c5.large with custom AMI.
"""
import os, time, sys, subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import boto3, paramiko

INPUT_VIDEO = "./artifact/artifacts/test_videos/video_repetido_10min.mp4"
INSTANCE_TYPE = "c5.large"
EXPECTED_CPU = "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz"
THREADS = 5
CODEC = "libx264"
BITRATE = "2M"
PRESET = "slow"
NUM_PARTS = 10
MAX_WORKERS = 10

PARTS_DIR = "./artifact/artifacts2/phase3_scaling/video_parts_c5_opt"
COMPRESSED_DIR = "./artifact/artifacts2/phase3_scaling/compressed_parts_c5_opt"


AWS_CONFIG = {
    "ami_id": "ami-06c7c20c67513469a", "key_name": "<aws-key-pair-name>",
    "security_groups": ["<aws-security-group-name>"], "region": "us-east-1",
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
        log(f"ERROR: Video not found", "Setup"); return False
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", INPUT_VIDEO],
        capture_output=True, text=True)
    duration = float(result.stdout.strip())
    part_duration = duration / NUM_PARTS
    log(f"Video: {duration:.1f}s → {NUM_PARTS} parts of {part_duration:.1f}s", "Setup")
    for i in range(NUM_PARTS):
        subprocess.run(["ffmpeg", "-y", "-i", INPUT_VIDEO, "-ss", str(i * part_duration),
            "-t", str(part_duration), "-c", "copy", f"{PARTS_DIR}/part_{i:02d}.mp4"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("Video split complete.", "Setup")
    return True

def process_part(part_index):
    context = f"Part {part_index:02d}"
    ec2 = boto3.client('ec2', region_name=AWS_CONFIG['region'])
    instance_id, ssh_client = None, None
    try:
        log(f"Launching {INSTANCE_TYPE}...", context)
        response = ec2.run_instances(ImageId=AWS_CONFIG['ami_id'], InstanceType=INSTANCE_TYPE,
            KeyName=AWS_CONFIG['key_name'], SecurityGroups=AWS_CONFIG['security_groups'], MinCount=1, MaxCount=1)
        instance_id = response['Instances'][0]['InstanceId']
        ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
        instance = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']
        log(f"Instance ready. IP: {public_ip}", context)
        time.sleep(30)
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(public_ip, username="ubuntu", key_filename=AWS_CONFIG['local_key_path'])
        stdin, stdout, stderr = ssh_client.exec_command("cat /proc/cpuinfo | grep 'model name' | head -1")
        cpu_model = stdout.read().decode().strip().split(": ")[-1]
        log(f"CPU: {cpu_model}", context)
        if EXPECTED_CPU and cpu_model != EXPECTED_CPU:
            log(f"WARNING: CPU mismatch! Expected {EXPECTED_CPU}, got {cpu_model}", context)
        sftp = ssh_client.open_sftp()
        try:
            log("Uploading segment...", context)
            sftp.put(f"{PARTS_DIR}/part_{part_index:02d}.mp4", "/home/ubuntu/input.mp4")
            cmd = f"ffmpeg -i /home/ubuntu/input.mp4 -c:v {CODEC} -preset {PRESET} -b:v {BITRATE} -threads {THREADS} -y /home/ubuntu/output.mp4"
            log("Running compression...", context)
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                raise RuntimeError(f"FFmpeg failed: {stderr.read().decode()[-200:]}")
            sftp.get("/home/ubuntu/output.mp4", f"{COMPRESSED_DIR}/part_{part_index:02d}_compressed.mp4")
            log("Done!", context)
        finally:
            sftp.close()
    except Exception as e:
        log(f"ERROR: {str(e)}", context); raise
    finally:
        if ssh_client:
            try: ssh_client.close()
            except: pass
        if instance_id:
            ec2.terminate_instances(InstanceIds=[instance_id]); log("Instance terminated.", context)

def run():
    log(f"=== Phase 3.2 OPTIMIZED Horizontal: {NUM_PARTS}x {INSTANCE_TYPE} ===")
    log(f"AMI: {"ami-06c7c20c67513469a"}, Max workers: {MAX_WORKERS}")
    total_start = time.time()
    if not split_video(): return
    split_end = time.time()
    log(f"SPLIT TIME: {split_end - total_start:.2f}s", "Summary")
    parallel_start = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(process_part, range(NUM_PARTS))
    parallel_end = time.time()
    total_time = parallel_end - total_start
    log("=" * 60)
    log(f"RESULTS — {NUM_PARTS}x {INSTANCE_TYPE} Horizontal OPTIMIZED")
    log(f"  Total Time:    {total_time:.2f}s ({total_time/60:.2f} min)")
    log(f"  Split Time:    {split_end - total_start:.2f}s")
    log(f"  Parallel Time: {parallel_end - parallel_start:.2f}s ({(parallel_end - parallel_start)/60:.2f} min)")
    log("=" * 60)

if __name__ == "__main__":
    class Tee:
        def __init__(self, *files): self.files = files
        def write(self, data):
            for f in self.files: f.write(data); f.flush()
        def flush(self):
            for f in self.files: f.flush()
    with open("c5_large_horizontal_opt.log", "w") as logfile:
        tee = Tee(sys.__stdout__, logfile)
        sys.stdout = sys.stderr = tee
        try: run()
        finally: sys.stdout = sys.__stdout__; sys.stderr = sys.__stderr__
