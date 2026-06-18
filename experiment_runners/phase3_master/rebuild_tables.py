import csv

csv_file = "./artifacts2/phase3_scaling/n30_parsed/averages_n30.csv"
data = {}
with open(csv_file, "r") as f:
    reader = csv.reader(f)
    next(reader)
    for row in reader:
        arch = row[0]
        data[arch] = {
            "total_sec": float(row[2]),
            "setup_sec": float(row[3]),
            "enc_sec": float(row[4])
        }

# Phase 3.1 values (unoptimized, grabbed from existing latex tables for accuracy cross-validation)
p31_data = {
    "t3_micro_serial": {"total": 4.03, "setup": 2.26, "enc": 1.77, "cost_hr": 0.0104, "n_instances": 1},
    "t3_micro_par": {"total": 3.28, "setup": 2.30, "enc": 0.97, "cost_hr": 0.0104, "n_instances": 10},
    "t3_2xlarge_vert": {"total": 3.04, "setup": 2.31, "enc": 0.73, "cost_hr": 0.3328, "n_instances": 1},
    
    "m5_large_serial": {"total": 3.46, "setup": 1.56, "enc": 1.90, "cost_hr": 0.0039}, # WAit, the old table used 0.0039 because of the typo! We should use 0.096!
    # If the old table used 0.0039, I must recalculate ALL costs for M and C using the real AWS pricing!
}

# The REAL AWS PRICING
pricing = {
    "t3.micro": 0.0104,
    "t3.2xlarge": 0.3328,
    "m5.large": 0.0960,
    "m5.4xlarge": 0.7680,
    "c5.large": 0.0850,
    "c5.4xlarge": 0.6800
}

# Values for Phase 3.1 (from previous table data, but time only, we will recalculate costs)
time_p31 = {
    "t": {"ser": [4.03, 2.26, 1.77], "par": [3.28, 2.30, 0.97], "ver": [3.04, 2.31, 0.73]},
    "m": {"ser": [3.46, 1.56, 1.90], "par": [3.63, 2.50, 1.13], "ver": [2.33, 1.74, 0.59]},
    "c": {"ser": [3.21, 1.55, 1.66], "par": [3.52, 2.50, 1.02], "ver": [2.13, 1.54, 0.59]}
}

# Load Phase 3.2 Time (convert from sec to min)
time_p32 = {
    "t": {
        "ser": [data["t3_micro_phase2"]["total_sec"]/60, data["t3_micro_phase2"]["setup_sec"]/60, data["t3_micro_phase2"]["enc_sec"]/60],
        "par": [data["t3_micro_paralelo_phase2"]["total_sec"]/60, data["t3_micro_paralelo_phase2"]["setup_sec"]/60, data["t3_micro_paralelo_phase2"]["enc_sec"]/60],
        "ver": [data["t3_2xlarge_phase2"]["total_sec"]/60, data["t3_2xlarge_phase2"]["setup_sec"]/60, data["t3_2xlarge_phase2"]["enc_sec"]/60]
    },
    "m": {
        "ser": [data["m5_large_serial_opt"]["total_sec"]/60, data["m5_large_serial_opt"]["setup_sec"]/60, data["m5_large_serial_opt"]["enc_sec"]/60],
        "par": [data["m5_large_horizontal_opt"]["total_sec"]/60, data["m5_large_horizontal_opt"]["setup_sec"]/60, data["m5_large_horizontal_opt"]["enc_sec"]/60],
        "ver": [data["m5_4xlarge_vertical_opt"]["total_sec"]/60, data["m5_4xlarge_vertical_opt"]["setup_sec"]/60, data["m5_4xlarge_vertical_opt"]["enc_sec"]/60]
    },
    "c": {
        "ser": [data["c5_large_serial_opt"]["total_sec"]/60, data["c5_large_serial_opt"]["setup_sec"]/60, data["c5_large_serial_opt"]["enc_sec"]/60],
        "par": [data["c5_large_horizontal_opt"]["total_sec"]/60, data["c5_large_horizontal_opt"]["setup_sec"]/60, data["c5_large_horizontal_opt"]["enc_sec"]/60],
        "ver": [data["c5_4xlarge_vertical_opt"]["total_sec"]/60, data["c5_4xlarge_vertical_opt"]["setup_sec"]/60, data["c5_4xlarge_vertical_opt"]["enc_sec"]/60]
    }
}

cost_mult = {
    "t": {"ser": 1 * pricing["t3.micro"] / 60, "par": 10 * pricing["t3.micro"] / 60, "ver": 1 * pricing["t3.2xlarge"] / 60},
    "m": {"ser": 1 * pricing["m5.large"] / 60, "par": 10 * pricing["m5.large"] / 60, "ver": 1 * pricing["m5.4xlarge"] / 60},
    "c": {"ser": 1 * pricing["c5.large"] / 60, "par": 10 * pricing["c5.large"] / 60, "ver": 1 * pricing["c5.4xlarge"] / 60}
}

for fam_key, fam_name in [("t", "Burstable (T)"), ("m", "General Purpose (M)"), ("c", "Compute Optimized (C)")]:
    print(f"\n================ {fam_name} ==================")
    for setup in ["ser", "par", "ver"]:
        t31_tot, t31_set, t31_enc = time_p31[fam_key][setup]
        t32_tot, t32_set, t32_enc = time_p32[fam_key][setup]
        
        c31 = t31_tot * cost_mult[fam_key][setup]
        c32 = t32_tot * cost_mult[fam_key][setup]
        
        # Improvement relative to Serial
        t31_tot_ser = time_p31[fam_key]["ser"][0]
        t32_tot_ser = time_p32[fam_key]["ser"][0]
        
        c31_ser = t31_tot_ser * cost_mult[fam_key]["ser"]
        c32_ser = t32_tot_ser * cost_mult[fam_key]["ser"]
        
        # Cost Reduction = (Serial - Target) / Serial * 100
        cred31 = (c31_ser - c31) / c31_ser * 100 if setup != "ser" else 0
        cred32 = (c32_ser - c32) / c32_ser * 100 if setup != "ser" else 0
        
        # Time Improve = (Serial - Target) / Serial * 100
        timp31 = (t31_tot_ser - t31_tot) / t31_tot_ser * 100 if setup != "ser" else 0
        timp32 = (t32_tot_ser - t32_tot) / t32_tot_ser * 100 if setup != "ser" else 0
        
        name = {"ser": "Serial", "par": "Parallel", "ver": "Vertical"}[setup]
        print(f"--- {name} ---")
        print(f"Total Time:      {t31_tot:.2f} | {t32_tot:.2f}")
        print(f"Setup Over:      {t31_set:.2f} | {t32_set:.2f}")
        print(f"Setup Over %:    {t31_set/t31_tot*100:.1f}% | {t32_set/t32_tot*100:.1f}%")
        print(f"Eff Enc Time:    {t31_enc:.2f} | {t32_enc:.2f}")
        print(f"Total Cost:      ${c31:.5f} | ${c32:.5f}")
        print(f"Cost per Min:    ${c31/10:.6f} | ${c32/10:.6f}")
        print(f"Time Improve %:  {timp31:.1f}% | {timp32:.1f}%")
        print(f"Cost Reduc %:    {cred31:.0f}% | {cred32:.0f}%")

