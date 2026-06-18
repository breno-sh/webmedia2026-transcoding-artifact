#!/usr/bin/env python3
"""
Chunk Sensitivity — Multi-Resolution Experiment (Phase 4 Extension).

Tests whether the optimal chunk size shifts with video resolution.
Hypothesis: at 240p encoding is fast and provisioning dominates (60s optimal);
at 1080p encoding dominates and larger chunks may be better.

Usage:
  python3 chunk_sensitivity_multiresolution.py --video PATH --chunks 10 --runs 5 --family m5
  python3 chunk_sensitivity_multiresolution.py --video PATH --chunks 20 --runs 5 --family m5

Families: t3 (t3.micro), m5 (m5.large), c5 (c5.large)
"""
import os, sys, time, subprocess, argparse, json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import boto3
import paramiko

# ─── FAMILY CONFIG ──────────────────────────────────────────────────────────
FAMILIES = {
    "t3": {"instance_type": "t3.micro",  "label": "T-family"},
    "m5": {"instance_type": "m5.large",  "label": "M-family"},
    "c5": {"instance_type": "c5.large",  "label": "C-family"},
}

CODEC = "libx264"
BITRATE = "2M"
PRESET = "slow"
THREADS = 5

CUSTOM_AMI = "ami-06c7c20c67513469a"

AWS_CONFIG = {
    "ami_id": CUSTOM_AMI,
    "key_name": "<aws-key-pair-name>",
    "security_groups": ["<aws-security-group-name>"],
    "region": "us-east-1",
    "local_key_path": "./aws-key.pem",
}

OUTPUT_DIR = "./artifacts3/chunk_multiresolution_logs"

# ────────────────────────────────────────────────────────────────────────────

def log(msg, context=None):
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    ctx = f" [{context}]" if context else ""
    line = f"[{ts}]{ctx} {msg}"
    print(line)
    return line

def get_video_info(video_path):
    result = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-show_entries", "stream=width,height",
         "-of", "json", video_path],
        capture_output=True, text=True
    )
    info = json.loads(result.stdout)
    duration = float(info["format"]["duration"])
    stream = info["streams"][0]
    return duration, stream["width"], stream["height"]

def split_video(video_path, parts_dir, num_parts):
    log("Starting video split...", "Setup")
    os.makedirs(parts_dir, exist_ok=True)
    duration, w, h = get_video_info(video_path)
    part_duration = duration / num_parts
    log(f"Video: {duration:.1f}s, {w}x{h} → {num_parts} parts of {part_duration:.1f}s each", "Setup")
    for i in range(num_parts):
        out = f"{parts_dir}/part_{i:02d}.mp4"
        if os.path.exists(out):
            continue
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-ss", str(i * part_duration),
             "-t", str(part_duration), "-c", "copy", out],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    log("Video split complete.", "Setup")
    return part_duration

BATCH_SIZE = 10  # max concurrent SFTP transfers

def _provision_one(part_index, instance_type):
    """Launch instance + wait for SSH. Returns (instance_id, ip, ssh_client, timings)."""
    ctx = f"Part {part_index:02d}"
    ec2 = boto3.client('ec2', region_name=AWS_CONFIG['region'])
    t0 = time.time()
    log(f"Launching {instance_type}...", ctx)
    resp = ec2.run_instances(
        ImageId=AWS_CONFIG['ami_id'], InstanceType=instance_type,
        KeyName=AWS_CONFIG['key_name'], SecurityGroups=AWS_CONFIG['security_groups'],
        MinCount=1, MaxCount=1
    )
    iid = resp['Instances'][0]['InstanceId']
    ec2.get_waiter('instance_running').wait(InstanceIds=[iid])
    info = ec2.describe_instances(InstanceIds=[iid])
    ip = info['Reservations'][0]['Instances'][0]['PublicIpAddress']
    t_prov = time.time() - t0
    log(f"Instance up ({t_prov:.1f}s). IP: {ip}", ctx)

    t_ssh = time.time()
    time.sleep(25)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for attempt in range(10):
        try:
            ssh.connect(ip, username="ubuntu",
                        key_filename=AWS_CONFIG['local_key_path'], timeout=10)
            break
        except Exception:
            if attempt == 9: raise
            time.sleep(5)
    t_ssh_ready = time.time() - t_ssh
    return iid, ip, ssh, {"provision": t_prov, "ssh_ready": t_ssh_ready}

