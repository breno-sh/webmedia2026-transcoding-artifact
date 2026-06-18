#!/usr/bin/env python3
"""
Batch Orchestrator — Run all experiments for Melhorias 1, 2, and 3.

This script generates and optionally executes all the phase3_unified.py
commands needed for the complete experiment matrix.

Usage:
  python3 run_all_experiments.py --generate   # Print all commands (dry-run)
  python3 run_all_experiments.py --execute    # Execute with vCPU budget management
"""

import argparse
import subprocess
import sys
import threading
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT = "phase3_unified.py"
RUNS = 30
VCPU_LIMIT = 32

# vCPU costs per instance type (physical vCPUs)
VCPU_COSTS = {
    "t3.micro": 2, "t3.2xlarge": 8,
    "m5.large": 2, "m5.4xlarge": 16,
    "c5.large": 2, "c5.4xlarge": 16,
    "t4g.micro": 2, "t4g.2xlarge": 8,
    "m7g.large": 2, "m7g.4xlarge": 16,
    "c7g.large": 2, "c7g.4xlarge": 16,
}

# Mapping for vertical strategy resolution (requested -> effective)
VERTICAL_TYPES = {
    "t3.micro": "t3.2xlarge",
    "m5.large": "m5.4xlarge",
    "c5.large": "c5.4xlarge",
    "t4g.micro": "t4g.2xlarge",
    "m7g.large": "m7g.4xlarge",
    "c7g.large": "c7g.4xlarge"
}

def get_vcpu_cost(exp):
    inst = exp["instance_type"]
    strat = exp["strategy"]
    num_parts = exp.get("num_parts", 10)
    
    if strat == "serial":
        return VCPU_COSTS.get(inst, 2)
    elif strat == "vertical":
        v_type = VERTICAL_TYPES.get(inst, inst)
        return VCPU_COSTS.get(v_type, 8)
    elif strat == "horizontal":
        # 10 parts x vCPUs per part instance
        return VCPU_COSTS.get(inst, 2) * num_parts
    return 2

class VCPUBudget:
    def __init__(self, limit):
        self.limit = limit
        self.used = 0
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)

    def acquire(self, cost):
        with self.cv:
            while self.used + cost > self.limit:
                self.cv.wait()
            self.used += cost
            print(f"DEBUG: Budget acquired {cost} vCPUs. Used: {self.used}/{self.limit}")

    def release(self, cost):
        with self.cv:
            self.used -= cost
            print(f"DEBUG: Budget released {cost} vCPUs. Used: {self.used}/{self.limit}")
            self.cv.notify_all()

# ============================================================================
# EXPERIMENT MATRIX
# ============================================================================

# Melhoria 1: H.265 and VP9 across all x86 families (skipping T family)
MELHORIA_1 = []
for codec in ["libx265", "libvpx-vp9"]:
    for family_inst in ["m5.large", "c5.large"]:
        for strategy in ["serial", "horizontal", "vertical"]:
            MELHORIA_1.append({
                "instance_type": family_inst,
                "strategy": strategy,
                "codec": codec,
                "region": "us-east-1",
                "runs": RUNS,
                "label": f"M1: {family_inst} {strategy} {codec}",
            })

# Melhoria 2: Regional validation in sa-east-1 (H.264, skipping T family)
MELHORIA_2 = []
for family_inst in ["m5.large", "c5.large"]:
    for strategy in ["serial", "horizontal", "vertical"]:
        MELHORIA_2.append({
            "instance_type": family_inst,
            "strategy": strategy,
            "codec": "libx264",
            "region": "sa-east-1",
            "runs": RUNS,
            "label": f"M2: {family_inst} {strategy} sa-east-1",
        })

# Melhoria 3: ARM Graviton instances (H.264/H.265/VP9, skipping T family)
MELHORIA_3 = []
for family_inst in ["m7g.large", "c7g.large"]:
    for strategy in ["serial", "horizontal", "vertical"]:
        for codec in ["libx264", "libx265", "libvpx-vp9"]:
            MELHORIA_3.append({
                "instance_type": family_inst,
                "strategy": strategy,
                "codec": codec,
                "region": "us-east-1",
                "runs": RUNS,
                "label": f"M3: {family_inst} {strategy} {codec}",
            })

ALL_MELHORIAS = {
    1: ("H.265/VP9 na Fase 3 (x86)", MELHORIA_1),
    2: ("Valida\u00e7\u00e3o regional sa-east-1", MELHORIA_2),
    3: ("ARM Graviton 3", MELHORIA_3),
}

def build_command(exp):
    cmd = [
        "python3", SCRIPT,
        "--instance-type", exp["instance_type"],
        "--strategy", exp["strategy"],
        "--codec", exp["codec"],
        "--region", exp["region"],
        "--runs", str(exp["runs"]),
    ]
    return cmd

def run_single_experiment(exp, budget, is_dry_run):
    cost = get_vcpu_cost(exp)
    budget.acquire(cost)
    try:
        cmd = build_command(exp)
        if is_dry_run: cmd.append("--dry-run")
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] RUNNING: {exp['label']} (Cost: {cost} vCPUs)")
        
        # We use check=False to continue even if one fails
        result = subprocess.run(cmd, cwd=".", capture_output=False)
        
        status = "COMPLETED" if result.returncode == 0 else f"FAILED (code {result.returncode})"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {status}: {exp['label']}")
    finally:
        budget.release(cost)

def main():
    parser = argparse.ArgumentParser(description="Parallel Budget-Aware Orchestrator")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--melhoria", type=int, choices=[1, 2, 3])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.melhoria:
        desc, experiments = ALL_MELHORIAS[args.melhoria]
        selected = [(args.melhoria, desc, experiments)]
    else:
        selected = [(num, desc, exps) for num, (desc, exps) in ALL_MELHORIAS.items()]

    budget = VCPUBudget(VCPU_LIMIT)

    for num, desc, experiments in selected:
        print(f"\n{'#' * 80}")
        print(f"# STARTING MELHORIA {num}: {desc}")
        print(f"#{'#' * 78}\n")

        if args.execute:
            # We use a ThreadPool to handle the scheduling logic, 
            # but the actual concurrency is limited by the VCPUBudget.
            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = [executor.submit(run_single_experiment, exp, budget, args.dry_run) 
                           for exp in experiments]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"ERROR in experiment thread: {e}")
        else:
            for exp in experiments:
                print(f"  - {exp['label']} (Estimated cost: {get_vcpu_cost(exp)} vCPUs)")

if __name__ == "__main__":
    main()
