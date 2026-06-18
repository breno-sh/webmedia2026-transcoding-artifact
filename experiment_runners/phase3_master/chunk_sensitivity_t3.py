#!/usr/bin/env python3
"""
Chunk Sensitivity Experiment — T-Family (t3.micro) — Horizontal Scaling with Custom AMI.
Usage:
  python3 chunk_sensitivity_t3.py --chunks 20   # 30-second chunks
  python3 chunk_sensitivity_t3.py --chunks 10   # 60-second chunks (baseline)
  python3 chunk_sensitivity_t3.py --chunks 5    # 120-second chunks

Requires: boto3, paramiko, ffmpeg/ffprobe on localhost
"""
import os, time, sys, subprocess, argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import boto3
import paramiko

# ─── CONFIG ───────────────────────────────────────────────────────────────────
INPUT_VIDEO = "./artifact/artifacts/test_videos/video_repetido_10min.mp4"
INSTANCE_TYPE = "t3.micro"
THREADS = 5
CODEC = "libx264"
BITRATE = "2M"
PRESET = "slow"

BASE_DIR = "./artifact/artifacts2/phase3_scaling"

CUSTOM_AMI = "ami-06c7c20c67513469a"

AWS_CONFIG = {
    "ami_id": CUSTOM_AMI,
    "key_name": "<aws-key-pair-name>",
    "security_groups": ["<aws-security-group-name>"],
    "region": "us-east-1",
    "local_key_path": "./artifact/artifacts2/aws-key.pem",
}
# ──────────────────────────────────────────────────────────────────────────────

def log(msg, context=None):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    ctx = f" [{context}]" if context else ""
    print(f"[{ts}]{ctx} {msg}")

def split_video(parts_dir, num_parts):
    log("Starting video split...", "Setup")
    os.makedirs(parts_dir, exist_ok=True)
    if not os.path.exists(INPUT_VIDEO):
        log(f"ERROR: Video not found at {INPUT_VIDEO}", "Setup"); return False
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", INPUT_VIDEO],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip())
    part_duration = duration / num_parts
    log(f"Video: {duration:.1f}s → {num_parts} parts of {part_duration:.1f}s each", "Setup")
    for i in range(num_parts):
        out = f"{parts_dir}/part_{i:02d}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-i", INPUT_VIDEO, "-ss", str(i * part_duration),
             "-t", str(part_duration), "-c", "copy", out],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    log("Video split complete.", "Setup")
    return True

def process_part(part_index, parts_dir, compressed_dir):
    context = f"Part {part_index:02d}"
    ec2 = boto3.client('ec2', region_name=AWS_CONFIG['region'])
    instance_id, ssh_client = None, None
    t_start = time.time()
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
        t_provisioned = time.time()
        log(f"Instance up in {t_provisioned - t_start:.1f}s. IP: {public_ip}", context)
        time.sleep(30)

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(public_ip, username="ubuntu", key_filename=AWS_CONFIG['local_key_path'])

        sftp = ssh_client.open_sftp()
        try:
            part_file = f"{parts_dir}/part_{part_index:02d}.mp4"
            log("Uploading segment...", context)
            sftp.put(part_file, "/home/ubuntu/input.mp4")
            cmd = (f"ffmpeg -nostdin -i /home/ubuntu/input.mp4 -c:v {CODEC} -preset {PRESET} "
                   f"-b:v {BITRATE} -threads {THREADS} "
                   f"-y /home/ubuntu/output.mp4")
            log("Running compression...", context)
            t_encode_start = time.time()
            stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=900)
            exit_status = stdout.channel.recv_exit_status()
            t_encode_end = time.time()
            if exit_status != 0:
                raise RuntimeError(f"FFmpeg failed: {stderr.read().decode()[-300:]}")
            log(f"Encoding done in {t_encode_end - t_encode_start:.1f}s. Downloading...", context)
            os.makedirs(compressed_dir, exist_ok=True)
            sftp.get("/home/ubuntu/output.mp4", f"{compressed_dir}/part_{part_index:02d}_compressed.mp4")
            log("Part complete!", context)
        finally:
            sftp.close()
        return time.time() - t_start
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

def run(num_parts):
    chunk_label = f"{600 // num_parts}s"
    log(f"=== Chunk Sensitivity: {num_parts}x {INSTANCE_TYPE} ({chunk_label}/chunk) ===")
    log(f"AMI: {CUSTOM_AMI} | Codec: {CODEC} | Threads: {THREADS}")

    parts_dir = f"{BASE_DIR}/sensitivity_t3_{chunk_label}_parts"
    compressed_dir = f"{BASE_DIR}/sensitivity_t3_{chunk_label}_compressed"

    total_start = time.time()
    if not split_video(parts_dir, num_parts):
        return
    split_end = time.time()
    split_time = split_end - total_start
    log(f"SPLIT TIME: {split_time:.2f}s", "Summary")

    parallel_start = time.time()
    with ThreadPoolExecutor(max_workers=num_parts) as executor:
        futures = {executor.submit(process_part, i, parts_dir, compressed_dir): i for i in range(num_parts)}
        for future in as_completed(futures):
            idx = futures[future]
            try: future.result()
            except Exception as e: log(f"Part {idx} FAILED: {e}", "ERROR")
    parallel_end = time.time()

    total_time = parallel_end - total_start
    parallel_time = parallel_end - parallel_start
    overhead_pct = (split_time + (parallel_time - (parallel_time * 0.5))) / total_time * 100  # approx

    log("=" * 60)
    log(f"RESULTS — {num_parts}x {INSTANCE_TYPE} | {chunk_label}/chunk")
    log(f"  Total Time:    {total_time:.2f}s  ({total_time / 60:.3f} min)")
    log(f"  Split Time:    {split_time:.2f}s")
    log(f"  Parallel Time: {parallel_time:.2f}s  ({parallel_time / 60:.3f} min)")
    log(f"  Setup Overhead: ~{split_time:.2f}s + 30s SSH wait per instance")
    log("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chunk sensitivity experiment for T-family")
    parser.add_argument("--chunks", type=int, required=True, choices=[5, 10, 20],
                        help="Number of chunks: 5=120s, 10=60s, 20=30s")
    args = parser.parse_args()

    chunk_label = f"{600 // args.chunks}s"
    log_file = f"chunk_sensitivity_t3_{chunk_label}.log"
    class Tee:
        def __init__(self, *files): self.files = files
        def write(self, data):
            for f in self.files: f.write(data); f.flush()
        def flush(self):
            for f in self.files: f.flush()
    with open(log_file, "w") as logfile:
        tee = Tee(sys.__stdout__, logfile)
        sys.stdout = sys.stderr = tee
        try: run(args.chunks)
        finally: sys.stdout = sys.__stdout__; sys.stderr = sys.__stderr__
