#!/usr/bin/env python3
"""
Step 1: Create a custom AMI with ffmpeg pre-installed.
Launches an Ubuntu instance, installs ffmpeg, creates AMI, terminates instance.
"""
import time
import sys
from datetime import datetime
import boto3

AWS_CONFIG = {
    "ami_id": "ami-0a313d6098716f372",  # Standard Ubuntu 22.04 LTS
    "key_name": "<aws-key-pair-name>",
    "security_groups": ["<aws-security-group-name>"],
    "region": "us-east-1",
    "local_key_path": "./artifact/artifacts2/aws-key.pem",
}

import paramiko

def log(msg):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {msg}")

def create_ami():
    ec2 = boto3.client('ec2', region_name=AWS_CONFIG['region'])
    instance_id = None

    try:
        # 1. Launch instance
        log("Step 1/5: Launching Ubuntu instance (t3.micro)...")
        response = ec2.run_instances(
            ImageId=AWS_CONFIG['ami_id'], InstanceType="t3.micro",
            KeyName=AWS_CONFIG['key_name'], SecurityGroups=AWS_CONFIG['security_groups'],
            MinCount=1, MaxCount=1
        )
        instance_id = response['Instances'][0]['InstanceId']
        log(f"  Instance {instance_id} launched. Waiting for running state...")

        ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
        instance = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']
        log(f"  Instance ready. IP: {public_ip}")

        time.sleep(30)

        # 2. SSH and install ffmpeg
        log("Step 2/5: Connecting via SSH...")
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(public_ip, username="ubuntu", key_filename=AWS_CONFIG['local_key_path'])
        log("  SSH connected.")

        log("Step 3/5: Installing ffmpeg...")
        for cmd in ["sudo apt-get update -y", "sudo apt-get install -y ffmpeg"]:
            log(f"  Running: {cmd}")
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                log(f"  WARNING: exit code {exit_status}")
            else:
                log(f"  OK")

        # Verify
        stdin, stdout, stderr = ssh_client.exec_command("ffmpeg -version | head -1")
        version = stdout.read().decode().strip()
        log(f"  ffmpeg version: {version}")
        ssh_client.close()

        # 3. Stop instance before creating AMI
        log("Step 4/5: Stopping instance for AMI creation...")
        ec2.stop_instances(InstanceIds=[instance_id])
        ec2.get_waiter('instance_stopped').wait(InstanceIds=[instance_id])
        log("  Instance stopped.")

        # 4. Create AMI
        log("Step 5/5: Creating AMI...")
        ami_response = ec2.create_image(
            InstanceId=instance_id,
            Name=f"anon-ffmpeg-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            Description="Ubuntu 22.04 with ffmpeg pre-installed for Phase 3.2 experiments"
        )
        new_ami_id = ami_response['ImageId']
        log(f"  AMI creation started: {new_ami_id}")
        log(f"  Waiting for AMI to become available (this takes a few minutes)...")

        ec2.get_waiter('image_available').wait(ImageIds=[new_ami_id])
        log(f"  AMI {new_ami_id} is now AVAILABLE!")

        # 5. Terminate instance
        ec2.terminate_instances(InstanceIds=[instance_id])
        log("  Source instance terminated.")
        instance_id = None  # Don't terminate again in finally

        log("=" * 60)
        log(f"SUCCESS! Custom AMI ID: {new_ami_id}")
        log(f"Use this AMI in your Phase 3.2 scripts.")
        log("=" * 60)

        return new_ami_id

    except Exception as e:
        log(f"ERROR: {str(e)}")
        raise
    finally:
        if instance_id:
            ec2.terminate_instances(InstanceIds=[instance_id])
            log("Instance terminated (cleanup).")


if __name__ == "__main__":
    ami_id = create_ami()
    # Save AMI ID to file for other scripts to use
    with open("custom_ami_id.txt", "w") as f:
        f.write(ami_id)
    log(f"AMI ID saved to custom_ami_id.txt: {ami_id}")
