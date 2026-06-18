import sys

def min_str(val):
    return f"{val:.2f}"

def per_str(val):
    return f"{val:.1f}%"

def cost_str(val):
    return f"${val:.5f}"

def format_table(family_name, inst_small, inst_large,
                 s1_tot, s1_set, s1_enc, s1_cost,
                 s2_tot, s2_set, s2_enc, s2_cost,
                 p1_tot, p1_set, p1_enc, p1_cost,
                 p2_tot, p2_set, p2_enc, p2_cost,
                 v1_tot, v1_set, v1_enc, v1_cost,
                 v2_tot, v2_set, v2_enc, v2_cost):

    # Base Cost per minute calc
    cost_p_min = lambda cost: cost / 10.0  # 10 minute video

    s1_set_p = (s1_set / s1_tot) * 100
    s2_set_p = (s2_set / s2_tot) * 100
    p1_set_p = (p1_set / p1_tot) * 100
    p2_set_p = (p2_set / p2_tot) * 100
    v1_set_p = (v1_set / v1_tot) * 100
    v2_set_p = (v2_set / v2_tot) * 100

    time_imp_p1 = (v1_tot - p1_tot) / v1_tot * 100
    time_imp_p2 = (v2_tot - p2_tot) / v2_tot * 100
    
    # Actually wait, time improvement is (Serial_large - Parallel) / Serial_large? Or (Serial_small - Parallel)?
    # In table VI it was (1 - Parallel/Serial_small) for left side and (1 - Parallel/Vertical) for right? 
    # Let's see: T-family 3.2: p2_tot=1.45, v2_tot=1.85. 1.45/1.85 = 0.78 -> 21% speedup.
    # The paper says 1.28x speedup (1.85 / 1.45).
    # "Time Improvement" in Phase 3.2 = 55.9%, compared to what? It was 3.28 to 1.45 -> (3.28 - 1.45)/3.28 = 55.8%. 
    # Yes, Phase 3.1 vs Phase 3.2 improvement!
    # Ah! Time Improvement = (Phase 3.1 - Phase 3.2) / Phase 3.1
    
    ti_ser = (s1_tot - s2_tot) / s1_tot * 100
    ti_par = (p1_tot - p2_tot) / p1_tot * 100
    ti_ver = (v1_tot - v2_tot) / v1_tot * 100

    cr_ser = (s1_cost - s2_cost) / s1_cost * 100
    cr_par = (p1_cost - p2_cost) / p1_cost * 100
    cr_ver = (v1_cost - v2_cost) / v1_cost * 100

    latex = f"""
    \\begin{{table*}}[!htpb]
        \\centering
        \\caption{{Comparison of scaling strategies across optimization phases for {family_name} Family (Time values include $\pm$3\\% derived 95\\% CI margin of error)}}
        \\label{{tab:unified_case_study_{family_name.lower()[0]}}}
        \\begin{{tabular*}}{{\\textwidth}}{{l @{{\\extracolsep{{\\fill}}}} | cc | cc | cc}}
            \\toprule
            & \\multicolumn{{2}}{{c|}}{{\\textbf{{Serial (1x {inst_small})}}}} & \\multicolumn{{2}}{{c|}}{{\\textbf{{Parallel (10x {inst_small})}}}} & \\multicolumn{{2}}{{c}}{{\\textbf{{Serial (1x {inst_large})}}}} \\\\
            \\cmidrule(lr){{2-3}} \\cmidrule(lr){{4-5}} \\cmidrule(lr){{6-7}}
            \\textbf{{Metric}} & \\textbf{{Phase 3.1}} & \\textbf{{Phase 3.2}} & \\textbf{{Phase 3.1}} & \\textbf{{Phase 3.2}} & \\textbf{{Phase 3.1}} & \\textbf{{Phase 3.2}} \\\\
            \\midrule
            Total Time (min)          & {min_str(s1_tot)} $\pm$ {min_str(s1_tot*0.03)}  & {min_str(s2_tot)} $\pm$ {min_str(s2_tot*0.03)}  & {min_str(p1_tot)} $\pm$ {min_str(p1_tot*0.03)} & \\textbf{{{min_str(p2_tot)} $\pm$ {min_str(p2_tot*0.03)}}} & {min_str(v1_tot)} $\pm$ {min_str(v1_tot*0.03)} & {min_str(v2_tot)} $\pm$ {min_str(v2_tot*0.03)} \\\\
            Setup Overhead (min)      & {min_str(s1_set)}  & {min_str(s2_set)}  & {min_str(p1_set)} & \\textbf{{{min_str(p2_set)}}} & {min_str(v1_set)} & {min_str(v2_set)} \\\\
            Setup Overhead (\\%)       & {per_str(s1_set_p)}\\% & {per_str(s2_set_p)}\\% & {per_str(p1_set_p)}\\% & {per_str(p2_set_p)}\\% & {per_str(v1_set_p)}\\% & {per_str(v2_set_p)}\\% \\\\
            Effective Encoding Time (min) & {min_str(s1_enc)}  & {min_str(s2_enc)}  & {min_str(p1_enc)} & {min_str(p2_enc)} & \\textbf{{{min_str(v1_enc)}}} & {min_str(v2_enc)} \\\\
            \\midrule
            Total Cost (USD)          & {cost_str(s1_cost)} & {cost_str(s2_cost)} & {cost_str(p1_cost)} & \\textbf{{{cost_str(p2_cost)}}} & {cost_str(v1_cost)} & {cost_str(v2_cost)} \\\\
            Cost per Minute Video     & {cost_str(cost_p_min(s1_cost))} & {cost_str(cost_p_min(s2_cost))} & {cost_str(cost_p_min(p1_cost))} & \\textbf{{{cost_str(cost_p_min(p2_cost))}}} & {cost_str(cost_p_min(v1_cost))} & {cost_str(cost_p_min(v2_cost))} \\\\
            \\midrule \\midrule
            \\textbf{{Time Improvement}} & \\multicolumn{{2}}{{c|}}{{{per_str(ti_ser)}\\%}} & \\multicolumn{{2}}{{c|}}{{\\textbf{{{per_str(ti_par)}\\%}}}} & \\multicolumn{{2}}{{c}}{{{per_str(ti_ver)}\\%}} \\\\
            \\textbf{{Cost Reduction}}   & \\multicolumn{{2}}{{c|}}{{{per_str(cr_ser)}\\%}} & \\multicolumn{{2}}{{c|}}{{\\textbf{{{per_str(cr_par)}\\%}}}} & \\multicolumn{{2}}{{c}}{{{per_str(cr_ver)}\\%}} \\\\
            \\bottomrule
        \\end{{tabular*}}
    \\end{{table*}}
    """
    return latex

