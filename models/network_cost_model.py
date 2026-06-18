#!/usr/bin/env python3
"""
Melhoria 5 — Analytical Network & Storage Cost Estimation

Models the "cost floor" that no compute optimization eliminates:
EBS storage, intra-region transfer, and internet egress costs
for a realistic Video-as-a-Service (VaaS) pipeline.

Pipeline modeled:
  1. Client uploads video to orchestrator (ingress = FREE)
  2. Orchestrator splits video into N chunks
  3. Orchestrator uploads chunks to N worker EC2 instances (intra-region)
  4. Workers encode chunks and return compressed output (intra-region)
  5. Orchestrator concatenates and delivers to end-user (egress)

Data transfer pricing (AWS, current as of 2025):
  - Ingress (internet → EC2): FREE
  - Intra-region same-AZ (private IP): FREE
  - Intra-region cross-AZ: $0.01/GB each direction
  - Egress (EC2 → internet): $0.09/GB (us-east-1), $0.15/GB (sa-east-1)
  - EBS gp3: $0.08/GB-month (us-east-1), $0.096/GB-month (sa-east-1)
"""


# ============================================================================
# PRICING CONSTANTS (USD)
# ============================================================================

PRICING = {
    "us-east-1": {
        "ingress": 0.00,           # Internet → EC2: FREE
        "intra_same_az": 0.00,     # Same AZ, private IP: FREE
        "intra_cross_az": 0.01,    # Cross-AZ: $0.01/GB each direction
        "egress_first_10tb": 0.09, # EC2 → Internet: first 10 TB/month
        "ebs_gp3_per_gb_month": 0.08,
        "label": "N. Virginia",
    },
    "sa-east-1": {
        "ingress": 0.00,
        "intra_same_az": 0.00,
        "intra_cross_az": 0.01,
        "egress_first_10tb": 0.15,
        "ebs_gp3_per_gb_month": 0.096,
        "label": "São Paulo",
    },
}

# Compute costs from the paper (horizontal 10x optimized, H.264, n=30 avg)
# Cost = instance_price_per_hour × (total_time_seconds / 3600) × num_instances
INSTANCE_PRICES = {
    "us-east-1": {
        "t3.micro":   0.0104,
        "m5.large":   0.0960,
        "c5.large":   0.0850,
    },
    "sa-east-1": {
        "t3.micro":   0.0156,
        "m5.large":   0.1380,
        "c5.large":   0.1220,
    },
}

# Phase 3.2 optimized horizontal (10 nodes, 60s chunks) average times (seconds)
HORIZONTAL_TIMES = {
    "t3.micro":  73.36,   # from averages_n30.csv
    "m5.large":  73.12,
    "c5.large":  70.97,
}

NUM_NODES = 10


# ============================================================================
# VIDEO WORKLOAD PROFILE
# ============================================================================

class VideoProfile:
    def __init__(self, name, duration_min, input_mb, output_mb):
        self.name = name
        self.duration_min = duration_min
        self.input_mb = input_mb
        self.output_mb = output_mb
        self.input_gb = input_mb / 1024
        self.output_gb = output_mb / 1024
        self.chunk_input_mb = input_mb / NUM_NODES
        self.chunk_output_mb = output_mb / NUM_NODES


PROFILES = [
    VideoProfile("10min 1080p (paper)", 10, 500, 150),
    VideoProfile("30min 1080p",         30, 1500, 450),
    VideoProfile("60min 1080p",         60, 3000, 900),
    VideoProfile("10min 4K",            10, 2000, 600),
]


# ============================================================================
# COST MODEL
# ============================================================================