def _upload_one(part_index, ssh, parts_dir):
    ctx = f"Part {part_index:02d}"
    sftp = ssh.open_sftp()
    t0 = time.time()
    sftp.put(f"{parts_dir}/part_{part_index:02d}.mp4", "/home/ubuntu/input.mp4")
    elapsed = time.time() - t0
    sftp.close()
    log(f"Upload: {elapsed:.1f}s", ctx)
    return elapsed

def _encode_start(part_index, ssh):
    """Start ffmpeg (non-blocking). Returns (stdin, stdout, stderr, t_start)."""
    cmd = (f"ffmpeg -nostdin -i /home/ubuntu/input.mp4 -c:v {CODEC} -preset {PRESET} "
           f"-b:v {BITRATE} -threads {THREADS} -max_muxing_queue_size 1024 "
           f"-y /home/ubuntu/output.mp4")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=1800)
    log(f"Encode started", f"Part {part_index:02d}")
    return stdin, stdout, stderr, time.time()

def _encode_wait(part_index, stdout, stderr, t_start):
    exit_status = stdout.channel.recv_exit_status()
    elapsed = time.time() - t_start
    if exit_status != 0:
        err = stderr.read().decode()[-500:]
        raise RuntimeError(f"FFmpeg failed (exit {exit_status}): {err}")
    log(f"Encode done: {elapsed:.1f}s", f"Part {part_index:02d}")
    return elapsed

def _download_one(part_index, ssh, compressed_dir):
    ctx = f"Part {part_index:02d}"
    sftp = ssh.open_sftp()
    t0 = time.time()
    os.makedirs(compressed_dir, exist_ok=True)
    sftp.get("/home/ubuntu/output.mp4",
             f"{compressed_dir}/part_{part_index:02d}_compressed.mp4")
    elapsed = time.time() - t0
    sftp.close()
    log(f"Download: {elapsed:.1f}s", ctx)
    return elapsed

def _terminate_one(part_index, instance_id):
    ec2 = boto3.client('ec2', region_name=AWS_CONFIG['region'])
    ec2.terminate_instances(InstanceIds=[instance_id])
    log(f"Terminated", f"Part {part_index:02d}")

