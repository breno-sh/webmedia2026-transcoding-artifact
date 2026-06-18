#!/usr/bin/env python3
"""
Unified Phase 3 Script — this study

Single parameterized script for ALL experimental improvements:
  - Melhoria 1: --codec libx265 / libvpx-vp9
  - Melhoria 2: --region sa-east-1
  - Melhoria 3: --instance-type t4g.micro / m7g.large / c7g.large etc.

Usage examples:
  # Original baseline (replicates existing scripts)
  python3 phase3_unified.py --instance-type t3.micro --strategy horizontal --codec libx264

  # Melhoria 1: H.265 on C family
  python3 phase3_unified.py --instance-type c5.large --strategy horizontal --codec libx265

  # Melhoria 2: Regional validation
  python3 phase3_unified.py --instance-type t3.micro --strategy horizontal --codec libx264 --region sa-east-1

  # Melhoria 3: ARM Graviton
  python3 phase3_unified.py --instance-type t4g.micro --strategy horizontal --codec libx264

  # Multiple runs
  python3 phase3_unified.py --instance-type c5.large --strategy horizontal --codec libx265 --runs 30
"""

import os
import sys
import time
import argparse
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import boto3
import paramiko


# ============================================================================
# INSTANCE CONFIGURATION DATABASE
# ============================================================================

INSTANCE_DB = {
    # --- x86 Burstable (T) ---
    "t3.micro": {
        "family": "T", "arch": "x86_64",
        "horizontal_type": "t3.micro", "vertical_type": "t3.2xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz",
    },
    "t3.2xlarge": {
        "family": "T", "arch": "x86_64",
        "horizontal_type": "t3.micro", "vertical_type": "t3.2xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz",
    },
    # --- x86 General Purpose (M) ---
    "m5.large": {
        "family": "M", "arch": "x86_64",
        "horizontal_type": "m5.large", "vertical_type": "m5.4xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz",
    },
    "m5.4xlarge": {
        "family": "M", "arch": "x86_64",
        "horizontal_type": "m5.large", "vertical_type": "m5.4xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8259CL CPU @ 2.50GHz",
    },
    # --- x86 Compute Optimized (C) ---
    "c5.large": {
        "family": "C", "arch": "x86_64",
        "horizontal_type": "c5.large", "vertical_type": "c5.4xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz",
    },
    "c5.4xlarge": {
        "family": "C", "arch": "x86_64",
        "horizontal_type": "c5.large", "vertical_type": "c5.4xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": "Intel(R) Xeon(R) Platinum 8275CL CPU @ 3.00GHz",
    },
    # --- ARM Graviton — Burstable (T4g) ---
    "t4g.micro": {
        "family": "T-ARM", "arch": "aarch64",
        "horizontal_type": "t4g.micro", "vertical_type": "t4g.2xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": None,  # Will be discovered
    },
    "t4g.2xlarge": {
        "family": "T-ARM", "arch": "aarch64",
        "horizontal_type": "t4g.micro", "vertical_type": "t4g.2xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": None,
    },
    # --- ARM Graviton — General Purpose (M7g) ---
    "m7g.large": {
        "family": "M-ARM", "arch": "aarch64",
        "horizontal_type": "m7g.large", "vertical_type": "m7g.4xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": None,
    },
    "m7g.4xlarge": {
        "family": "M-ARM", "arch": "aarch64",
        "horizontal_type": "m7g.large", "vertical_type": "m7g.4xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": None,
    },
    # --- ARM Graviton — Compute Optimized (C7g) ---
    "c7g.large": {
        "family": "C-ARM", "arch": "aarch64",
        "horizontal_type": "c7g.large", "vertical_type": "c7g.4xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": None,
    },
    "c7g.4xlarge": {
        "family": "C-ARM", "arch": "aarch64",
        "horizontal_type": "c7g.large", "vertical_type": "c7g.4xlarge",
        "horizontal_threads": 5, "vertical_threads": 10,
        "expected_cpu": None,
    },
}


# AMI database: region → arch → ami_id
AMI_DB = {
    "us-east-1": {
        "x86_64":  "ami-06c7c20c67513469a",
        "aarch64": "ami-0976d56fa61f42304",
    },
    "sa-east-1": {
        "x86_64":  "ami-0653a33fe2919af93",
        "aarch64": "ami-0ecbc0dab130caeda",
    },
}

# AWS credentials configuration per region
AWS_KEYS = {
    "us-east-1": {
        "key_name": "<aws-key-pair-name>",
        "security_groups": ["<aws-security-group-name>"],
        "local_key_path": os.path.expanduser(
            "~/doutorado/artifact/artifact/artifacts2/aws-key.pem"
        ),
    },
    "sa-east-1": {
        "key_name": "<author>-sa",
        "security_groups": ["<author>Group-sa"],
        "local_key_path": os.path.expanduser(
            "~/doutorado/artifact/artifact/artifacts2/<author>-sa.pem"
        ),
    },
}

