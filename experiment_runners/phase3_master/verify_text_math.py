import csv

csv_file = "./artifacts2/phase3_scaling/n30_parsed/averages_n30.csv"

# Load the data
data = {}
with open(csv_file, "r") as f:
    reader = csv.reader(f)
    next(reader) # skip header
    for row in reader:
        arch = row[0]
        # Format: Architecture,CleanRunsCount,AvgTotalTime,AvgSetupTime,AvgEncodingTime
        data[arch] = {
            "total": float(row[2]),
            "setup": float(row[3]),
            "enc": float(row[4])
        }

prices = {
    "c5_large_horizontal_opt": 10 * 0.085, # $0.085/hr for c5.large on-demand -> wait, c5.large is 0.085
    "c5_4xlarge_vertical_opt": 0.68,
    "m5_large_horizontal_opt": 10 * 0.096,
    "m5_4xlarge_vertical_opt": 0.768,
    "t3_micro_paralelo_phase2": 10 * 0.0104,
    "t3_2xlarge_phase2": 0.3328
}

print("=== T-Family ===")
t_vert_t = data["t3_2xlarge_phase2"]["total"] / 60
t_horiz_t = data["t3_micro_paralelo_phase2"]["total"] / 60

print(f"t3.2xlarge Total: {t_vert_t:.2f} min (Expected Table V: 1.80)")
print(f"10x t3.micro Total: {t_horiz_t:.2f} min (Expected Table V: 1.22)")
print(f"Speedup Horizontal vs Vertical: {t_vert_t / t_horiz_t:.2f}x (Expected text: 1.48x)")

t_vert_cost = (0.3328 / 60) * t_vert_t
t_horiz_cost = (10 * 0.0104 / 60) * t_horiz_t
print(f"t3.2xlarge Cost: ${t_vert_cost:.5f} (Expected Table V: $0.00999)")
print(f"10x t3.micro Cost: ${t_horiz_cost:.5f} (Expected Table V: $0.00212)")
print(f"Cost Reduction ((Vert-Horiz)/Vert): {100 * (t_vert_cost - t_horiz_cost) / t_vert_cost:.1f}% (Expected abstract: 75.5%?)") 
# Wait, cost reduction calculation in Latex: (0.00212 - 0.00999)/0.00999? Actually table says -2025% which means they use different formula. Ah, (P3.1 - P3.2) / P3.2 maybe or something else?

print("\n=== M-Family ===")
m_vert_t = data["m5_4xlarge_vertical_opt"]["total"] / 60
m_horiz_t = data["m5_large_horizontal_opt"]["total"] / 60
print(f"m5.4xlarge Total: {m_vert_t:.2f} min (Expected Table VI: 1.56)")
print(f"10x m5.large Total: {m_horiz_t:.2f} min (Expected Table VI: 1.21)")
print(f"Speedup Horizontal vs Vertical: {m_vert_t / m_horiz_t:.2f}x (Expected text: 1.29x)")

m_vert_cost = (0.768 / 60) * m_vert_t
m_horiz_cost = (10 * 0.096 / 60) * m_horiz_t
print(f"m5.4xlarge Cost: ${m_vert_cost:.5f} (Expected text: $0.0200)")
print(f"10x m5.large Cost: ${m_horiz_cost:.5f} (Expected text: $0.0193)")
print(f"M-family cost savings: {100 * (m_vert_cost - m_horiz_cost) / m_vert_cost:.1f}% (Expected text: 3.5%)")

print("\n=== C-Family ===")
c_vert_t = data["c5_4xlarge_vertical_opt"]["total"] / 60
c_horiz_t = data["c5_large_horizontal_opt"]["total"] / 60
print(f"c5.4xlarge Total: {c_vert_t:.2f} min (Expected Table VI: 1.49)")
print(f"10x c5.large Total: {c_horiz_t:.2f} min (Expected Table VI: 1.18)")
print(f"Speedup Horizontal vs Vertical: {c_vert_t / c_horiz_t:.2f}x (Expected text: 1.26x)")

c_vert_cost = (0.68 / 60) * c_vert_t
c_horiz_cost = (10 * 0.085 / 60) * c_horiz_t
print(f"c5.4xlarge Cost: ${c_vert_cost:.5f} (Expected text: $0.0169)")
print(f"10x c5.large Cost: ${c_horiz_cost:.5f} (Expected text: $0.0167)")
print(f"C-family cost savings: {100 * (c_vert_cost - c_horiz_cost) / c_vert_cost:.1f}% (Expected text: 1.2%)")

# Phase 2 29x cost efficiency check
t3_micro_cost_per_sec = 0.0104 / 3600
c5_4xlarge_cost_per_sec = 0.68 / 3600

# values from Table IV (tab:final_comparison_consistent)
t3_micro_time_5t = 2.5307
c5_4xlarge_time_10t = 1.1260

t3_micro_eff = 1 / (t3_micro_cost_per_sec * t3_micro_time_5t)
c5_4xlarge_eff = 1 / (c5_4xlarge_cost_per_sec * c5_4xlarge_time_10t)

print(f"\nPhase 2 29x factor (Expected text: 29-fold): {t3_micro_eff / c5_4xlarge_eff:.2f}x")
