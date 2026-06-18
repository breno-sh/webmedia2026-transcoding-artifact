#!/usr/bin/env python3
"""
Prerequisite 3: Set up Key Pair and Security Group in sa-east-1.

Creates the necessary AWS resources in the São Paulo region:
  1. Key Pair (downloads .pem file)
  2. Security Group (allows SSH inbound from anywhere)

After running, update AWS_KEYS["sa-east-1"] in phase3_unified.py.
"""

import os
import sys
import boto3
from datetime import datetime

REGION = "sa-east-1"
KEY_NAME = "<author>-sa"
SG_NAME = "<author>Group-sa"
SG_DESCRIPTION = "this study - SSH access for Phase 3 experiments (sa-east-1)"

# Where to save the key pair .pem file
KEY_DIR = os.path.expanduser(
    "~/doutorado/artifact/artifact/artifacts2"
)
KEY_PATH = os.path.join(KEY_DIR, f"{KEY_NAME}.pem")


def log(msg):
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"[{timestamp}] {msg}")


def create_key_pair(ec2):
    """Create key pair and save .pem file."""
    log(f"Creating key pair '{KEY_NAME}' in {REGION}...")

    # Check if already exists
    try:
        ec2.describe_key_pairs(KeyNames=[KEY_NAME])
        log(f"  Key pair '{KEY_NAME}' already exists. Skipping creation.")
        log(f"  If you need to recreate it, delete it first:")
        log(f"    aws ec2 delete-key-pair --key-name {KEY_NAME} --region {REGION}")
        return
    except ec2.exceptions.ClientError:
        pass  # Key doesn't exist, proceed with creation

    response = ec2.create_key_pair(
        KeyName=KEY_NAME,
        KeyType='rsa',
        KeyFormat='pem',
    )

    # Save private key
    os.makedirs(KEY_DIR, exist_ok=True)
    with open(KEY_PATH, 'w') as f:
        f.write(response['KeyMaterial'])
    os.chmod(KEY_PATH, 0o400)

    log(f"  ✅ Key pair created and saved to: {KEY_PATH}")


def create_security_group(ec2):
    """Create security group with SSH access."""
    log(f"Creating security group '{SG_NAME}' in {REGION}...")

    # Check if already exists
    try:
        response = ec2.describe_security_groups(GroupNames=[SG_NAME])
        sg_id = response['SecurityGroups'][0]['GroupId']
        log(f"  Security group '{SG_NAME}' already exists (ID: {sg_id}). Skipping.")
        return sg_id
    except ec2.exceptions.ClientError:
        pass  # SG doesn't exist, proceed with creation

    # Get default VPC
    vpc_response = ec2.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])
    if not vpc_response['Vpcs']:
        log("  ERROR: No default VPC found in sa-east-1. Create one first.")
        return None
    vpc_id = vpc_response['Vpcs'][0]['VpcId']
    log(f"  Using default VPC: {vpc_id}")

    # Create SG
    response = ec2.create_security_group(
        GroupName=SG_NAME,
        Description=SG_DESCRIPTION,
        VpcId=vpc_id,
    )
    sg_id = response['GroupId']

    # Add SSH ingress rule
    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[{
            'IpProtocol': 'tcp',
            'FromPort': 22,
            'ToPort': 22,
            'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'SSH from anywhere'}],
        }],
    )

    log(f"  ✅ Security group created: {sg_id} (SSH inbound from 0.0.0.0/0)")
    return sg_id


def main():
    ec2 = boto3.client('ec2', region_name=REGION)

    log(f"Setting up AWS resources in {REGION}...")
    log("")

    create_key_pair(ec2)
    log("")

    sg_id = create_security_group(ec2)
    log("")

    log("=" * 70)
    log("SETUP COMPLETE. Update phase3_unified.py AWS_KEYS:")
    log(f'  AWS_KEYS["sa-east-1"] = {{')
    log(f'      "key_name": "{KEY_NAME}",')
    log(f'      "security_groups": ["{SG_NAME}"],')
    log(f'      "local_key_path": "{KEY_PATH}",')
    log(f'  }}')
    log("=" * 70)
    log("")
    log("EXECUTION ORDER:")
    log("  1. ✅ This script (prereq_3) — key pair + security group in sa-east-1")
    log("  2. Run prereq_1_create_arm_ami.py — create ARM AMI in us-east-1")
    log("  3. Run prereq_2_copy_amis_sa_east.py — copy AMIs to sa-east-1")
    log("  4. Update AMI_DB and AWS_KEYS in phase3_unified.py")
    log("  5. Run experiments with run_all_experiments.py")


if __name__ == "__main__":
    main()
