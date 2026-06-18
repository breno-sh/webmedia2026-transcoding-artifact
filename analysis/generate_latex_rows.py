
import pandas as pd
import os
import numpy as np

base_dir = "./"
data_dir = os.path.join(base_dir, "artifacts2/experimental_data/")

prices = {
    "m5.large": 0.096,
    "m5.xlarge": 0.192,
    "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768,
    "c5.large": 0.085,
    "c5.xlarge": 0.170,
    "c5.2xlarge": 0.340,
    "c5.4xlarge": 0.680
}

instances = ["m5.large", "m5.xlarge", "m5.2xlarge", "m5.4xlarge", "c5.large", "c5.xlarge", "c5.2xlarge", "c5.4xlarge"]
codecs = ["h264", "h265", "vp9"]
threads = [1, 3, 5, 10]

def format_num(val):
    if val >= 10:
        return f"{val:.2f}"
    else:
        return f"{val:.4f}"

def format_cost(val):
    return f"{val:.7f}"

def format_eff(val):
    return f"{int(val):,}"

for inst in instances:
    csv_path = os.path.join(data_dir, f"aggregated_{inst.replace('.', '_')}.csv")
    if not os.path.exists(csv_path):
        print(f"Skipping {inst}")
        continue
    
    df = pd.read_csv(csv_path)
    price_per_sec = prices[inst] / 3600.0
    
    for t in threads:
        line = [f"{inst} & {t} thread"]
        for codec in codecs:
            col = f"{codec} {t} thread"
            if col in df.columns:
                data = df[col].dropna().values
                median = np.median(data)
                std = np.std(data, ddof=1)
                vmin = np.min(data)
                vmax = np.max(data)
                
                cost = median * price_per_sec
                eff = 1.0 / cost if cost > 0 else 0
                
                # Table format: Median & Std & Min & Max & Eff | Cost
                line.append(f"& {format_num(median)} & {format_num(std)} & {format_num(vmin)} & {format_num(vmax)} & {format_eff(eff)} | {format_cost(cost)}")
            else:
                line.append("& - & - & - & - & - | -")
        
        print(" ".join(line) + " \\\\")
