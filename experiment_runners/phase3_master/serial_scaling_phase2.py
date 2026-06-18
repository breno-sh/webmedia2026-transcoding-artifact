#!/usr/bin/env python3
"""
Serial/Vertical Scaling Script (Phase 3.2 - Optimized AMI).
Runs a SINGLE instance that processes the entire 10-minute video.
Used for both:
  - Serial baseline (1x smallest instance)
  - Vertical scaling (1x largest instance)
"""
import os
import time
import argparse
from datetime import datetime
import boto3
import paramiko

class SingleInstanceScaling:
    def __init__(self, instance_type, expected_cpu=None, threads=5):
        self.input_video = os.path.join(os.path.dirname(__file__), "..", "video_10_minutos.mp4")
        self.instance_type = instance_type
        self.expected_cpu = expected_cpu
        self.threads = threads
        
        self.codec = "libx264"
        self.bitrate = "2M"
        self.preset = "slow"
        
        self.aws_config = {
            "ami_id": "ami-0300cfb089403fb0b",
            "key_name": "<aws-key-pair-name>",
            "security_groups": ["<aws-security-group-name>"],
            "region": "us-east-1",
            "local_key_path": "./artifact/artifacts2/aws-key.pem",
        }

    def log(self, msg, context=None):
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        context_info = f" [{context}]" if context else ""
        print(f"[{timestamp}]{context_info} {msg}")

    def run(self):
        context = f"{self.instance_type}-Serial"
        ec2 = boto3.client('ec2', region_name=self.aws_config['region'])
        instance_id, ssh_client = None, None
        
        self.log(f"=== Phase 3.2 Serial/Vertical: {self.instance_type} ===")
        self.log(f"Codec: {self.codec}, Threads: {self.threads}, Preset: {self.preset}")
        
        if not os.path.exists(self.input_video):
            self.log(f"ERROR: Input video not found: {self.input_video}", context)
            return
        
        total_start = time.time()
        
        try:
            # --- SETUP PHASE ---
            setup_start = time.time()
            
            self.log("Launching EC2 instance...", context)
            response = ec2.run_instances(
                ImageId=self.aws_config['ami_id'],
                InstanceType=self.instance_type,
                KeyName=self.aws_config['key_name'],
                SecurityGroups=self.aws_config['security_groups'],
                MinCount=1, MaxCount=1
            )
            instance_id = response['Instances'][0]['InstanceId']
            self.log(f"Instance {instance_id} launched. Waiting for running state...", context)
            
            ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
            instance = ec2.describe_instances(InstanceIds=[instance_id])
            public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']
            self.log(f"Instance ready. IP: {public_ip}", context)
            
            time.sleep(30)  # Wait for SSH to be ready
            
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(public_ip, username="ubuntu", key_filename=self.aws_config['local_key_path'])
            self.log("SSH connected.", context)
            
            # CPU check
            self.log("Checking CPU model...", context)
            stdin, stdout, stderr = ssh_client.exec_command("cat /proc/cpuinfo | grep 'model name' | head -1")
            cpu_model = stdout.read().decode().strip().split(": ")[-1]
            self.log(f"CPU found: {cpu_model}", context)
            
            if self.expected_cpu and cpu_model != self.expected_cpu:
                self.log(f"WARNING: CPU mismatch! Expected {self.expected_cpu}, got {cpu_model}.", context)
            
            # Upload video
            self.log("Uploading 10-minute video...", context)
            sftp = ssh_client.open_sftp()
            sftp.put(self.input_video, "/home/ubuntu/input.mp4")
            sftp.close()
            self.log("Upload complete.", context)
            
            setup_end = time.time()
            setup_time = setup_end - setup_start
            self.log(f"SETUP TIME: {setup_time:.2f}s ({setup_time/60:.2f} min)", context)
            
            # --- ENCODING PHASE ---
            encoding_start = time.time()
            
            cmd = (f"ffmpeg -i /home/ubuntu/input.mp4 -c:v {self.codec} -preset {self.preset} "
                   f"-b:v {self.bitrate} -threads {self.threads} /home/ubuntu/output.mp4")
            self.log(f"Running compression: {cmd}", context)
            
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            # Stream stderr for progress (ffmpeg outputs to stderr)
            while True:
                line = stderr.readline()
                if not line:
                    break
                line = line.strip()
                if line and ('time=' in line or 'speed=' in line):
                    self.log(f"  {line}", context)
            
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                self.log(f"ERROR: FFmpeg failed with exit code {exit_status}", context)
                return
            
            encoding_end = time.time()
            encoding_time = encoding_end - encoding_start
            self.log(f"ENCODING TIME: {encoding_time:.2f}s ({encoding_time/60:.2f} min)", context)
            
        except Exception as e:
            self.log(f"ERROR: {str(e)}", context)
            raise
        finally:
            total_end = time.time()
            total_time = total_end - total_start
            
            if ssh_client:
                ssh_client.close()
            if instance_id:
                ec2.terminate_instances(InstanceIds=[instance_id])
                self.log("Instance terminated.", context)
            
            # --- SUMMARY ---
            self.log("=" * 60, context)
            self.log(f"RESULTS SUMMARY - {self.instance_type}", context)
            self.log(f"  Total Time:    {total_time:.2f}s ({total_time/60:.2f} min)", context)
            if 'setup_time' in dir():
                self.log(f"  Setup Time:    {setup_time:.2f}s ({setup_time/60:.2f} min)", context)
            if 'encoding_time' in dir():
                self.log(f"  Encoding Time: {encoding_time:.2f}s ({encoding_time/60:.2f} min)", context)
                self.log(f"  Setup %:       {(setup_time/total_time)*100:.1f}%", context)
            self.log("=" * 60, context)


if __name__ == "__main__":
    import sys
    
    parser = argparse.ArgumentParser(description='Run serial/vertical video compression on a single EC2 instance.')
    parser.add_argument('--instance-type', required=True, help='EC2 Instance Type (e.g., m5.large or m5.4xlarge)')
    parser.add_argument('--expected-cpu', help='Expected CPU Model Name')
    parser.add_argument('--threads', type=int, default=5, help='Number of threads for FFmpeg')
    
    args = parser.parse_args()

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
                
    script_name = os.path.splitext(os.path.basename(__file__))[0]
    log_filename = f"{script_name}_{args.instance_type}.log"
    
    with open(log_filename, "w") as logfile:
        tee = Tee(sys.__stdout__, logfile)
        sys.stdout = sys.stderr = tee
        try:
            SingleInstanceScaling(
                instance_type=args.instance_type,
                expected_cpu=args.expected_cpu,
                threads=args.threads
            ).run()
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