def run_trial(trial_num, video_path, num_parts, instance_type, resolution_label):
    """Run one horizontal encoding trial with batched SFTP pipeline.

    Pipeline per batch of BATCH_SIZE parts:
      1. Provision all instances in batch (parallel)
      2. Upload chunks (parallel, max BATCH_SIZE concurrent SFTPs)
      3. Start encoding (non-blocking)  →  while encoding, provision next batch
      4. Wait for encoding to finish
      5. Download results (parallel)
      6. Terminate instances
    """
    chunk_secs = int(600 / num_parts)  # approximate
    label = f"{resolution_label}_{instance_type}_{chunk_secs}s"
    parts_dir = f"{OUTPUT_DIR}/parts_{label}"
    compressed_dir = f"{OUTPUT_DIR}/compressed_{label}_trial{trial_num:02d}"

    log(f"\n{'='*70}")
    log(f"TRIAL {trial_num} — {num_parts}x {instance_type} | {chunk_secs}s chunks | {resolution_label}")
    log(f"  Pipeline: batches of {BATCH_SIZE}, SFTP capped at {BATCH_SIZE} concurrent")
    log(f"{'='*70}")

    t_total = time.time()

    # Split (cached across trials)
    t_split = time.time()
    split_video(video_path, parts_dir, num_parts)
    split_time = time.time() - t_split

    # Divide parts into batches
    part_indices = list(range(num_parts))
    batches = [part_indices[i:i+BATCH_SIZE] for i in range(0, len(part_indices), BATCH_SIZE)]

    all_timings = {}
    # Track encoding futures from previous batch so we can overlap
    prev_batch_encoding = []  # list of (part_idx, iid, ssh, stdout, stderr, t_start)

    t_parallel = time.time()

    for batch_num, batch_parts in enumerate(batches):
        log(f"\n>>> BATCH {batch_num+1}/{len(batches)}: parts {batch_parts} <<<", "Pipeline")

        # Step 1: Provision all instances in this batch (parallel)
        log("Provisioning...", "Pipeline")
        batch_instances = {}  # part_idx -> (iid, ip, ssh, timings)
        with ThreadPoolExecutor(max_workers=len(batch_parts)) as ex:
            futs = {ex.submit(_provision_one, idx, instance_type): idx for idx in batch_parts}
            for f in as_completed(futs):
                idx = futs[f]
                try:
                    iid, ip, ssh, timings = f.result()
                    batch_instances[idx] = (iid, ip, ssh, timings)
                except Exception as e:
                    log(f"Part {idx} provision FAILED: {e}", "ERROR")
                    all_timings[idx] = {"error": str(e)}

        # Step 2: Upload chunks (parallel, within this batch only)
        log("Uploading...", "Pipeline")
        with ThreadPoolExecutor(max_workers=len(batch_parts)) as ex:
            upload_futs = {}
            for idx in batch_parts:
                if idx in batch_instances:
                    _, _, ssh, _ = batch_instances[idx]
                    upload_futs[ex.submit(_upload_one, idx, ssh, parts_dir)] = idx
            for f in as_completed(upload_futs):
                idx = upload_futs[f]
                try:
                    batch_instances[idx][3]['upload'] = f.result()
                except Exception as e:
                    log(f"Part {idx} upload FAILED: {e}", "ERROR")
                    all_timings[idx] = {"error": str(e)}

        # Step 3: Start encoding on all instances (non-blocking)
        log("Starting encodes...", "Pipeline")
        current_batch_encoding = []
        for idx in batch_parts:
            if idx in batch_instances and idx not in all_timings:
                iid, ip, ssh, timings = batch_instances[idx]
                try:
                    stdin, stdout, stderr, t_enc = _encode_start(idx, ssh)
                    current_batch_encoding.append((idx, iid, ssh, stdout, stderr, t_enc, timings))
                except Exception as e:
                    log(f"Part {idx} encode start FAILED: {e}", "ERROR")
                    all_timings[idx] = {"error": str(e)}

        # Step 4: While this batch encodes, collect previous batch results
        if prev_batch_encoding:
            log("Collecting previous batch results...", "Pipeline")
            for idx, iid, ssh, stdout, stderr, t_enc, timings in prev_batch_encoding:
                try:
                    timings['encode'] = _encode_wait(idx, stdout, stderr, t_enc)
                    timings['download'] = _download_one(idx, ssh, compressed_dir)
                    timings['total'] = timings['provision'] + timings['ssh_ready'] + timings['upload'] + timings['encode'] + timings['download']
                    all_timings[idx] = timings
                except Exception as e:
                    log(f"Part {idx} FAILED: {e}", "ERROR")
                    all_timings[idx] = {"error": str(e)}
                finally:
                    try: ssh.close()
                    except: pass
                    _terminate_one(idx, iid)

        prev_batch_encoding = current_batch_encoding

    # Collect final batch results
    if prev_batch_encoding:
        log("\nCollecting final batch results...", "Pipeline")
        for idx, iid, ssh, stdout, stderr, t_enc, timings in prev_batch_encoding:
            try:
                timings['encode'] = _encode_wait(idx, stdout, stderr, t_enc)
                timings['download'] = _download_one(idx, ssh, compressed_dir)
                timings['total'] = timings['provision'] + timings['ssh_ready'] + timings['upload'] + timings['encode'] + timings['download']
                all_timings[idx] = timings
            except Exception as e:
                log(f"Part {idx} FAILED: {e}", "ERROR")
                all_timings[idx] = {"error": str(e)}
            finally:
                try: ssh.close()
                except: pass
                _terminate_one(idx, iid)

    parallel_time = time.time() - t_parallel
    total_time = time.time() - t_total

    # Summary
    log(f"\n{'─'*50}")
    log(f"TRIAL {trial_num} RESULTS — {label}")
    log(f"  Total Time:    {total_time:.2f}s  ({total_time / 60:.3f} min)")
    log(f"  Split Time:    {split_time:.2f}s")
    log(f"  Parallel Time: {parallel_time:.2f}s  ({parallel_time / 60:.3f} min)")

    encode_times, provision_times, upload_times, download_times = [], [], [], []
    for idx in sorted(all_timings.keys()):
        t = all_timings[idx]
        if 'error' not in t:
            encode_times.append(t.get('encode', 0))
            provision_times.append(t.get('provision', 0))
            upload_times.append(t.get('upload', 0))
            download_times.append(t.get('download', 0))

    if encode_times:
        log(f"  Avg Encode:    {sum(encode_times)/len(encode_times):.2f}s")
        log(f"  Avg Provision: {sum(provision_times)/len(provision_times):.2f}s")
        log(f"  Avg Upload:    {sum(upload_times)/len(upload_times):.2f}s")
        log(f"  Avg Download:  {sum(download_times)/len(download_times):.2f}s")
        log(f"  Max Encode:    {max(encode_times):.2f}s (bottleneck part)")
    log(f"{'─'*50}\n")

    return {
        "trial": trial_num,
        "total_time": total_time,
        "split_time": split_time,
        "parallel_time": parallel_time,
        "part_timings": all_timings,
        "config": {
            "resolution": resolution_label,
            "instance_type": instance_type,
            "chunk_secs": chunk_secs,
            "num_parts": num_parts,
        }
    }

