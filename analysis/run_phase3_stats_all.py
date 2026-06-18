import os
import glob
import re
import numpy as np
import scipy.stats as stats

def get_times_from_logs(pattern):
    times = []
    files = glob.glob(pattern)
    for file in files:
        try:
            with open(file, 'r') as f:
                content = f.read()
                match = re.search(r'(?i)total (?:execute\s*)?time:\s*([\d.]+)', content)
                if match:
                    times.append(float(match.group(1)))
        except:
            continue
    return np.array(times)

def analyze(name, t1, t2):
    if len(t1) == 0 or len(t2) == 0:
        print(f"Skipping {name} (N1={len(t1)}, N2={len(t2)})")
        return
        
    print(f"\n--- {name} ---")
    print(f"Hori: N={len(t1)}, Mean={np.mean(t1):.4f}, Std={np.std(t1, ddof=1):.4f} (seconds)")
    print(f"Vert: N={len(t2)}, Mean={np.mean(t2):.4f}, Std={np.std(t2, ddof=1):.4f} (seconds)")
    
    _, p_shapiro1 = stats.shapiro(t1)
    _, p_shapiro2 = stats.shapiro(t2)
    print(f"Shapiro-Wilk Hori: p = {p_shapiro1:.4e} ({'Normal' if p_shapiro1 > 0.05 else 'Not Normal'})")
    print(f"Shapiro-Wilk Vert: p = {p_shapiro2:.4e} ({'Normal' if p_shapiro2 > 0.05 else 'Not Normal'})")
    
    stat_levene, p_levene = stats.levene(t1, t2)
    print(f"Levene Test: p = {p_levene:.4e} ({'Equal Variances' if p_levene > 0.05 else 'Unequal Variances'})")
    
    stat_t, p_t = stats.ttest_ind(t1, t2, equal_var=False)
    print(f"Welch's t-test: p = {p_t:.4e}")
    
    m1, m2 = np.mean(t1), np.mean(t2)
    n1, n2 = len(t1), len(t2)
    v1, v2 = np.var(t1, ddof=1), np.var(t2, ddof=1)
    pooled_sd = np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    d = (m1 - m2) / pooled_sd
    print(f"Cohen's d: {abs(d):.4f}")

base = "./phase3_scaling/n30_logs/"

# M-Family
m_h = get_times_from_logs(base + "m5_large_horizontal_opt_run_*.log")
m_v = get_times_from_logs(base + "m5_4xlarge_vertical_opt_run_*.log")
analyze("M-Family Phase 3", m_h, m_v)

# C-Family
c_h = get_times_from_logs(base + "c5_large_horizontal_opt_run_*.log")
c_v = get_times_from_logs(base + "c5_4xlarge_vertical_opt_run_*.log")
analyze("C-Family Phase 3", c_h, c_v)

# T-Family
t_h = get_times_from_logs(base + "t3_micro_paralelo_phase2_run_*.log")
t_v = get_times_from_logs(base + "t3_2xlarge_phase2_run_*.log")
analyze("T-Family Phase 3", t_h, t_v)

