#!/usr/bin/env python3
"""
Phase 3 Re-run Script — CPU-Verified (terminate + retry)
=========================================================
Re-runs the 8 Phase 3 configurations that showed CPU heterogeneity.
Each instance is verified via /proc/cpuinfo; wrong-CPU instances are
immediately terminated and replaced (same logic as all_instances_phase2_extended.py
and the original t3-single-phase-1.py Phase 1 scripts).

Log format is identical to n30_logs/ so that parse_n30_logs.py works unchanged.
Logs are written to n30_rerun_logs/ to keep clean data separate.

Usage:
    python3 rerun_cpu_verified.py [--dry-run] [--configs m5_large_serial,...]
"""

import os
import re
import sys
import time
import threading
import subprocess
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED, ALL_COMPLETED
import boto3
import paramiko

# ============================================================================
# AWS / Experiment Configuration
# ============================================================================

AWS_CONFIG = {
    "key_name":        "<aws-key-pair-name>",
    "security_groups": ["<aws-security-group-name>"],
    "region":          "us-east-1",
    "local_key_path":  "./aws-key.pem",
}

INPUT_VIDEO = (
    "./artifact"
    "/artifacts/test_videos/video_repetido_10min.mp4"
)

AMI_STANDARD = "ami-0a313d6098716f372"  # Ubuntu 18.04 LTS (installs ffmpeg at runtime)
AMI_PREBUILT  = "ami-06c7c20c67513469a"  # Ubuntu 22.04 LTS + ffmpeg pre-installed

LOG_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "n30_rerun_logs"
)

# Global vCPU semaphore — stay well below the 436-vCPU account limit
VCPU_LIMIT   = 400
MAX_RETRIES  = 15  # max terminate+retry attempts per instance slot
RETRY_SLEEP  = 10  # seconds between retries

vcpu_sem = threading.Semaphore(VCPU_LIMIT)

# ============================================================================
# Configurations to re-run
# ============================================================================

CONFIGS = [
    # --- M-family Phase 3.1 (unoptimized — installs ffmpeg) ---
    {
        "name": "m5_large_serial",
        "strategy": "serial",
        "instance_type": "m5.large",
        "vcpus": 2,
        "ami": AMI_STANDARD,
        "prebuilt": False,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz",
        "threads": 5,
        "n_runs": 30,
    },
    {
        "name": "m5_large_horizontal",
        "strategy": "horizontal",
        "instance_type": "m5.large",
        "vcpus": 2,
        "ami": AMI_STANDARD,
        "prebuilt": False,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz",
        "threads": 5,
        "n_runs": 30,
        "n_parts": 10,
        "max_workers": 5,  # match original script (2 batches of 5)
    },
    {
        "name": "m5_4xlarge_vertical",
        "strategy": "vertical",
        "instance_type": "m5.4xlarge",
        "vcpus": 16,
        "ami": AMI_STANDARD,
        "prebuilt": False,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz",
        "threads": 10,
        "n_runs": 30,
    },
    # --- M-family Phase 3.2 (optimized — pre-built AMI) ---
    {
        "name": "m5_large_serial_opt",
        "strategy": "serial",
        "instance_type": "m5.large",
        "vcpus": 2,
        "ami": AMI_PREBUILT,
        "prebuilt": True,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz",
        "threads": 5,
        "n_runs": 30,
    },
    {
        "name": "m5_4xlarge_vertical_opt",
        "strategy": "vertical",
        "instance_type": "m5.4xlarge",
        "vcpus": 16,
        "ami": AMI_PREBUILT,
        "prebuilt": True,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz",
        "threads": 10,
        "n_runs": 30,
    },
    # --- C-family Phase 3.2 (optimized) ---
    {
        "name": "c5_large_horizontal_opt",
        "strategy": "horizontal",
        "instance_type": "c5.large",
        "vcpus": 2,
        "ami": AMI_PREBUILT,
        "prebuilt": True,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz",
        "threads": 5,
        "n_runs": 30,
        "n_parts": 10,
        "max_workers": 5,
    },
    # --- C-family Phase 3.1 (unoptimized) ---
    {
        "name": "c5_4xlarge_vertical",
        "strategy": "vertical",
        "instance_type": "c5.4xlarge",
        "vcpus": 16,
        "ami": AMI_STANDARD,
        "prebuilt": False,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz",
        "threads": 10,
        "n_runs": 30,
    },
    # --- C-family Phase 3.2 (optimized) ---
    {
        "name": "c5_4xlarge_vertical_opt",
        "strategy": "vertical",
        "instance_type": "c5.4xlarge",
        "vcpus": 16,
        "ami": AMI_PREBUILT,
        "prebuilt": True,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz",
        "threads": 10,
        "n_runs": 30,
    },
]