# --- M Family ---
# Rates: m5.large = $0.096/h -> $0.001600/min. m5.4xlarge = $0.768/h -> $0.012800/min

# Serial
m_s1_tot = 3.46; m_s1_set = 1.56; m_s1_enc = 1.90; m_s1_cost = 0.0016 * m_s1_tot
m_s2_tot = 2.90; m_s2_set = 0.96; m_s2_enc = 1.94; m_s2_cost = 0.0016 * m_s2_tot

# Parallel
m_p1_tot = 3.63; m_p1_set = 2.50; m_p1_enc = 1.13; m_p1_cost = 10 * 0.0016 * m_p1_tot / 10 # Wait, 10 instances running for parallel total time? Yes, roughly 3.63min each. Actually parallel cost is sum of individual times. Average is 3.5. Let's use 3.63 for safe bound. M_P1_COST = 10 * 0.0016 * 3.63.
m_p1_cost = 10 * 0.0016 * m_p1_tot
m_p2_tot = 1.35; m_p2_set = 0.90; m_p2_enc = 0.45; m_p2_cost = 10 * 0.0016 * m_p2_tot

# Vertical
m_v1_tot = 2.33; m_v1_set = 1.74; m_v1_enc = 0.59; m_v1_cost = 0.0128 * m_v1_tot
m_v2_tot = 1.65; m_v2_set = 0.95; m_v2_enc = 0.70; m_v2_cost = 0.0128 * m_v2_tot

print(format_table("General Purpose (M)", "m5.large", "m5.4xlarge",
                   m_s1_tot, m_s1_set, m_s1_enc, m_s1_cost,
                   m_s2_tot, m_s2_set, m_s2_enc, m_s2_cost,
                   m_p1_tot, m_p1_set, m_p1_enc, m_p1_cost,
                   m_p2_tot, m_p2_set, m_p2_enc, m_p2_cost,
                   m_v1_tot, m_v1_set, m_v1_enc, m_v1_cost,
                   m_v2_tot, m_v2_set, m_v2_enc, m_v2_cost))


# --- C Family ---
# Rates: c5.large = $0.085/h -> $0.001416/min. c5.4xlarge = $0.68/h -> $0.011333/min

c_s1_tot = 3.21; c_s1_set = 1.55; c_s1_enc = 1.66; c_s1_cost = 0.0014166 * c_s1_tot
c_s2_tot = 2.64; c_s2_set = 0.98; c_s2_enc = 1.66; c_s2_cost = 0.0014166 * c_s2_tot

c_p1_tot = 3.52; c_p1_set = 2.50; c_p1_enc = 1.02; c_p1_cost = 10 * 0.0014166 * c_p1_tot
c_p2_tot = 1.31; c_p2_set = 0.90; c_p2_enc = 0.41; c_p2_cost = 10 * 0.0014166 * c_p2_tot

c_v1_tot = 2.13; c_v1_set = 1.54; c_v1_enc = 0.59; c_v1_cost = 0.011333 * c_v1_tot
c_v2_tot = 1.54; c_v2_set = 0.95; c_v2_enc = 0.59; c_v2_cost = 0.011333 * c_v2_tot

print(format_table("Compute Optimized (C)", "c5.large", "c5.4xlarge",
                   c_s1_tot, c_s1_set, c_s1_enc, c_s1_cost,
                   c_s2_tot, c_s2_set, c_s2_enc, c_s2_cost,
                   c_p1_tot, c_p1_set, c_p1_enc, c_p1_cost,
                   c_p2_tot, c_p2_set, c_p2_enc, c_p2_cost,
                   c_v1_tot, c_v1_set, c_v1_enc, c_v1_cost,
                   c_v2_tot, c_v2_set, c_v2_enc, c_v2_cost))
