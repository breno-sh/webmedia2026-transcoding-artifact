import boto3
import time
import paramiko
from datetime import datetime

AWS_CONFIG = {
    "ami_id": "ami-0a0e5d9c7acc336f1",  # Standard Ubuntu 22.04 LTS
    "key_name": "<aws-key-pair-name>",
    "security_groups": ["<aws-security-group-name>"],
    "region": "us-east-1",
    "local_key_path": "./artifact/artifacts2/aws-key.pem",
}

def log(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}")

ec2 = boto3.client('ec2', region_name=AWS_CONFIG['region'])

log("Launching base Ubuntu 22.04 instance for AMI generation...")
response = ec2.run_instances(
    ImageId=AWS_CONFIG['ami_id'], 
    InstanceType='t3.micro',  # Cheap instance just for baking
    KeyName=AWS_CONFIG['key_name'], 
    SecurityGroups=AWS_CONFIG['security_groups'],
    MinCount=1, MaxCount=1
)
instance_id = response['Instances'][0]['InstanceId']
log(f"Instance {instance_id} launched. Waiting for Running state...")

ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
instance = ec2.describe_instances(InstanceIds=[instance_id])
public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']
log(f"Instance ready. IP: {public_ip}. Waiting 30s for SSH daemon...")
time.sleep(30)

ssh_client = paramiko.SSHClient()
ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_client.connect(public_ip, username="ubuntu", key_filename=AWS_CONFIG['local_key_path'])
log("SSH connected. Installing FFmpeg...")

for cmd in ["sudo apt-get update -y", "sudo apt-get install -y ffmpeg"]:
    stdin, stdout, stderr = ssh_client.exec_command(cmd)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        log(f"WARNING: '{cmd}' failed!")
ssh_client.close()
log("FFmpeg successfully installed on base instance.")

log("Creating AMI Image from instance...")
ami_response = ec2.create_image(
    InstanceId=instance_id,
    Name=f"Ubuntu-22.04-FFmpeg-Phase3-{int(time.time())}",
    Description="Official Ubuntu 22.04 LTS with pre-installed FFmpeg for Phase 3.2",
    NoReboot=True
)
new_ami_id = ami_response['ImageId']
log(f"AMI Creation initiated! New AMI ID: {new_ami_id}")
log("Waiting for AMI to become available (this takes a few minutes)...")

ec2.get_waiter('image_available').wait(ImageIds=[new_ami_id])
log(f"Success! The new official AMI '{new_ami_id}' is ready.")

log("Terminating base instance...")
ec2.terminate_instances(InstanceIds=[instance_id])
log("Done.")
