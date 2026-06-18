import boto3
import paramiko
import time
import os
import argparse
from datetime import datetime

# Configuration
CONFIG = {
    "ami_id": "ami-0a313d6098716f372",  # Standard Ubuntu 22.04 LTS for Phase 1
    "key_name": "<aws-key-pair-name>",
    "security_groups": ["<aws-security-group-name>"],
    "region": "us-east-1",
    "local_key_path": "./aws-key.pem",
}

# New Instance Families for Phase 1
INSTANCE_TYPES = [
    "c5.large", "c5.xlarge", "c5.2xlarge", "c5.4xlarge",
    "m5.large", "m5.xlarge", "m5.2xlarge", "m5.4xlarge"
]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def ensure_dirs(instance_type, zone):
    path = f"artifacts2/phase1_homogeneity/cpu_verification_logs/{instance_type}/{zone}"
    os.makedirs(path, exist_ok=True)
    return path

def run_verification(instance_type, iterations=100):
    ec2 = boto3.client('ec2', region_name=CONFIG['region'])
    
    log(f"🚀 Starting Phase 1 Homogeneity Check for {instance_type} ({iterations} iterations)")
    
    for i in range(1, iterations + 1):
        try:
            log(f"--- Iteration {i}/{iterations} for {instance_type} ---")
            
            # Launch Instance
            response = ec2.run_instances(
                ImageId=CONFIG['ami_id'],
                InstanceType=instance_type,
                KeyName=CONFIG['key_name'],
                SecurityGroups=CONFIG['security_groups'],
                MinCount=1, MaxCount=1,
                TagSpecifications=[{'ResourceType': 'instance', 'Tags': [{'Key': 'Name', 'Value': f'Phase1-Homogeneity-{instance_type}-{i}'}]}]
            )
            instance_id = response['Instances'][0]['InstanceId']
            zone = response['Instances'][0]['Placement']['AvailabilityZone'][-1] # e.g., 'a', 'b'
            log(f"🆔 Launched {instance_id} in zone {zone}")
            
            # Wait for Running
            ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
            instance = ec2.describe_instances(InstanceIds=[instance_id])
            public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']
            log(f"🌐 Public IP: {public_ip}")
            
            # Wait for SSH
            time.sleep(30) # Give some time for SSH to be ready
            
            # Connect and Get CPU Info
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(public_ip, username="ubuntu", key_filename=CONFIG['local_key_path'])
            
            stdin, stdout, stderr = ssh.exec_command("cat /proc/cpuinfo")
            cpu_info = stdout.read().decode()
            
            # Save Log
            log_dir = ensure_dirs(instance_type, zone)
            filename = f"cpuinfo-{instance_type}-us-east-1-us-east-1{zone}-{i}.log"
            filepath = os.path.join(log_dir, filename)
            
            with open(filepath, "w") as f:
                f.write(cpu_info)
            log(f"💾 Saved CPU info to {filepath}")
            
            ssh.close()
            
        except Exception as e:
            log(f"❌ Error in iteration {i}: {e}")
            
        finally:
            # Terminate
            if 'instance_id' in locals():
                log(f"🧹 Terminating {instance_id}...")
                ec2.terminate_instances(InstanceIds=[instance_id])

CONST_ITERATIONS = 100

def main():
    print(f"🚀 Starting Phase 1 Homogeneity Check")
    print(f"Target: {CONST_ITERATIONS} iterations per instance type")
    print(f"Instance Types: {INSTANCE_TYPES}")
    
    for instance_type in INSTANCE_TYPES:
        run_verification(instance_type, CONST_ITERATIONS)

if __name__ == "__main__":
    main()