def calculate_network_costs(profile, region_key, cross_az=True):
    """Calculate all non-compute costs for horizontal scaling pipeline."""
    p = PRICING[region_key]
    v = profile

    # Transfer rates (assuming cross-AZ since parallel instances land in different AZs)
    transfer_rate = p["intra_cross_az"] if cross_az else p["intra_same_az"]

    # Step 1: Client upload (ingress) — FREE
    ingress_cost = 0.0

    # Step 2: Orchestrator → Workers (upload N chunks, cross-AZ)
    upload_gb = v.input_gb  # total input distributed across N workers
    upload_cost = upload_gb * transfer_rate * 2  # bidirectional: out from orch + in at worker

    # Step 3: Workers → Orchestrator (download N compressed chunks)
    download_gb = v.output_gb
    download_cost = download_gb * transfer_rate * 2  # bidirectional

    # Step 4: Orchestrator → End user (egress)
    egress_cost = v.output_gb * p["egress_first_10tb"]

    # Step 5: EBS temporary storage (assume 1 hour of usage = 1/(720) of monthly cost)
    # Each worker needs: input chunk + output chunk storage
    # Orchestrator needs: full input + full output
    total_storage_gb = (v.input_gb + v.output_gb) * 2  # workers + orchestrator
    ebs_cost = total_storage_gb * p["ebs_gp3_per_gb_month"] / 720  # 720 hours/month

    total_network = ingress_cost + upload_cost + download_cost + egress_cost + ebs_cost

    return {
        "ingress": ingress_cost,
        "upload_to_workers": upload_cost,
        "download_from_workers": download_cost,
        "egress_to_user": egress_cost,
        "ebs_temp": ebs_cost,
        "total_network": total_network,
    }


def calculate_compute_cost(instance_type, region_key):
    """Calculate compute cost for horizontal scaling."""
    price = INSTANCE_PRICES[region_key][instance_type]
    time_s = HORIZONTAL_TIMES[instance_type]
    # Each of 10 nodes runs for the full duration
    return price * (time_s / 3600) * NUM_NODES


# ============================================================================
# MAIN ANALYSIS
# ============================================================================

print("=" * 90)
print("MELHORIA 5 — ESTIMATIVA ANALÍTICA DE CUSTOS DE REDE E STORAGE")
print("=" * 90)
print()
print("Pipeline: Upload → Split → Distribute (cross-AZ) → Encode → Retrieve → Egress")
print(f"Modo: Horizontal {NUM_NODES}x nodes, AMI otimizada, H.264")
print()

# Reference scenario: 10min 1080p video
ref = PROFILES[0]
print(f"═══ CENÁRIO DE REFERÊNCIA: {ref.name} ═══")
print(f"  Input:  {ref.input_mb} MB ({ref.input_gb:.2f} GB)")
print(f"  Output: {ref.output_mb} MB ({ref.output_gb:.2f} GB)")
print()

for region in ["us-east-1", "sa-east-1"]:
    p = PRICING[region]
    print(f"─── {p['label']} ({region}) ───")
    print()

    net = calculate_network_costs(ref, region)

    print("  Custos de rede/storage:")
    print(f"    Ingress (upload do cliente):     ${net['ingress']:.6f}  (FREE)")
    print(f"    Orch → Workers (cross-AZ):       ${net['upload_to_workers']:.6f}")
    print(f"    Workers → Orch (cross-AZ):       ${net['download_from_workers']:.6f}")
    print(f"    Egress (entrega ao usuário):      ${net['egress_to_user']:.6f}")
    print(f"    EBS temporário:                   ${net['ebs_temp']:.6f}")
    print(f"    ──────────────────────────────────")
    print(f"    TOTAL REDE + STORAGE:             ${net['total_network']:.6f}")
    print()

    print("  Custos de compute (horizontal 10x, AMI opt):")
    for inst in ["t3.micro", "m5.large", "c5.large"]:
        comp = calculate_compute_cost(inst, region)
        ratio = net['total_network'] / comp if comp > 0 else float('inf')
        print(f"    {inst:12s}: ${comp:.6f}  →  rede/compute = {ratio:.1f}×")
    print()

# ============================================================================
# COMPARISON TABLE: ALL PROFILES × REGIONS
# ============================================================================

print()
print("=" * 90)
print("TABELA COMPARATIVA — CUSTO POR VÍDEO (USD)")
print("=" * 90)
print()
print(f"{'Perfil':<22s} {'Região':<12s} {'Rede+Stor':>10s} {'Compute':>10s} {'Total':>10s} {'%Rede':>7s}")
print("-" * 75)

for prof in PROFILES:
    for region in ["us-east-1", "sa-east-1"]:
        net = calculate_network_costs(prof, region)
        # Use cheapest compute (t3.micro)
        comp = calculate_compute_cost("t3.micro", region)
        total = net["total_network"] + comp
        pct = (net["total_network"] / total) * 100 if total > 0 else 0
        rlabel = PRICING[region]["label"][:6]
        print(f"{prof.name:<22s} {rlabel:<12s} ${net['total_network']:>8.5f}  ${comp:>8.5f}  ${total:>8.5f}  {pct:>5.1f}%")

