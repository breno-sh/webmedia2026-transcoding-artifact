import os
import time
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import boto3
import paramiko

class ParallelCompressionGeneric:
    def __init__(self, instance_type, expected_cpu=None, threads=5):
        self.input_video = os.path.join(os.path.dirname(__file__), "..", "video_10_minutos.mp4")
        self.instance_type = instance_type
        self.expected_cpu = expected_cpu
        self.threads = threads
        
        # Directory names based on instance type to avoid collisions
        self.parts_dir = f"video_parts_{self.instance_type}"
        self.compressed_dir = f"compressed_parts_{self.instance_type}"
        
        self.num_parts = 10
        self.max_total_vcpus = 10  # User constraint
        # Determine vCPUs for this instance type
        self.instance_vcpus = self._get_instance_vcpus(instance_type)
        
        # Calculate max workers (instances) to stay within vCPU limit
        if self.instance_vcpus > self.max_total_vcpus:
             self.log(f"WARNING: Instance {instance_type} has {self.instance_vcpus} vCPUs, which exceeds the limit of {self.max_total_vcpus}. Testing might fail or require limit increase.", "Setup")
             self.max_workers = 1
        else:
             self.max_workers = max(1, self.max_total_vcpus // self.instance_vcpus)
        
        self.log(f"Concurrency Limit: Max {self.max_workers} instances of {instance_type} ({self.instance_vcpus} vCPUs each) to respect {self.max_total_vcpus} vCPU total limit.", "Setup")

        self.codec = "libx264"
        self.bitrate = "2M"
        self.preset = "slow"
        
        self.aws_config = {
            "ami_id": "ami-0300cfb089403fb0b",
            "key_name": "<aws-key-pair-name>",  # Replace with your AWS key pair name
            "security_groups": ["<aws-security-group-name>"],  # Using Security Group Name
            "region": "us-east-1",
            "local_key_path": "./artifact/artifacts2/aws-key.pem",  # Replace with path to your .pem key file
            "instance_type": self.instance_type
        }
        self._create_directories()

    def _create_directories(self):
        os.makedirs(self.parts_dir, exist_ok=True)
        os.makedirs(self.compressed_dir, exist_ok=True)

    def _get_instance_vcpus(self, instance_type):
        # Known vCPU counts for families in this study
        # T-family
        if instance_type in ["t2.micro", "t3.micro"]: return 2
        if instance_type in ["t3.small", "t3.medium", "t3.large"]: return 2
        if instance_type == "t3.xlarge": return 4
        if instance_type == "t3.2xlarge": return 8
        # C-family
        if instance_type == "c5.large": return 2
        if instance_type == "c5.xlarge": return 4
        if instance_type == "c5.2xlarge": return 8
        if instance_type == "c5.4xlarge": return 16
        # M-family
        if instance_type == "m5.large": return 2
        if instance_type == "m5.xlarge": return 4
        if instance_type == "m5.2xlarge": return 8
        if instance_type == "m5.4xlarge": return 16
        return 2 # Default fallback safe assumption

    def log(self, msg, context=None):
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        context_info = f" [{context}]" if context else ""
        print(f"[{timestamp}]{context_info} {msg}")

    def split_video(self):
        self.log(f"Starting video split for {self.instance_type}...", "Setup")
        if not os.path.exists(self.input_video):
            self.log(f"Error: Input video {self.input_video} not found!", "Setup")
            return

        duration_cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {self.input_video}"
        try:
            duration = float(os.popen(duration_cmd).read())
        except ValueError:
            self.log("Error reading video duration. Check ffprobe/input file.", "Setup")
            return

        part_duration = duration / self.num_parts
        for i in range(self.num_parts):
            output_file = f"{self.parts_dir}/part_{i:02d}.mp4"
            os.system(f"ffmpeg -y -i {self.input_video} -ss {i * part_duration} -t {part_duration} -c copy {output_file} > /dev/null 2>&1")
        self.log("Divisão concluída.", "Setup")

    def process_part(self, part_index):
        context = f"Part {part_index:02d}"
        ec2 = boto3.client('ec2', region_name=self.aws_config['region'])
        instance_id, ssh_client = None, None
        try:
            self.log(f"Launching {self.instance_type}...", context)
            response = ec2.run_instances(
                ImageId=self.aws_config['ami_id'], InstanceType=self.aws_config['instance_type'],
                KeyName=self.aws_config['key_name'], SecurityGroups=self.aws_config['security_groups'],
                MinCount=1, MaxCount=1
            )
            instance_id = response['Instances'][0]['InstanceId']
            ec2.get_waiter('instance_running').wait(InstanceIds=[instance_id])
            instance = ec2.describe_instances(InstanceIds=[instance_id])
            public_ip = instance['Reservations'][0]['Instances'][0]['PublicIpAddress']
            self.log(f"Instance ready. IP: {public_ip}", context)
            time.sleep(30)
            
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(public_ip, username="ubuntu", key_filename=self.aws_config['local_key_path'])
            
            self.log("Checking CPU model...", context)
            stdin, stdout, stderr = ssh_client.exec_command("cat /proc/cpuinfo | grep 'model name' | head -1")
            cpu_model = stdout.read().decode().strip().split(": ")[-1]
            self.log(f"CPU found: {cpu_model}", context)
            
            if self.expected_cpu and cpu_model != self.expected_cpu:
                 self.log(f"WARNING: CPU mismatch! Expected {self.expected_cpu}, got {cpu_model}.", context)
            
            sftp = ssh_client.open_sftp()
            try:
                part_file_path = f"{self.parts_dir}/part_{part_index:02d}.mp4"
                remote_input_path = "/home/ubuntu/input.mp4"
                remote_output_path = "/home/ubuntu/output.mp4"
                local_output_path = f"{self.compressed_dir}/part_{part_index:02d}_compressed.mp4"
                
                self.log("Sending file...", context)
                sftp.put(part_file_path, remote_input_path)
                cmd = (f"ffmpeg -i {remote_input_path} -c:v {self.codec} -preset {self.preset} "
                       f"-b:v {self.bitrate} -threads {self.threads} {remote_output_path}")
                self.log("Running compression...", context)
                stdin, stdout, stderr = ssh_client.exec_command(cmd)
                if stdout.channel.recv_exit_status() != 0: 
                    raise RuntimeError(f"FFmpeg falhou: {stderr.read().decode()}")
                self.log("Downloading compressed file...", context)
                sftp.get(remote_output_path, local_output_path)
            finally:
                sftp.close()
        except Exception as e:
            self.log(f"ERROR: {str(e)}", context)
            raise
        finally:
            if ssh_client: ssh_client.close()
            if instance_id:
                ec2.terminate_instances(InstanceIds=[instance_id])
                self.log("Instance terminated.", context)

    def run(self):
        self.split_video()
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            executor.map(self.process_part, range(self.num_parts))
        self.log(f"🎉 Processing Complete for {self.instance_type}!")

if __name__ == "__main__":
    import sys
    
    parser = argparse.ArgumentParser(description='Run parallel video compression on EC2.')
    parser.add_argument('--instance-type', required=True, help='EC2 Instance Type (e.g., c5.large)')
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
            ParallelCompressionGeneric(
                instance_type=args.instance_type,
                expected_cpu=args.expected_cpu,
                threads=args.threads
            ).run()
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
