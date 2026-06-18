import pandas as pd
import numpy as np
import scipy.stats as stats

def calc_stats(t1, t2, name):
    # filter out nans just in case
    t1 = t1[~np.isnan(t1)]
    t2 = t2[~np.isnan(t2)]
    
    print(f"\n--- {name} ---")
    m1, m2 = np.mean(t1), np.mean(t2)
    s1, s2 = np.std(t1, ddof=1), np.std(t2, ddof=1)
    
    print(f"Dist 1: Mean={m1:.4f}, Median={np.median(t1):.4f}, Std={s1:.4f}")
    print(f"Dist 2: Mean={m2:.4f}, Median={np.median(t2):.4f}, Std={s2:.4f}")
    
    # Welch
    stat_t, p_t = stats.ttest_ind(t1, t2, equal_var=False)
    print(f"Welch's t-test: p = {p_t:.4e}")
    
    # Cohen's d
    n1, n2 = len(t1), len(t2)
    v1, v2 = np.var(t1, ddof=1), np.var(t2, ddof=1)
    pooled_sd = np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    d = (m1 - m2) / pooled_sd
    print(f"Cohen's d: {abs(d):.4f}")
    
    speedup = max(m1, m2) / min(m1, m2)
    diff_percent = (max(m1, m2) - min(m1, m2)) / min(m1, m2) * 100
    faster_pct = (max(m1, m2) - min(m1, m2)) / max(m1, m2) * 100 
    print(f"Speedup multiplier: {speedup:.4f}x")
    print(f"Relative difference (ref=min): {diff_percent:.2f}% slower")
    print(f"Relative difference (ref=max): {faster_pct:.2f}% faster")

base_dir = "./"

# 1. c5.large vs m5.large (10 threads, H.264)
try:
    df_m = pd.read_csv(base_dir + "artifacts2/experimental_data/aggregated_m5_large.csv")
    df_c = pd.read_csv(base_dir + "artifacts2/experimental_data/aggregated_c5_large.csv")
    
    m_data = df_m['h264 10 thread'].values
    c_data = df_c['h264 10 thread'].values
    calc_stats(m_data, c_data, "P2: c5.large (2) vs m5.large (1) (10 threads, H.264)")
except Exception as e:
    print("Error 1:", e)

# 2. t3.micro vs c5.large (1 thread, H.264)
try:
    df_t = pd.read_csv(base_dir + "artifacts/experimental_data/aggregated_t3_micro.csv")
    
    t_data = df_t['h264 1 thread'].values
    c_data_1 = df_c['h264 1 thread'].values
    calc_stats(t_data, c_data_1, "P2: t3.micro (1) vs c5.large (2) (1 thread, H.264)")
except Exception as e:
    print("Error 2:", e)