# Codec-specific FFmpeg parameters
CODEC_PARAMS = {
    "libx264": {
        "ffmpeg_codec": "libx264",
        "preset": "slow",
        "bitrate": "2M",
        "output_ext": "mp4",
    },
    "libx265": {
        "ffmpeg_codec": "libx265",
        "preset": "slow",
        "bitrate": "2M",
        "output_ext": "mp4",
    },
    "libvpx-vp9": {
        "ffmpeg_codec": "libvpx-vp9",
        "preset": "slow",
        "bitrate": "2M",
        "output_ext": "mp4",
    },
}

INPUT_VIDEO = os.path.expanduser(
    "~/doutorado/artifact/artifacts/test_videos/video_repetido_10min.mp4"
)


# ============================================================================
# LOGGING
# ============================================================================

def log(msg, context=None):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    context_info = f" [{context}]" if context else ""
    print(f"[{timestamp}]{context_info} {msg}")


# ============================================================================
# FFmpeg COMMAND BUILDER
# ============================================================================

def build_ffmpeg_cmd(codec_key, threads, input_path="/home/ubuntu/input.mp4",
                     output_path="/home/ubuntu/output"):
    """Build the FFmpeg command string for the given codec configuration."""
    cp = CODEC_PARAMS[codec_key]
    output_file = f"{output_path}.{cp['output_ext']}"

    cmd_parts = [
        "ffmpeg", "-i", input_path,
        "-c:v", cp["ffmpeg_codec"],
        "-preset", cp["preset"],
        "-b:v", cp["bitrate"],
        "-threads", str(threads),
        output_file
    ]

    return " ".join(cmd_parts), output_file


# ============================================================================
# STRATEGY: HORIZONTAL (N × small instances)
# ============================================================================

def run_horizontal(args, instance_type, threads, ami_id, aws_keys):
    """Run horizontal scaling: N × small instances (parallel chunks) repeated N times."""
    num_parts = args.num_parts
    max_workers = args.max_workers or num_parts
    base_dir = os.path.dirname(os.path.abspath(__file__))
    parts_dir = os.path.join(base_dir, f"video_parts_{instance_type.replace('.', '_')}_{args.codec}")
    compressed_dir = os.path.join(base_dir, f"compressed_{instance_type.replace('.', '_')}_{args.codec}")

    log(f"=== Phase 3.2 Horizontal: {num_parts}x {instance_type} ===")
    log(f"AMI: {ami_id} | Codec: {args.codec} | Threads: {threads} | Runs: {args.runs}")
    
    results = []

    for run_idx in range(1, args.runs + 1):
        log(f"--- Horizontal Run {run_idx}/{args.runs} ---")
        run_start = time.time()
        
        # 1. Split video
        log("Splitting video...", "Setup")
        os.makedirs(parts_dir, exist_ok=True)
        os.makedirs(compressed_dir, exist_ok=True)
        # Clear previous segments
        for f in os.listdir(parts_dir): os.remove(os.path.join(parts_dir, f))
        for f in os.listdir(compressed_dir): os.remove(os.path.join(compressed_dir, f))

        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", INPUT_VIDEO],
            capture_output=True, text=True
        )
        duration = float(result.stdout.strip())
        part_duration = duration / num_parts

        for i in range(num_parts):
            output_file = f"{parts_dir}/part_{i:02d}.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-i", INPUT_VIDEO, "-ss", str(i * part_duration),
                "-t", str(part_duration), "-c", "copy", output_file
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 2. Parallel Processing
        def process_part(part_index):
            context = f"Part {part_index:02d}"
            ec2 = boto3.client('ec2', region_name=args.region)
            instance_id, ssh_client = None, None
            try:
                response = ec2.run_instances(
                    ImageId=ami_id, InstanceType=instance_type,
                    KeyName=aws_keys['key_name'],
                    SecurityGroups=aws_keys['security_groups'],
                    MinCount=1, MaxCount=1
                )
                instance_id = response['Instances'][0]['InstanceId']
                ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
                instance = ec2.describe_instances(InstanceIds=[instance_id])
                public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']
                time.sleep(25)

                ssh_client = paramiko.SSHClient()
                ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh_client.connect(public_ip, username="ubuntu", key_filename=aws_keys['local_key_path'])

                sftp = ssh_client.open_sftp()
                part_file = f"{parts_dir}/part_{part_index:02d}.mp4"
                sftp.put(part_file, "/home/ubuntu/input.mp4")

                cmd, remote_output = build_ffmpeg_cmd(args.codec, threads)
                ssh_client.exec_command(cmd)
                
                # Check exit status
                stdin, stdout, stderr = ssh_client.exec_command("echo $?")
                if stdout.read().decode().strip() != "0":
                    raise RuntimeError("FFmpeg failed")

                ext = CODEC_PARAMS[args.codec]["output_ext"]
                local_output = f"{compressed_dir}/part_{part_index:02d}_compressed.{ext}"
                sftp.get(remote_output, local_output)
                sftp.close()
            finally:
                if ssh_client: ssh_client.close()
                if instance_id: ec2.terminate_instances(InstanceIds=[instance_id])

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.map(process_part, range(num_parts))

        results.append(time.time() - run_start)
        log(f"Horizontal Run {run_idx} completed in {results[-1]:.2f}s")
    
    return results