# ============================================================================
# Logging helpers
# ============================================================================

def ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def make_logger(log_path):
    """Returns a log(msg, context='') function that writes to file + stdout."""
    lock = threading.Lock()
    def _log(msg, context=""):
        line = f"[{ts()}]" + (f" [{context}]" if context else "") + f" {msg}"
        with lock:
            with open(log_path, "a") as f:
                f.write(line + "\n")
        print(line)
    return _log

# ============================================================================
# AWS helpers
# ============================================================================

def launch_instance(ec2, ami, instance_type, log, context=""):
    """Launch one EC2 instance, wait until running, return (instance_id, public_ip)."""
    response = ec2.run_instances(
        ImageId=ami,
        InstanceType=instance_type,
        KeyName=AWS_CONFIG["key_name"],
        SecurityGroups=AWS_CONFIG["security_groups"],
        MinCount=1, MaxCount=1,
    )
    iid = response["Instances"][0]["InstanceId"]
    log(f"Instance {iid} launched. Waiting for running...", context)
    ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
    desc = ec2.describe_instances(InstanceIds=[iid])
    ip = desc["Reservations"][0]["Instances"][0]["PublicIpAddress"]
    log(f"Instance ready. IP: {ip}", context)
    return iid, ip


def ssh_connect(ip, key_path, retries=8, delay=5):
    """Return a connected paramiko SSHClient."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for attempt in range(retries):
        try:
            ssh.connect(ip, username="ubuntu", key_filename=key_path, timeout=15)
            return ssh
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)


def get_cpu_model(ssh):
    """Read /proc/cpuinfo model name from remote instance."""
    _, stdout, _ = ssh.exec_command(
        "cat /proc/cpuinfo | grep 'model name' | head -1"
    )
    stdout.channel.recv_exit_status()
    return stdout.read().decode().strip().split(": ")[-1]


def install_ffmpeg(ssh, log, context):
    """Install ffmpeg on a fresh Ubuntu instance."""
    log("Installing ffmpeg...", context)
    for cmd in ["sudo apt-get update -y", "sudo apt-get install -y ffmpeg"]:
        _, stdout, _ = ssh.exec_command(cmd)
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            log(f"WARNING: '{cmd}' exit {rc}", context)
    log("ffmpeg installed.", context)


def run_ffmpeg(ssh, threads, log, context):
    """Run ffmpeg on remote instance. Returns encoding seconds."""
    codec   = "libx264"
    preset  = "slow"
    bitrate = "2M"
    cmd = (
        f"ffmpeg -i /home/ubuntu/input.mp4 -c:v {codec} -preset {preset} "
        f"-b:v {bitrate} -threads {threads} -max_muxing_queue_size 1024 "
        f"-y /home/ubuntu/output.mp4"
    )
    log(f"Running: {cmd}", context)
    t0 = time.time()
    _, stdout, stderr = ssh.exec_command(cmd)
    rc = stdout.channel.recv_exit_status()
    elapsed = time.time() - t0
    if rc != 0:
        err = stderr.read().decode()[-300:]
        raise RuntimeError(f"ffmpeg exit {rc}: {err}")
    return elapsed


def acquire_vcpus(n, log, context):
    """Acquire n vCPU slots from the global semaphore."""
    for _ in range(n):
        vcpu_sem.acquire()
    log(f"[vCPU] Acquired {n} slots.", context)


def release_vcpus(n, log, context):
    """Release n vCPU slots back to the global semaphore."""
    for _ in range(n):
        vcpu_sem.release()
    log(f"[vCPU] Released {n} slots.", context)

# ============================================================================
# Core: get a CPU-verified instance (terminate + retry)
# ============================================================================

def get_verified_instance(ec2, cfg, log, context):
    """
    Launch an instance, verify CPU via /proc/cpuinfo.
    If wrong CPU: terminate immediately and retry (up to MAX_RETRIES).
    Returns (instance_id, ssh_client, launch_time) where launch_time is the
    timestamp of the successful instance launch (for comparable wall-clock timing).

    This replicates the methodology of all_instances_phase2_extended.py
    and t3-single-phase-1.py — the gold-standard CPU-pinning approach.
    """
    ami           = cfg["ami"]
    instance_type = cfg["instance_type"]
    expected_cpu  = cfg["expected_cpu"]
    vcpus         = cfg["vcpus"]
    key_path      = AWS_CONFIG["local_key_path"]

    for attempt in range(1, MAX_RETRIES + 1):
        acquire_vcpus(vcpus, log, context)
        iid = None
        try:
            launch_time = time.time()  # record start of THIS attempt's launch
            iid, ip = launch_instance(ec2, ami, instance_type, log, context)
            time.sleep(25)  # allow sshd to start (matches original scripts)
            ssh = ssh_connect(ip, key_path)
            log("SSH connected.", context)

            cpu_model = get_cpu_model(ssh)
            log(f"CPU found: {cpu_model}", context)

            if cpu_model == expected_cpu:
                log("CPU correct. Proceeding.", context)
                # Return launch_time so callers anchor their wall-clock timer
                # to the successful launch (excludes retry overhead, matches
                # original n30_logs methodology where there were no retries)
                return iid, ssh, launch_time  # caller is responsible for terminate + release_vcpus

            # Wrong CPU — terminate and retry
            log(
                f"CPU mismatch (attempt {attempt}/{MAX_RETRIES}): "
                f"got '{cpu_model}', expected '{expected_cpu}'. "
                f"Terminating and retrying...",
                context,
            )
            ssh.close()
            ec2.terminate_instances(InstanceIds=[iid])
            iid = None
        except Exception as e:
            log(f"Error on attempt {attempt}: {e}", context)
            if iid:
                try:
                    ec2.terminate_instances(InstanceIds=[iid])
                except Exception:
                    pass
                iid = None
        finally:
            if iid is None:
                release_vcpus(vcpus, log, context)

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_SLEEP)

    raise RuntimeError(
        f"Failed to get correct CPU ({expected_cpu}) after {MAX_RETRIES} attempts."
    )

# ============================================================================
# Strategy: Serial
# ============================================================================

def run_serial_single(cfg, run_id, log_path):
    """Run one serial benchmark. Matches format of m5_large_serial_run_N.log."""
    log = make_logger(log_path)
    ec2 = boto3.client("ec2", region_name=AWS_CONFIG["region"])
    name    = cfg["name"]
    threads = cfg["threads"]
    vcpus   = cfg["vcpus"]
    context = f"{cfg['instance_type']}-Serial"

    suffix  = " OPTIMIZED" if cfg["prebuilt"] else ""
    log(f"=== Phase 3.2{suffix} Serial Baseline: 1x {cfg['instance_type']} ===")
    log(f"Codec: libx264, Threads: {threads}, Preset: slow")
    if cfg["prebuilt"]:
        log(f"AMI: {cfg['ami']} (ffmpeg pre-installed)")

    iid = None
    ssh = None
    setup_time = enc_time = 0.0
    try:
        log(f"Launching EC2 instance...", context)
        iid, ssh, launch_time = get_verified_instance(ec2, cfg, log, context)
        # Anchor wall-clock timer to successful instance launch (excludes
        # retry overhead; matches original n30_logs where retries never occurred)
        total_start = setup_start = launch_time

        if not cfg["prebuilt"]:
            install_ffmpeg(ssh, log, context)

        log(f"CPU: {cfg['expected_cpu']}", context)  # already verified
        log("Uploading 10-minute video...", context)
        sftp = ssh.open_sftp()
        sftp.put(INPUT_VIDEO, "/home/ubuntu/input.mp4")
        sftp.close()
        log("Upload complete.", context)

        setup_time = time.time() - setup_start
        log(f"SETUP TIME: {setup_time:.2f}s ({setup_time/60:.2f} min)", context)

        enc_time = run_ffmpeg(ssh, threads, log, context)
        log(f"ENCODING TIME: {enc_time:.2f}s ({enc_time/60:.2f} min)", context)

    finally:
        if ssh:
            try: ssh.close()
            except: pass
        if iid:
            ec2.terminate_instances(InstanceIds=[iid])
            log("Instance terminated.", context)
            release_vcpus(vcpus, log, context)

    total_time = time.time() - total_start

    log(f"{'='*60}", context)
    log(f"RESULTS — {cfg['instance_type']} Serial", context)
    log(f"  Total Time:    {total_time:.2f}s ({total_time/60:.2f} min)", context)
    log(f"  Setup Time:    {setup_time:.2f}s ({setup_time/60:.2f} min)", context)
    log(f"  Encoding Time: {enc_time:.2f}s ({enc_time/60:.2f} min)", context)
    log(f"  Setup %:       {100*setup_time/total_time:.1f}%", context)
    log(f"{'='*60}", context)
    return total_time

# ============================================================================
# Strategy: Vertical
# ============================================================================

def run_vertical_single(cfg, run_id, log_path):
    """Run one vertical benchmark. Matches format of m5_4xlarge_vertical_run_N.log."""
    log = make_logger(log_path)
    ec2 = boto3.client("ec2", region_name=AWS_CONFIG["region"])
    threads = cfg["threads"]
    vcpus   = cfg["vcpus"]
    context = f"{cfg['instance_type']}-Vertical"

    suffix = " OPTIMIZED" if cfg["prebuilt"] else ""
    log(f"=== Phase 3.2{suffix} Vertical Scaling: 1x {cfg['instance_type']} ===")
    log(f"Codec: libx264, Threads: {threads}, Preset: slow")

    iid = None
    ssh = None
    setup_time = enc_time = 0.0
    try:
        log("Launching EC2 instance...", context)
        iid, ssh, launch_time = get_verified_instance(ec2, cfg, log, context)
        total_start = setup_start = launch_time

        if not cfg["prebuilt"]:
            install_ffmpeg(ssh, log, context)

        log(f"CPU: {cfg['expected_cpu']}", context)
        log("Uploading 10-minute video...", context)
        sftp = ssh.open_sftp()
        sftp.put(INPUT_VIDEO, "/home/ubuntu/input.mp4")
        sftp.close()
        log("Upload complete.", context)

        setup_time = time.time() - setup_start
        log(f"SETUP TIME: {setup_time:.2f}s ({setup_time/60:.2f} min)", context)

        enc_time = run_ffmpeg(ssh, threads, log, context)
        log(f"ENCODING TIME: {enc_time:.2f}s ({enc_time/60:.2f} min)", context)

    finally:
        if ssh:
            try: ssh.close()
            except: pass
        if iid:
            ec2.terminate_instances(InstanceIds=[iid])
            log("Instance terminated.", context)
            release_vcpus(vcpus, log, context)

    total_time = time.time() - total_start
    log(f"{'='*60}", context)
    log(f"RESULTS — {cfg['instance_type']} Vertical", context)
    log(f"  Total Time:    {total_time:.2f}s ({total_time/60:.2f} min)", context)
    log(f"  Setup Time:    {setup_time:.2f}s ({setup_time/60:.2f} min)", context)
    log(f"  Encoding Time: {enc_time:.2f}s ({enc_time/60:.2f} min)", context)
    log(f"  Setup %:       {100*setup_time/total_time:.1f}%", context)
    log(f"{'='*60}", context)
    return total_time

# ============================================================================
# Strategy: Horizontal
# ============================================================================

def _process_part(part_index, cfg, parts_dir, log, run_log_path):
    """Process one video chunk on a CPU-verified instance. Returns part elapsed seconds."""
    ec2     = boto3.client("ec2", region_name=AWS_CONFIG["region"])
    threads = cfg["threads"]
    vcpus   = cfg["vcpus"]
    context = f"Part {part_index:02d}"

    iid = None
    ssh = None
    try:
        log(f"Launching {cfg['instance_type']}...", context)
        iid, ssh, t_part_start = get_verified_instance(ec2, cfg, log, context)

        if not cfg["prebuilt"]:
            install_ffmpeg(ssh, log, context)

        log(f"CPU: {cfg['expected_cpu']}", context)

        sftp = ssh.open_sftp()
        part_file = os.path.join(parts_dir, f"part_{part_index:02d}.mp4")
        log("Uploading segment...", context)
        sftp.put(part_file, "/home/ubuntu/input.mp4")
        sftp.close()

        run_ffmpeg(ssh, threads, log, context)
        log("Done!", context)
        return time.time() - t_part_start

    finally:
        if ssh:
            try: ssh.close()
            except: pass
        if iid:
            ec2.terminate_instances(InstanceIds=[iid])
            log("Instance terminated.", context)
            release_vcpus(vcpus, log, context)


def run_horizontal_single(cfg, run_id, log_path):
    """Run one horizontal benchmark. Matches format of c5_large_horizontal_run_N.log."""
    log = make_logger(log_path)
    n_parts    = cfg.get("n_parts", 10)
    max_workers= cfg.get("max_workers", 5)
    threads    = cfg["threads"]
    suffix     = " OPTIMIZED" if cfg["prebuilt"] else ""

    log(f"=== Phase 3.2{suffix} Horizontal Scaling: {n_parts}x {cfg['instance_type']} ===")
    log(f"Codec: libx264, Threads: {threads}, Max workers: {max_workers}")

    # Split video
    base_dir  = os.path.dirname(os.path.abspath(__file__))
    parts_dir = os.path.join(
        base_dir, f"parts_{cfg['name']}_run{run_id}"
    )
    os.makedirs(parts_dir, exist_ok=True)

    total_start = time.time()
    log("Starting video split...", "Setup")

    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", INPUT_VIDEO],
        capture_output=True, text=True, check=True
    )
    duration     = float(result.stdout.strip())
    part_duration= duration / n_parts
    log(f"Video: {duration:.1f}s → {n_parts} parts of {part_duration:.1f}s", "Setup")

    for i in range(n_parts):
        out = os.path.join(parts_dir, f"part_{i:02d}.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-i", INPUT_VIDEO,
             "-ss", str(i * part_duration), "-t", str(part_duration),
             "-c", "copy", out],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
        )

    split_time = time.time() - total_start
    log(f"Video split complete.", "Setup")
    log(f"SPLIT TIME: {split_time:.2f}s", "Summary")

    parallel_start = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_process_part, i, cfg, parts_dir, log, log_path)
            for i in range(n_parts)
        ]
        for f in futures:
            f.result()  # re-raise exceptions

    parallel_time = time.time() - parallel_start
    total_time    = time.time() - total_start

    # Cleanup parts
    for f in os.listdir(parts_dir):
        os.remove(os.path.join(parts_dir, f))
    os.rmdir(parts_dir)

    log(f"{'='*60}")
    log(f"RESULTS — {n_parts}x {cfg['instance_type']} Horizontal")
    log(f"  Total Time:    {total_time:.2f}s ({total_time/60:.2f} min)")
    log(f"  Split Time:    {split_time:.2f}s")
    log(f"  Parallel Time: {parallel_time:.2f}s ({parallel_time/60:.2f} min)")
    log(f"{'='*60}")
    return total_time

# ============================================================================
# Per-config runner: launches all n_runs in parallel
# ============================================================================

STRATEGY_MAP = {
    "serial":     run_serial_single,
    "vertical":   run_vertical_single,
    "horizontal": run_horizontal_single,
}

def run_config(cfg, dry_run=False):
    """Run all n_runs for a single config, all in parallel."""
    name    = cfg["name"]
    n_runs  = cfg["n_runs"]
    strategy= cfg["strategy"]
    runner  = STRATEGY_MAP[strategy]

    print(f"\n{'='*70}")
    print(f"[{ts()}] Starting config: {name} ({n_runs} runs, strategy={strategy})")
    print(f"{'='*70}")

    if dry_run:
        print(f"  [DRY RUN] Would run {n_runs} × {name}")
        return

    # Check for already-completed runs (must contain RESULTS block)
    existing = set()
    for fn in os.listdir(LOG_DIR):
        m = re.match(rf"{re.escape(name)}_run_(\d+)\.log", fn)
        if m:
            log_path = os.path.join(LOG_DIR, fn)
            with open(log_path) as fh:
                if "RESULTS" in fh.read():
                    existing.add(int(m.group(1)))
    run_ids = [i for i in range(1, n_runs + 1) if i not in existing]

    if not run_ids:
        print(f"  [{name}] All {n_runs} runs already complete. Skipping.")
        return

    print(f"  [{name}] Launching {len(run_ids)} runs (skipping {len(existing)} existing)...")

    # Run all n_runs concurrently (same parallelism as original n30_logs scripts)
    # to match original network/bandwidth conditions per-config.
    # Configs are run SEQUENTIALLY in main() to avoid cross-config contention.
    futures = {}
    with ThreadPoolExecutor(max_workers=n_runs) as executor:
        for run_id in run_ids:
            log_path = os.path.join(LOG_DIR, f"{name}_run_{run_id}.log")
            f = executor.submit(runner, cfg, run_id, log_path)
            futures[f] = run_id

        success = 0
        for f in futures:
            rid = futures[f]
            try:
                elapsed = f.result()
                print(f"  [{name}] run {rid:02d} done in {elapsed:.1f}s")
                success += 1
            except Exception as e:
                print(f"  [{name}] run {rid:02d} FAILED: {e}")

    print(f"\n  [{name}] Completed {success}/{len(run_ids)} runs.")

# ============================================================================
# Main
# ============================================================================

def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would run without launching instances")
    p.add_argument("--configs", default="",
                   help="Comma-separated list of config names to run (default: all)")
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(LOG_DIR, exist_ok=True)

    # Filter configs
    selected = [c["name"] for c in CONFIGS]
    if args.configs:
        selected = [s.strip() for s in args.configs.split(",")]
    configs_to_run = [c for c in CONFIGS if c["name"] in selected]

    if not configs_to_run:
        print(f"No matching configs found. Available: {[c['name'] for c in CONFIGS]}")
        sys.exit(1)

    # vCPU estimate
    total_vcpu_peak = sum(
        c["n_runs"] * c["vcpus"] * (c.get("max_workers", 1) if c["strategy"] == "horizontal" else 1)
        for c in configs_to_run
    )
    print(f"\n{'='*70}")
    print(f"Phase 3 Re-run: CPU-Verified (terminate + retry)")
    print(f"Configs to run : {[c['name'] for c in configs_to_run]}")
    print(f"vCPU budget    : {VCPU_LIMIT} (account limit: 436)")
    print(f"Peak vCPU demand (unbounded): {total_vcpu_peak}")
    print(f"Log output dir : {LOG_DIR}")
    print(f"{'='*70}\n")

    if not args.dry_run:
        if not os.path.exists(INPUT_VIDEO):
            print(f"ERROR: Input video not found: {INPUT_VIDEO}")
            sys.exit(1)
        if not os.path.exists(AWS_CONFIG["local_key_path"]):
            print(f"ERROR: PEM key not found: {AWS_CONFIG['local_key_path']}")
            sys.exit(1)

    global_start = time.time()

    # Run configs SEQUENTIALLY to avoid cross-config network/resource contention.
    # Within each config, all n_runs run concurrently (matching original scripts).
    for c in configs_to_run:
        try:
            run_config(c, args.dry_run)
        except Exception as e:
            print(f"\n[FATAL] Config {c['name']} raised: {e}")

    total = time.time() - global_start
    print(f"\n{'='*70}")
    print(f"All configs finished in {total:.1f}s ({total/60:.1f} min)")
    print(f"Logs: {LOG_DIR}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
