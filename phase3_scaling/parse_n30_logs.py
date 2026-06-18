import os
import glob
import re
import csv
from collections import defaultdict

# The two base directories where logs are stored
dirs = [
    "./phase3_scaling/n30_logs",
    "./phase3_scaling/n30_logs"
]

# We need exactly 30 clean runs for each architecture.
REQUIRED_RUNS = 30

# Store results as {architecture_name: [{"total": float, "setup": float, "encoding": float}]}
clean_results = defaultdict(list)
warnings_count = defaultdict(int)

# Regex patterns to extract data
total_re = re.compile(r"Total Time:\s+([\d\.]+)s")
setup_re = re.compile(r"Setup Time:\s+([\d\.]+)s")
split_re = re.compile(r"Split Time:\s+([\d\.]+)s")
encoding_re = re.compile(r"Encoding Time:\s+([\d\.]+)s")
parallel_re = re.compile(r"Parallel Time:\s+([\d\.]+)s")

for d in dirs:
    if not os.path.exists(d):
        continue
        
    for log_path in glob.glob(os.path.join(d, "*.log")):
        filename = os.path.basename(log_path)
        # Architecture name is filename minus "_run_X.log"
        arch_match = re.search(r"(.+)_run_\d+\.log", filename)
        if not arch_match:
            continue
            
        arch_name = arch_match.group(1)
        
        with open(log_path, "r") as f:
            content = f.read()
            
        # Option A: We accept any CPU model provisioned by AWS, so we count warnings but do not discard.
        if "WARNING: CPU mismatch" in content:
            warnings_count[arch_name] += 1
            # We DONT discard this run. Option A allows hardware heterogenity for statistical volume.
        # Check if the file is incomplete (no RESULTS block)
        if "RESULTS" not in content:
            print(f"File {filename} is missing RESULTS block.")
            continue
            
        # Extract metrics
        total_time = None
        setup_time = None
        encoding_time = None
        
        m_total = total_re.search(content)
        if m_total:
            total_time = float(m_total.group(1))
            
        # Serial setups have Setup / Encoding. Horizontal has Split / Parallel.
        m_setup = setup_re.search(content)
        if m_setup:
            setup_time = float(m_setup.group(1))
        else:
            m_split = split_re.search(content)
            if m_split:
                setup_time = float(m_split.group(1))
                
        m_enc = encoding_re.search(content)
        if m_enc:
            encoding_time = float(m_enc.group(1))
        else:
            m_par = parallel_re.search(content)
            if m_par:
                encoding_time = float(m_par.group(1))
                
        if total_time is not None:
            clean_results[arch_name].append({
                "run_file": filename,
                "total": total_time,
                "setup": setup_time or 0.0,
                "encoding": encoding_time or 0.0
            })

# Ensure we have at least 30 clean runs and compute averages
print(f"{'Architecture':<30} | {'Clean Runs':<10} | {'Warnings':<10} | {'Avg Total (s)':<15} | {'Avg Setup (s)':<15} | {'Avg Enc (s)':<15}")
print("-" * 110)

final_averages = {}

# We write a new aggregated CSV to inject into the paper
os.makedirs("./phase3_scaling/n30_parsed", exist_ok=True)
csv_file = "./phase3_scaling/n30_parsed/averages_n30.csv"

with open(csv_file, "w", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["Architecture", "CleanRunsCount", "AvgTotalTime", "AvgSetupTime", "AvgEncodingTime"])
    
    for arch, runs in clean_results.items():
        if len(runs) < REQUIRED_RUNS:
            print(f"CRITICAL ERROR: {arch} only has {len(runs)} clean runs (needed {REQUIRED_RUNS})")
            continue
            
        # Select exactly the first 30 clean runs
        selected = runs[:REQUIRED_RUNS]
        
        avg_tot = sum(r["total"] for r in selected) / REQUIRED_RUNS
        avg_set = sum(r["setup"] for r in selected) / REQUIRED_RUNS
        avg_enc = sum(r["encoding"] for r in selected) / REQUIRED_RUNS
        
        writer.writerow([arch, REQUIRED_RUNS, f"{avg_tot:.2f}", f"{avg_set:.2f}", f"{avg_enc:.2f}"])
        
        print(f"{arch:<30} | {len(selected):<10} | {warnings_count[arch]:<10} | {avg_tot:<15.2f} | {avg_set:<15.2f} | {avg_enc:<15.2f}")
        final_averages[arch] = (avg_tot, avg_set, avg_enc)

print(f"\nFinal averages written to: {csv_file}")