def main():
    parser = argparse.ArgumentParser(description="Multi-resolution chunk sensitivity")
    parser.add_argument("--video", required=True, help="Path to input video")
    parser.add_argument("--chunks", type=int, required=True, choices=[5, 10, 20],
                        help="Number of chunks (5=120s, 10=60s, 20=30s)")
    parser.add_argument("--runs", type=int, default=5, help="Number of trials (default: 5)")
    parser.add_argument("--family", required=True, choices=["t3", "m5", "c5"],
                        help="Instance family")
    parser.add_argument("--resolution-label", default=None,
                        help="Label for resolution (auto-detected if omitted)")
    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"ERROR: Video not found: {args.video}")
        sys.exit(1)

    duration, w, h = get_video_info(args.video)
    res_label = args.resolution_label or f"{h}p"
    instance_type = FAMILIES[args.family]["instance_type"]
    chunk_secs = int(duration / args.chunks)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log(f"╔{'═'*68}╗")
    log(f"║ CHUNK SENSITIVITY — MULTI-RESOLUTION")
    log(f"║ Video: {args.video}")
    log(f"║ Resolution: {w}x{h} ({res_label})")
    log(f"║ Duration: {duration:.1f}s")
    log(f"║ Instance: {instance_type} ({FAMILIES[args.family]['label']})")
    log(f"║ Chunks: {args.chunks} × {chunk_secs}s")
    log(f"║ Trials: {args.runs}")
    log(f"╚{'═'*68}╝")

    # Log file
    log_name = f"chunk_multi_{res_label}_{args.family}_{chunk_secs}s.log"
    log_path = os.path.join(OUTPUT_DIR, log_name)

    class Tee:
        def __init__(self, *files): self.files = files
        def write(self, data):
            for f in self.files: f.write(data); f.flush()
        def flush(self):
            for f in self.files: f.flush()

    results = []
    with open(log_path, "w") as logfile:
        tee = Tee(sys.__stdout__, logfile)
        sys.stdout = sys.stderr = tee
        try:
            for trial in range(1, args.runs + 1):
                result = run_trial(trial, args.video, args.chunks, instance_type, res_label)
                results.append(result)
                log(f"\n>>> Completed {trial}/{args.runs} trials <<<\n")
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

    # Save structured results
    json_path = os.path.join(OUTPUT_DIR, log_name.replace(".log", ".json"))
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    # Final summary
    times = [r["total_time"] for r in results if "total_time" in r]
    if times:
        import statistics
        print(f"\n{'='*60}")
        print(f"FINAL SUMMARY: {res_label} | {instance_type} | {chunk_secs}s chunks")
        print(f"  Trials:  {len(times)}")
        print(f"  Median:  {statistics.median(times):.2f}s ({statistics.median(times)/60:.3f} min)")
        print(f"  Mean:    {statistics.mean(times):.2f}s")
        print(f"  Stdev:   {statistics.stdev(times):.2f}s" if len(times) > 1 else "")
        print(f"  Min/Max: {min(times):.2f}s / {max(times):.2f}s")
        print(f"  Log:     {log_path}")
        print(f"  JSON:    {json_path}")
        print(f"{'='*60}")

if __name__ == "__main__":
    main()
