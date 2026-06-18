#!/usr/bin/env python3
"""
Prerequisite 2: Copy AMIs from us-east-1 to sa-east-1.

Copies both x86 and ARM custom AMIs to the São Paulo region.
After running, update AMI_DB["sa-east-1"] in phase3_unified.py.
"""

import sys
import time
import boto3
from datetime import datetime

SOURCE_REGION = "us-east-1"
DEST_REGION = "sa-east-1"

# AMIs to copy (update after running prereq_1)
AMIS_TO_COPY = {
    "x86_64": {
        "source_ami": "ami-06c7c20c67513469a",  # Existing x86 custom AMI
        "name": "anon-ubuntu2204-x86-ffmpeg-sa",
        "description": "Ubuntu 22.04 x86 + FFmpeg (copied from us-east-1) for this study",
    },
    "aarch64": {
        "source_ami": "ami-0976d56fa61f42304",  # Created via prereq_1
        "name": "anon-ubuntu2204-arm64-ffmpeg-sa",
        "description": "Ubuntu 22.04 ARM64 + FFmpeg (copied from us-east-1) for this study",
    },
}


def log(msg):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {msg}")


def main():
    ec2_dest = boto3.client('ec2', region_name=DEST_REGION)

    results = {}

    for arch, config in AMIS_TO_COPY.items():
        source_ami = config["source_ami"]

        if "PLACEHOLDER" in source_ami:
            log(f"SKIP {arch}: source AMI is placeholder. Run prereq_1 first.")
            continue

        log(f"Copying {arch} AMI {source_ami} from {SOURCE_REGION} to {DEST_REGION}...")

        response = ec2_dest.copy_image(
            Name=config["name"],
            Description=config["description"],
            SourceImageId=source_ami,
            SourceRegion=SOURCE_REGION,
        )

        new_ami_id = response['ImageId']
        results[arch] = new_ami_id
        log(f"  Copy initiated: {new_ami_id}")

    if not results:
        log("No AMIs to copy. Exiting.")
        return

    # Wait for all copies to complete
    log("Waiting for all AMI copies to complete (may take 10-20 minutes)...")
    for arch, ami_id in results.items():
        log(f"  Waiting for {arch} AMI {ami_id}...")
        ec2_dest.get_waiter('image_available').wait(ImageIds=[ami_id])
        log(f"  ✅ {arch} AMI ready: {ami_id}")

    # Print summary
    log("")
    log("=" * 70)
    log("UPDATE phase3_unified.py AMI_DB:")
    for arch, ami_id in results.items():
        log(f'  AMI_DB["sa-east-1"]["{arch}"] = "{ami_id}"')
    log("=" * 70)


if __name__ == "__main__":
    main()
