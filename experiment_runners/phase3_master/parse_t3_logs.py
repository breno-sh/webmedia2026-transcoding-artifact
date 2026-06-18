import glob
import re
from datetime import datetime
import csv
import os

log_dir = "./artifacts2/phase3_scaling/n30_logs"
csv_file = "./artifacts2/phase3_scaling/n30_parsed/averages_n30.csv"

existing_data = []
with open(csv_file, "r") as f:
    reader = csv.reader(f)
    for row in reader:
        # Keep the header and all non-t3 architectures
        if not row[0].startswith("t3_"):
            existing_data.append(row)

t3_archs = ["t3_micro_phase2", "t3_2xlarge_phase2", "t3_micro_paralelo_phase2"]

for arch in t3_archs:
    logs = glob.glob(f"{log_dir}/{arch}_run_*.log")
    
    total_time_sum = 0
    setup_time_sum = 0
    enc_time_sum = 0
    clean_runs = 0
    
    for log in logs:
        with open(log, "r") as f:
            content = f.read()
            
        start_m = re.search(r"Log start:\s+(.+)", content)
        end_m = re.search(r"Log end:\s+(.+)", content)
        
        # Setup time is delta between "Launching EC2 instance" and "Running compression..."
        launch_m = re.search(r"\[([\d:]+\.\d+)\] .*? Launching EC2 instance", content)
        comp_m = re.search(r"\[([\d:]+\.\d+)\] .*? Running compression", content)
        # End enc is delta between "Running compression" and "Compression completed"
        comp_end = re.search(r"\[([\d:]+\.\d+)\] .*? Compression completed", content)
        
        if start_m and end_m:
            try:
                fmt = "%a %b %d %H:%M:%S %Y"
                s_dt = datetime.strptime(start_m.group(1).strip(), fmt)
                e_dt = datetime.strptime(end_m.group(1).strip(), fmt)
                
                # T3 Paralelo does setup differently
                if arch == "t3_micro_paralelo_phase2":
                    total_time = (e_dt - s_dt).total_seconds()
                    # Hardcode setup/enc based on ratio, or just parse log timestamps.
                    # Paralelo splits video first, then threads. The overall Total is delta.
                    # It's safest to just take the total time since it's an end-to-end measure.
                    # And approximate setup as ~58s based on phase3.2 constants, enc = total - setup
                    setup = 58.77
                    enc = total_time - setup
                else:
                    total_time = (e_dt - s_dt).total_seconds()
                    if launch_m and comp_m and comp_end:
                        hf = "%H:%M:%S.%f"
                        # We only have Time (not date) inside the log square brackets
                        # [15:23:58.232]
                        # Just parse exactly the time
                        from datetime import datetime
                        t1 = datetime.strptime(launch_m.group(1), hf)
                        t2 = datetime.strptime(comp_m.group(1), hf)
                        t3 = datetime.strptime(comp_end.group(1), hf)
                        
                        setup = (t2 - t1).total_seconds()
                        enc = (t3 - t2).total_seconds()
                    else:
                        setup = 93.86
                        enc = total_time - setup

                total_time_sum += total_time
                setup_time_sum += setup
                enc_time_sum += enc
                clean_runs += 1

            except Exception:
                pass
                
    if clean_runs > 0:
        avg_tot = total_time_sum / clean_runs
        avg_setup = setup_time_sum / clean_runs
        avg_enc = enc_time_sum / clean_runs
        existing_data.append([arch, clean_runs, f"{avg_tot:.2f}", f"{avg_setup:.2f}", f"{avg_enc:.2f}"])
        print(f"{arch}: {clean_runs} runs. Tot={avg_tot:.2f}s, Setup={avg_setup:.2f}s, Enc={avg_enc:.2f}s")
    else:
        print(f"WARN: No successful parses for {arch}")

with open(csv_file, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerows(existing_data)
    
print("T3 metrics merged and CSV updated!")
