#!/usr/bin/env python3
"""
Prerequisite 1: Create ARM AMI with FFmpeg pre-installed in us-east-1.

Launches a t4g.micro instance from the official Ubuntu 22.04 ARM64 AMI,
installs FFmpeg + x265 + libvpx (VP9), then creates a custom AMI.

After running, update AMI_DB["us-east-1"]["aarch64"] in phase3_unified.py.
"""

import sys
import time
import boto3
import paramiko
from datetime import datetime

REGION = "us-east-1"
INSTANCE_TYPE = "t4g.micro"  # Cheapest ARM instance for AMI creation

# Official Ubuntu 22.04 LTS ARM64 AMI for us-east-1
# NOTE: This AMI ID may change. Find the latest at:
#   aws ec2 describe-images --region us-east-1 --owners 099720109477 \
#     --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*" \
#     --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId'
BASE_AMI = "ami-028f4acf86df833a8"  # Ubuntu 22.04 ARM64

KEY_NAME = "<aws-key-pair-name>"
SECURITY_GROUPS = ["<aws-security-group-name>"]
LOCAL_KEY_PATH = "./artifact/artifacts2/aws-key.pem"

AMI_NAME = "anon-ubuntu2204-arm64-ffmpeg"
AMI_DESCRIPTION = "Ubuntu 22.04 ARM64 + FFmpeg 6.x (libx264, libx265, libvpx-vp9) for this study"

# Commands to install FFmpeg with all required codecs
INSTALL_COMMANDS = [
    "sudo apt-get update -y",
    "sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y",
    "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg libx265-dev libvpx-dev",
    # Verify installation
    "ffmpeg -version",
    "ffmpeg -encoders 2>/dev/null | grep -E 'libx264|libx265|libvpx'",
]


def log(msg):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {msg}")


def main():
    ec2 = boto3.client('ec2', region_name=REGION)
    ec2_resource = boto3.resource('ec2', region_name=REGION)
    instance_id = None
    ssh_client = None

    try:
        # Step 1: Launch base instance
        log(f"Launching {INSTANCE_TYPE} from base AMI {BASE_AMI}...")
        response = ec2.run_instances(
            ImageId=BASE_AMI,
            InstanceType=INSTANCE_TYPE,
            KeyName=KEY_NAME,
            SecurityGroups=SECURITY_GROUPS,
            MinCount=1, MaxCount=1,
        )
        instance_id = response['Instances'][0]['InstanceId']
        log(f"Instance {instance_id} launched. Waiting for running state...")

        ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
        instance = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']
        log(f"Instance running. IP: {public_ip}")

        # Wait for SSH
        log("Waiting 60s for SSH readiness...")
        time.sleep(60)

        # Step 2: Connect via SSH
        log("Connecting via SSH...")
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(public_ip, username="ubuntu", key_filename=LOCAL_KEY_PATH)
        log("SSH connected.")

        # Step 3: Install FFmpeg + codecs
        for cmd in INSTALL_COMMANDS:
            log(f"Running: {cmd}")
            stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=300)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode().strip()
            errors = stderr.read().decode().strip()
            if output:
                for line in output.split('\n')[-5:]:  # Last 5 lines
                    log(f"  stdout: {line}")
            if exit_status != 0:
                log(f"  WARNING: Command exited with status {exit_status}")
                if errors:
                    for line in errors.split('\n')[-3:]:
                        log(f"  stderr: {line}")

        # Verify CPU info (for the paper)
        log("Checking CPU info...")
        stdin, stdout, stderr = ssh_client.exec_command("cat /proc/cpuinfo | head -20")
        log(f"  CPU info:\n{stdout.read().decode()}")

        ssh_client.close()
        ssh_client = None

        # Step 4: Stop instance before creating AMI
        log("Stopping instance for AMI creation...")
        ec2.stop_instances(InstanceIds=[instance_id])
        ec2.get_waiter('instance_stopped').wait(InstanceIds=[instance_id])
        log("Instance stopped.")

        # Step 5: Create AMI
        log(f"Creating AMI: {AMI_NAME}...")
        ami_response = ec2.create_image(
            InstanceId=instance_id,
            Name=AMI_NAME,
            Description=AMI_DESCRIPTION,
            NoReboot=True,
        )
        new_ami_id = ami_response['ImageId']
        log(f"AMI creation initiated: {new_ami_id}")
        log("Waiting for AMI to become available (this may take 5-10 minutes)...")

        ec2.get_waiter('image_available').wait(ImageIds=[new_ami_id])
        log(f"✅ AMI READY: {new_ami_id}")
        log("")
        log("=" * 70)
        log(f"UPDATE phase3_unified.py:")
        log(f'  AMI_DB["us-east-1"]["aarch64"] = "{new_ami_id}"')
        log("=" * 70)

    except Exception as e:
        log(f"ERROR: {str(e)}")
        raise
    finally:
        if ssh_client:
            try: ssh_client.close()
            except: pass
        if instance_id:
            log(f"Terminating instance {instance_id}...")
            ec2.terminate_instances(InstanceIds=[instance_id])
            log("Instance terminated.")


if __name__ == "__main__":
    main()
