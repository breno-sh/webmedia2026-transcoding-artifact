#!/usr/bin/env python3
"""
Melhoria 4 — Analytical Chunk-Size Optimization Model

Derives a prescriptive formula for the optimal chunk duration c* that
minimizes total wall-clock time T_total(c) in horizontal scaling.

Model:
  T_total(c) = T_prov(N) + T_encode(c) + T_transfer(c)

where:
  N            = D / c         (number of nodes)
  T_prov(N)    = p0 + p1 × N   (provisioning grows linearly with N due to API contention)
  T_encode(c)  = r × c         (per-node encoding, linear in chunk duration)
  T_transfer(c)= α × c         (SFTP upload/download proportional to chunk size)

Combining:
  T_total(c) = p0 + p1·(D/c) + (r + α)·c
             = p0 + p1·D/c + a·c

where a = r + α (combined encoding + transfer rate per second of chunk).

Taking derivative:
  dT/dc = a - p1·D / c² = 0
  c* = sqrt(p1 · D / a)

Data source: Table VI of the paper (canonical, averaged runs).
"""

import numpy as np


# ============================================================================
# EMPIRICAL DATA FROM TABLE VI (canonical, paper values)
# ============================================================================

D = 600  # seconds (10-minute video)

# Table VI data: {chunk_duration_s: total_time_min}
# Vertical baselines from Table V (n=30 averages)
empirical = {
    "Burstable (T)": {
        30:  1.39,   # 20x t3.micro
        60:  1.22,   # 10x t3.micro (best)
        120: 2.04,   # 5x t3.micro
        "vertical_min": 1.80,  # t3.2xlarge, n=45 avg
    },
    "General (M)": {
        30:  1.63,   # 20x m5.large
        60:  1.22,   # 10x m5.large (best)
        120: 2.10,   # 5x m5.large
        "vertical_min": 1.56,  # m5.4xlarge, n=30 avg (93.70s / 60)
    },
    "Compute (C)": {
        30:  1.44,   # 20x c5.large
        60:  1.18,   # 10x c5.large (best)
        120: 1.98,   # 5x c5.large
        "vertical_min": 1.49,  # c5.4xlarge, n=30 avg (89.49s / 60)
    },
}


def fit_model(family_name, data):
    """
    Fit: T(c) = p0 + p1·D/c + a·c  (in minutes)

    3 data points (c=30,60,120), 3 unknowns (p0, p1, a).
    """
    chunks = [30, 60, 120]
    times = [data[c] for c in chunks]

    # Linear system: [1, D/c, c] × [p0, p1, a]^T = T
    A = np.array([
        [1, D / chunks[0], chunks[0]],
        [1, D / chunks[1], chunks[1]],
        [1, D / chunks[2], chunks[2]],
    ])
    b_vec = np.array(times)

    params = np.linalg.solve(A, b_vec)
    p0 = params[0]   # fixed provisioning base (min)
    p1 = params[1]   # per-node provisioning cost (min·node)
    a  = params[2]   # encoding+transfer rate (min/s-of-chunk)

    # Optimal chunk
    if a > 0 and p1 > 0:
        c_star = np.sqrt(p1 * D / a)
    else:
        c_star = float('nan')

    # T_min at c*
    if not np.isnan(c_star):
        T_min = p0 + p1 * D / c_star + a * c_star
    else:
        T_min = float('nan')

    # Predictions for various chunk sizes
    predictions = {}
    for c in [15, 20, 30, 40, 50, 60, 75, 90, 120, 150, 180, 240, 300]:
        predictions[c] = p0 + p1 * D / c + a * c

    # Residuals (should be ~0 since we fit 3 params to 3 points)
    residuals = {c: abs(p0 + p1 * D / c + a * c - data[c]) for c in chunks}

    return {
        "p0": p0, "p1": p1, "a": a,
        "c_star": c_star, "T_min": T_min,
        "predictions": predictions, "residuals": residuals,
    }


def speedup_range(p0, p1, a, T_vert):
    """
    Find c range where horizontal is faster than vertical.
    p0 + p1·D/c + a·c < T_vert
    a·c² - (T_vert - p0)·c + p1·D < 0
    """
    A_coeff = a
    B_coeff = -(T_vert - p0)
    C_coeff = p1 * D, 

    disc = B_coeff**2 - 4 * A_coeff * C_coeff[0]
    if disc < 0:
        return None, None
    c1 = (-B_coeff - np.sqrt(disc)) / (2 * A_coeff)
    c2 = (-B_coeff + np.sqrt(disc)) / (2 * A_coeff)
    return c1, c2


# ============================================================================
# MAIN
# ============================================================================

print("=" * 80)
print("MELHORIA 4 — MODELO ANALÍTICO DE CHUNK ÓTIMO")
print("=" * 80)
print()
print("Modelo: T(c) = p₀ + p₁·D/c + a·c   [minutos]")
print("  p₀ = base fixa de provisionamento")
print("  p₁ = custo incremental de provisionamento por nó")
print("  a  = taxa de encoding + transferência (min/s de chunk)")
print("  D  = 600s (vídeo de 10 min)")
print()

