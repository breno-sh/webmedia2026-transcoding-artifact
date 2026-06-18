import glob
import re
from datetime import datetime
import os

def parse_time(log_line):
    # Extracts datetime from "[14:06:18.765]"
    m = re.search(r"\[([\d:]+\.\d+)\]", log_line)
    if m:
        try:
            return datetime.strptime(m.group(1), "%H:%M:%S.%f")
        except:
            return None
    return None

def analyze_parallel_logs(prefix, arch_name):
    logs = glob.glob(f"artifacts2/phase3_scaling/n30_logs/{prefix}_run_*.log")
    if not logs:
        # Also check phase3_scaling dir for phase 3.1
        logs = glob.glob(f"artifacts/phase3_scaling/n30_logs/{prefix}_run_*.log")
        
    if not logs:
        print(f"No logs found for {prefix}")
        return
        
    total_time_sum = 0
    setup_time_sum = 0
    enc_time_sum = 0
    count = 0
    
    for log in logs[:30]: # use exactly 30 runs as per paper
        with open(log, 'r') as f:
            lines = f.readlines()
            
        start_time = parse_time(lines[0])
        end_time = None
        
        # Determine total time based on RESULTS block if available, or just last line
        total_time = None
        for line in reversed(lines):
            if "Total Time" in line:
                m = re.search(r"Total Time:\s+([\d\.]+)s", line)
                if m:
                    total_time = float(m.group(1))
                    break
        
        if total_time is None:
            # try to compute from timestamps
            for line in reversed(lines):
                t = parse_time(line)
                if t:
                    end_time = t
                    break
            if end_time and start_time:
                total_time = (end_time - start_time).total_seconds()
                
        if total_time is None:
            continue
            
        # To find effective encoding time: 
        # For each part, track 'Running compression' and 'Done!'
        part_starts = {}
        part_ends = {}
        
        for line in lines:
            m_part = re.search(r"\[Part (\d+)\]", line)
            if not m_part: continue
            part = int(m_part.group(1))
            
            t = parse_time(line)
            if not t: continue
            
            if "Running compression" in line or "Starting FFmpeg" in line or "ffmpeg -i" in line or "compression..." in line:
                if part not in part_starts:
                    part_starts[part] = t
            if "Done!" in line or "Compression completed" in line or "Download do arquivo" in line or "Downloading" in line:
                if part not in part_ends:
                    part_ends[part] = t
                    
        # Calculate bottleneck encoding time
        max_enc = 0
        for p in part_starts:
            if p in part_ends:
                diff = (part_ends[p] - part_starts[p]).total_seconds()
                if diff > max_enc:
                    max_enc = diff
                    
        if max_enc > 0:
            enc_time_sum += max_enc
            setup_time_sum += (total_time - max_enc)
            total_time_sum += total_time
            count += 1
            
    if count > 0:
        print(f"{arch_name} ({count} runs):")
        print(f"  Total: {total_time_sum/count/60:.2f} min")
        print(f"  Setup: {setup_time_sum/count/60:.2f} min ({(setup_time_sum/total_time_sum)*100:.1f}%)")
        print(f"  Enc:   {enc_time_sum/count/60:.2f} min")
        print("-" * 40)

print("--- Phase 3.2 ---")
analyze_parallel_logs("m5_large_horizontal_opt", "10x m5.large Phase 3.2")
analyze_parallel_logs("c5_large_horizontal_opt", "10x c5.large Phase 3.2")
analyze_parallel_logs("t3_micro_paralelo_phase2", "10x t3.micro Phase 3.2 (N=30)")

print("--- Phase 3.1 ---")
analyze_parallel_logs("m5_large_horizontal", "10x m5.large Phase 3.1")
analyze_parallel_logs("c5_large_horizontal", "10x c5.large Phase 3.1")
# t3 micro phase 3.1 is hard to parse because of its log format, but we can try
analyze_parallel_logs("t3_micro_horizontal", "10x t3.micro Phase 3.1")