# ============================================================================
# STRATEGY: VERTICAL (1 × large instance)
# ============================================================================

def run_vertical(args, instance_type, threads, ami_id, aws_keys):
    """Run vertical: single large instance encodes full video N times."""
    context = f"{instance_type}-Vertical"
    ec2 = boto3.client('ec2', region_name=args.region)
    instance_id, ssh_client = None, None

    log(f"=== Phase 3.2 Vertical: 1x {instance_type} ===")
    log(f"AMI: {ami_id} | Codec: {args.codec} | Threads: {threads} | Runs: {args.runs}")

    results = []
    try:
        # SETUP PHASE (Once)
        setup_start = time.time()
        log("Launching EC2 instance...", context)
        response = ec2.run_instances(
            ImageId=ami_id, InstanceType=instance_type,
            KeyName=aws_keys['key_name'],
            SecurityGroups=aws_keys['security_groups'],
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
        ssh_client.connect(public_ip, username="ubuntu",
                           key_filename=aws_keys['local_key_path'])
        log("SSH connected.", context)

        # UPLOAD (Once)
        log("Uploading 10-minute video...", context)
        sftp = ssh_client.open_sftp()
        sftp.put(INPUT_VIDEO, "/home/ubuntu/input.mp4")
        sftp.close()
        log("Upload complete.", context)
        setup_end = time.time()
        log(f"SETUP AND UPLOAD TIME: {setup_end - setup_start:.2f}s", context)

        # REPETITION LOOP
        for run_idx in range(1, args.runs + 1):
            log(f"--- Run {run_idx}/{args.runs} ---", context)
            run_start = time.time()
            
            cmd, _ = build_ffmpeg_cmd(args.codec, threads)
            ssh_client.exec_command("rm -f /home/ubuntu/output.mp4")
            
            log(f"Running: {cmd}", context)
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                err = stderr.read().decode()
                log(f"ERROR: FFmpeg failed (exit {exit_status}): {err[-200:]}", context)
                continue
                
            run_end = time.time()
            elapsed = run_end - run_start
            results.append(elapsed)
            log(f"Done: {elapsed:.2f}s", context)
            
            if run_idx < args.runs:
                time.sleep(5)

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

    return results


# ============================================================================
# STRATEGY: SERIAL (Baselines)
# ============================================================================

def run_serial(args, instance_type, threads, ami_id, aws_keys):
    """Run serial baseline: single instance encodes the full video N times."""
    context = f"{instance_type}-Serial"
    ec2 = boto3.client('ec2', region_name=args.region)
    instance_id, ssh_client = None, None

    log(f"=== Phase 3.2 Serial: 1x {instance_type} ===")
    log(f"AMI: {ami_id} | Codec: {args.codec} | Threads: {threads} | Runs: {args.runs}")

    if not os.path.exists(INPUT_VIDEO):
        log(f"ERROR: Video not found: {INPUT_VIDEO}", context)
        return None

    results = []
    try:
        # 1. SETUP PHASE (Once per instance)
        setup_start = time.time()
        log("Launching EC2 instance...", context)
        response = ec2.run_instances(
            ImageId=ami_id, InstanceType=instance_type,
            KeyName=aws_keys['key_name'],
            SecurityGroups=aws_keys['security_groups'],
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
        ssh_client.connect(public_ip, username="ubuntu",
                           key_filename=aws_keys['local_key_path'])
        log("SSH connected.", context)

        # 2. DATA PREP (Once per instance)
        log("Uploading 10-minute video...", context)
        sftp = ssh_client.open_sftp()
        sftp.put(INPUT_VIDEO, "/home/ubuntu/input.mp4")
        sftp.close()
        log("Upload complete.", context)
        setup_end = time.time()
        log(f"SETUP AND UPLOAD TIME: {setup_end - setup_start:.2f}s", context)

        # 3. REPETITION LOOP
        for run_idx in range(1, args.runs + 1):
            log(f"--- Run {run_idx}/{args.runs} ---", context)
            run_start = time.time()
            
            cmd, _ = build_ffmpeg_cmd(args.codec, threads)
            # Remove output if exists from previous run
            ssh_client.exec_command("rm -f /home/ubuntu/output.mp4")
            
            log(f"Running: {cmd}", context)
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                err = stderr.read().decode()
                log(f"ERROR: FFmpeg failed (exit {exit_status}): {err[-200:]}", context)
                continue
                
            run_end = time.time()
            elapsed = run_end - run_start
            results.append(elapsed)
            log(f"Done: {elapsed:.2f}s", context)
            
            if run_idx < args.runs:
                time.sleep(5)

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

    return results


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Unified Phase 3 benchmark script for this study",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--instance-type", required=True,
        choices=list(INSTANCE_DB.keys()),
        help="EC2 instance type to use"
    )
    parser.add_argument(
        "--strategy", required=True,
        choices=["horizontal", "vertical", "serial"],
        help="Scaling strategy:\n"
             "  horizontal: N \u00d7 small instances (parallel chunks)\n"
             "  vertical:   1 \u00d7 large instance (full video, many threads)\n"
             "  serial:     1 \u00d7 small instance (full video, baseline)"
    )
    parser.add_argument(
        "--codec", required=True,
        choices=["libx264", "libx265", "libvpx-vp9"],
        help="Video codec for FFmpeg"
    )
    parser.add_argument(
        "--region", default="us-east-1",
        choices=["us-east-1", "sa-east-1"],
        help="AWS region (default: us-east-1)"
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of repetitions (default: 1)"
    )
    parser.add_argument(
        "--num-parts", type=int, default=10,
        help="Number of chunks for horizontal strategy (default: 10)"
    )
    parser.add_argument(
        "--max-workers", type=int, default=None,
        help="Max parallel workers for horizontal (default: same as --num-parts)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print configuration and exit without launching instances"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Resolve instance type based on strategy
    db_entry = INSTANCE_DB[args.instance_type]

    if args.strategy == "horizontal":
        effective_type = db_entry["horizontal_type"]
        threads = db_entry["horizontal_threads"]
    elif args.strategy == "vertical":
        effective_type = db_entry["vertical_type"]
        threads = db_entry["vertical_threads"]
    else:  # serial
        effective_type = db_entry["horizontal_type"]
        threads = db_entry["horizontal_threads"]

    # Resolve AMI
    arch = db_entry["arch"]
    ami_id = AMI_DB.get(args.region, {}).get(arch)
    if not ami_id:
        log(f"ERROR: AMI not configured for {args.region}/{arch}")
        return

    # Resolve AWS keys
    aws_keys = AWS_KEYS.get(args.region)
    if not aws_keys:
        log(f"ERROR: AWS keys not configured for region {args.region}")
        return

    # Print configuration
    log("=" * 70)
    log(f"CONFIGURATION")
    log(f"  Instance type:  {args.instance_type} \u2192 effective: {effective_type}")
    log(f"  Strategy:       {args.strategy}")
    log(f"  Codec:          {args.codec}")
    log(f"  Threads:        {threads}")
    log(f"  Region:         {args.region}")
    log(f"  AMI:            {ami_id}")
    log(f"  Architecture:   {arch}")
    log(f"  Runs:           {args.runs}")
    log("=" * 70)

    if args.dry_run:
        log("DRY RUN \u2014 exiting without launching instances.")
        return

    # Strategy dispatch
    strategy_fn = {
        "horizontal": run_horizontal,
        "vertical":   run_vertical,
        "serial":     run_serial,
    }[args.strategy]

    # Run the strategy once (it handles N repetitions internally now)
    results = strategy_fn(args, effective_type, threads, ami_id, aws_keys)

    # Summary
    if results:
        import statistics
        log("\n" + "=" * 70)
        log(f"AGGREGATE RESULTS \u2014 {len(results)}/{args.runs} successful runs")
        log(f"  Instance:  {effective_type} | Strategy: {args.strategy}")
        log(f"  Codec:     {args.codec}")
        log(f"  Mean:      {statistics.mean(results):.2f}s")
        log(f"  Median:    {statistics.median(results):.2f}s")
        if len(results) > 1:
            log(f"  Stdev:     {statistics.stdev(results):.2f}s")
        log(f"  Min:       {min(results):.2f}s")
        log(f"  Max:       {max(results):.2f}s")
        log("=" * 70)


if __name__ == "__main__":
    # Build log filename
    import sys
    log_filename = f"phase3_unified_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

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

    with open(log_filename, "w") as logfile:
        tee = Tee(sys.__stdout__, logfile)
        sys.stdout = sys.stderr = tee
        try:
            main()
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
