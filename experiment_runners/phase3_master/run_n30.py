import os
import subprocess
import time
import threading
from datetime import datetime
import concurrent.futures

# Define the scripts to run alongside their required vCPU limits
# format: (directory, script_name, vcpu_cost)
# c5.4xlarge/m5.4xlarge = 16 vCPUs
# c5.large/m5.large/t3.micro = 2 vCPUs
# t3.2xlarge = 8 vCPUs
# Horizontal scripts usually spawn MAX_WORKERS times the instance vCPU.
base_dir2 = "./artifacts2/phase3_scaling"
base_dir = "./artifacts/phase3_scaling"

SCRIPTS = [
    # M Family OPT scripts (16 vs 2 vCPUs)
    (base_dir2, "m5_4xlarge_vertical_opt.py", 16),
    (base_dir2, "m5_large_horizontal_opt.py", 20),
    (base_dir2, "m5_large_serial_opt.py", 2),
    
    # C Family OPT scripts (16 vs 2 vCPUs)
    (base_dir2, "c5_4xlarge_vertical_opt.py", 16),
    (base_dir2, "c5_large_horizontal_opt.py", 20),
    (base_dir2, "c5_large_serial_opt.py", 2),
]

N_RUNS = 45 # We run 45 times to guarantee at least 30 100% pristine runs from scratch
MAX_VCPUS = 32

active_vcpus = 0
vcpus_lock = threading.Condition()

def log(msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {msg}")

def run_script(script_dir, script_name, iteration, vcpu_cost):
    global active_vcpus
    
    # Wait until there are enough vCPUs available
    with vcpus_lock:
        while active_vcpus + vcpu_cost > MAX_VCPUS:
            vcpus_lock.wait()
        active_vcpus += vcpu_cost
        log(f"Acquired {vcpu_cost} vCPUs for {script_name}. Active vCPUs: {active_vcpus}/{MAX_VCPUS}")
        
    try:
        script_path = os.path.join(script_dir, script_name)
        log(f"Running {script_name} from {script_dir} - Iteration {iteration+1}/{N_RUNS}")
        
        result = subprocess.run(
            ["python3", script_path],
            cwd=script_dir,
            capture_output=True,
            text=True
        )
        
        log_dir = os.path.join(script_dir, "n30_logs")
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, f"{script_name.replace('.py', '')}_run_{iteration+1}.log")
        with open(log_file, "w") as f:
            f.write(result.stdout)
            if result.stderr:
                f.write("\n--- STDERR ---\n")
                f.write(result.stderr)
                
        if result.returncode != 0:
            log(f"ERROR running {script_name} on iteration {iteration+1}. See {log_file}")
        else:
            log(f"Successfully completed {script_name} - Iteration {iteration+1}")
            
    finally:
        # Release the vCPUs back to the pool
        with vcpus_lock:
            active_vcpus -= vcpu_cost
            log(f"Released {vcpu_cost} vCPUs from {script_name}. Active vCPUs: {active_vcpus}/{MAX_VCPUS}")
            vcpus_lock.notify_all()

if __name__ == "__main__":
    tasks = []
    # Build a flat list of all tasks we need to run: 15 scripts * 45 runs = 675 tasks
    for iteration in range(N_RUNS):
        for s_dir, s_name, v_cost in SCRIPTS:
            tasks.append((s_dir, s_name, iteration, v_cost))
            
    # Execute everything using a thread pool. The ThreadPool can be large, 
    # the actual concurrency limit is enforced by the vCPU Condition Lock.
    log(f"Submitting {len(tasks)} tasks to thread pool with {MAX_VCPUS} vCPU constraint.")
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(run_script, d, s, i, v) for (d, s, i, v) in tasks]
        
        # Wait for all futures to resolve
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                log(f"Task generated an exception: {e}")

    log("ALL 45 ITERATIONS OF PHASE 3 COMPLETED.")