# ============================================================================
# KEY INSIGHT: EGRESS DOMINANCE THRESHOLD
# ============================================================================

print()
print("=" * 90)
print("INSIGHT PRINCIPAL — DOMINÂNCIA DO EGRESS")
print("=" * 90)
print()

for region in ["us-east-1", "sa-east-1"]:
    p = PRICING[region]
    print(f"─── {p['label']} ({region}) ───")

    # At what output size does egress exceed cheapest compute?
    cheapest_compute = calculate_compute_cost("t3.micro", region)
    egress_rate = p["egress_first_10tb"]
    threshold_gb = cheapest_compute / egress_rate
    threshold_mb = threshold_gb * 1024

    print(f"  Compute mais barato (t3.micro ×10): ${cheapest_compute:.5f}")
    print(f"  Egress rate: ${egress_rate}/GB")
    print(f"  Egress = Compute quando output ≥ {threshold_mb:.0f} MB ({threshold_gb:.2f} GB)")
    print(f"  → Vídeos 1080p ~150 MB output: egress = ${0.150/1024*egress_rate:.5f} ({'abaixo' if 150 < threshold_mb else 'ACIMA'} do threshold)")
    print(f"  → Vídeos 4K ~600 MB output: egress = ${0.600/1024*egress_rate:.5f} ({'abaixo' if 600 < threshold_mb else 'ACIMA'} do threshold)")
    print()

# ============================================================================
# BATCH ANALYSIS: 1000 videos/day
# ============================================================================

print()
print("=" * 90)
print("PROJEÇÃO: PIPELINE PRODUÇÃO — 1000 vídeos/dia (10min 1080p)")
print("=" * 90)
print()

ref = PROFILES[0]
for region in ["us-east-1", "sa-east-1"]:
    p = PRICING[region]
    net = calculate_network_costs(ref, region)
    comp = calculate_compute_cost("t3.micro", region)

    daily_net = net["total_network"] * 1000
    daily_comp = comp * 1000
    daily_total = daily_net + daily_comp
    monthly_total = daily_total * 30

    print(f"─── {p['label']} ({region}) ───")
    print(f"  Por vídeo:  rede=${net['total_network']:.5f}  compute=${comp:.5f}  total=${net['total_network']+comp:.5f}")
    print(f"  Diário (1000 vídeos):  rede=${daily_net:.2f}  compute=${daily_comp:.2f}  total=${daily_total:.2f}")
    print(f"  Mensal (30k vídeos):   rede=${monthly_total-daily_comp*30:.2f}  compute=${daily_comp*30:.2f}  total=${monthly_total:.2f}")
    pct = (daily_net / daily_total) * 100
    print(f"  Rede como % do total: {pct:.1f}%")
    print()

# ============================================================================
# LATEX OUTPUT
# ============================================================================

print()
print("=" * 90)
print("LATEX — TABELA DE CUSTOS REDE vs COMPUTE")
print("=" * 90)
print()
print(r"\begin{table}[h]")
print(r"\centering")
print(r"\caption{Network and storage costs vs.\ compute costs per video for horizontal scaling with 10$\times$ t3.micro (Phase 3.2 AMI). Reference: 10-min 1080p H.264 video.}")
print(r"\label{tab:network_costs}")
print(r"\resizebox{\columnwidth}{!}{")
print(r"\begin{tabular}{|l|c|c|c|c|c|}")
print(r"\hline")
print(r"\textbf{Region} & \textbf{Intra-region} & \textbf{Egress} & \textbf{EBS} & \textbf{Total Network} & \textbf{Compute (t3.micro$\times$10)} \\")
print(r"\hline")

for region in ["us-east-1", "sa-east-1"]:
    p = PRICING[region]
    net = calculate_network_costs(ref, region)
    comp = calculate_compute_cost("t3.micro", region)
    intra = net["upload_to_workers"] + net["download_from_workers"]
    print(f"{p['label']} & \\${intra:.5f} & \\${net['egress_to_user']:.5f} & \\${net['ebs_temp']:.6f} & \\${net['total_network']:.5f} & \\${comp:.5f} \\\\")

print(r"\hline")
print(r"\end{tabular}")
print(r"}")
print(r"\end{table}")
