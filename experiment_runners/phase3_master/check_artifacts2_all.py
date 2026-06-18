import re
import glob

def parse_logs(pattern):
    times = []
    for f in glob.glob(pattern):
        run_match = re.search(r'run_(\d+)\.log', f)
        if not run_match: continue
        run_num = int(run_match.group(1))
        
        with open(f, 'r') as file:
            c = file.read()
            tot = re.search(r'Total Execution Time:\s*([\d\.]+)', c)
            if not tot:
                 tot = re.search(r'Total Time:\s*([\d\.]+)', c)
            if tot:
                times.append((run_num, float(tot.group(1))))
    times.sort(key=lambda x: x[0])
    return times

t = parse_logs('./artifacts2/phase3_scaling/n30_logs/t3_micro_phase2_run_*.log')
print("Extracted", len(t), "times.")
for run, time in t:
    print(f"Run {run:<2}: {time:6.2f} s ({time/60:4.2f} min)")
