import os
import pandas as pd
from pathlib import Path
import re

def parse_16t_logs():
    instances = ["c5.4xlarge", "m5.4xlarge"]
    codecs = ["h264", "h265", "vp9"]
    target_threads = 16
    log_dir = Path("logs_16t")
    data_dir = Path("artifacts2/experimental_data")

    for instance in instances:
        csv_file = data_dir / f"aggregated_{instance.replace('.', '_')}.csv"
        if not csv_file.exists():
            print(f"Skipping {instance}, no aggregated CSV found.")
            continue
            
        df = pd.read_csv(csv_file)
        
        for codec in codecs:
            log_file = log_dir / f"compression_{instance}_{codec}_{target_threads}thread.log"
            new_col_name = f"{codec} {target_threads} thread"
            
            if not log_file.exists():
                print(f"File not found: {log_file}")
                # For safety, insert NaNs if missing
                if new_col_name not in df.columns:
                    df[new_col_name] = [float('nan')] * len(df)
                continue
                
            with open(log_file, "r") as f:
                content = f.read()
                
            times = re.findall(rf"Compression \d+ \({target_threads} threads\): ([\d\.]+) seconds", content)
            times = [float(t) for t in times][:30]  # Take up to 30
            
            if len(times) == 30:
                df[new_col_name] = times
                print(f"Successfully processed {instance} {codec} {target_threads}t")
            else:
                print(f"Warning: Found {len(times)} times for {instance} {codec} {target_threads}t. Expected 30.")
                
        # Reorder columns logically (group by codec, sort by thread)
        cols = list(df.columns)
        def sort_key(col):
            parts = col.split()
            codec_k = {'h264': 0, 'h265': 1, 'vp9': 2}.get(parts[0], 99)
            thread_k = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 99
            return (codec_k, thread_k)
            
        cols.sort(key=sort_key)
        df = df[cols]
        df.to_csv(csv_file, index=False)
        print(f"Saved updated CSV for {instance}")

if __name__ == "__main__":
    parse_16t_logs()