results = {}
for family in empirical:
    data = empirical[family]
    r = fit_model(family, data)
    results[family] = r

    print(f"═══ {family} ═══")
    print(f"  p₀ (base prov):       {r['p0']:.4f} min ({r['p0']*60:.1f}s)")
    print(f"  p₁ (custo/nó):        {r['p1']:.6f} min·nó ({r['p1']*60:.3f}s/nó)")
    print(f"  a  (enc+transfer):    {r['a']:.6f} min/s  ({r['a']*60:.4f}s/s)")
    print(f"  c* (chunk ótimo):     {r['c_star']:.1f}s")
    print(f"  T_min(c*):            {r['T_min']:.3f} min ({r['T_min']*60:.1f}s)")
    print(f"  Fit residuals:        {r['residuals']}")
    print()

    # Speedup range
    T_vert = data["vertical_min"]
    c1, c2 = speedup_range(r["p0"], r["p1"], r["a"], T_vert)
    if c1 is not None and c1 > 0:
        print(f"  Speedup > 1× vs vertical ({T_vert:.2f} min):")
        print(f"    para c ∈ [{max(1,c1):.1f}s, {c2:.1f}s]")
    elif c1 is not None:
        print(f"  Speedup > 1× vs vertical ({T_vert:.2f} min):")
        print(f"    para c ∈ [~0s, {c2:.1f}s]")
    else:
        print(f"  Sem intervalo de speedup (horizontal sempre mais lento)")
    print()

# ============================================================================
# PREDICTION TABLE
# ============================================================================

print("=" * 80)
print("TABELA DE PREDIÇÕES — T_total (min) por chunk")
print("=" * 80)
header = f"{'Chunk':>7s} {'Nodes':>6s}"
for fam in results:
    short = fam.split("(")[1].rstrip(")")
    header += f"  {short:>6s}"
print(header)
print("-" * 68)

for c in [20, 30, 40, 50, 60, 75, 90, 120, 150, 180, 240]:
    N = D // c
    row = f"{c:>5d}s {N:>5d}x"
    for fam in results:
        pred = results[fam]["predictions"][c]
        row += f"  {pred:>6.3f}"
    # Mark empirical points
    marker = ""
    if c in [30, 60, 120]:
        marker = " ← empírico"
    print(row + marker)

print()
print("=" * 80)
print("FÓRMULA GERAL")
print("=" * 80)
print()
print("Dado:")
print("  D      = duração total do vídeo (s)")
print("  p₁     = custo de provisionamento por nó (min)")
print("  a      = taxa de encoding + transferência (min/s)")
print()
print("Chunk ótimo:")
print("  c* = √(p₁ · D / a)")
print()
print("Tempo mínimo:")
print("  T_min = p₀ + 2·√(p₁ · D · a)")
print()
print("Generalização para vídeo de duração D':")
print("  c*(D') = √(p₁ · D' / a)")
print("  → Para vídeos mais longos, chunks maiores são ótimos")
print("  → Para vídeos mais curtos, chunks menores são ótimos")
print()

# Example: what's optimal for different video lengths?
print("=" * 80)
print("GENERALIZAÇÃO — CHUNK ÓTIMO POR DURAÇÃO DE VÍDEO")
print("=" * 80)
print()
print(f"{'Duração':>10s}", end="")
for fam in results:
    short = fam.split("(")[1].rstrip(")")
    print(f"  {'c*_'+short:>8s}  {'T_min':>6s}", end="")
print()
print("-" * 80)

for D_test in [60, 120, 300, 600, 1200, 1800, 3600]:
    label = f"{D_test}s" if D_test < 60 else f"{D_test//60}min"
    row = f"{label:>10s}"
    for fam in results:
        r = results[fam]
        c_opt = np.sqrt(r["p1"] * D_test / r["a"])
        T_min = r["p0"] + 2 * np.sqrt(r["p1"] * D_test * r["a"])
        row += f"  {c_opt:>7.1f}s  {T_min:>5.2f}m"
    print(row)

print()

# ============================================================================
# LATEX OUTPUT
# ============================================================================

print("=" * 80)
print("LATEX — TABELA DE PARÂMETROS DO MODELO")
print("=" * 80)
print()
print(r"\begin{table}[h]")
print(r"\centering")
print(r"\caption{Fitted parameters for the chunk-size optimization model $T(c) = p_0 + p_1 \cdot D/c + a \cdot c$.}")
print(r"\label{tab:chunk_model}")
print(r"\begin{tabular}{|l|c|c|c|c|c|}")
print(r"\hline")
print(r"\textbf{Family} & $p_0$ (min) & $p_1$ (min) & $a$ (min/s) & $c^*$ (s) & $T_{\min}$ (min) \\")
print(r"\hline")
for fam in results:
    r = results[fam]
    short = fam.split("(")[1].rstrip(")")
    print(f"{short} & {r['p0']:.3f} & {r['p1']:.4f} & {r['a']:.6f} & {r['c_star']:.0f} & {r['T_min']:.3f} \\\\")
print(r"\hline")
print(r"\end{tabular}")
print(r"\end{table}")
