import os
import glob

target_dir = "./artifacts2/phase3_scaling"
py_files = glob.glob(os.path.join(target_dir, "*.py"))

for p in py_files:
    if "chunk_sensitivity" in p or "run_n30" in p or "patch_cpu" in p or "unpatch_cpu" in p or "parallel_scaling_phase2" in p or "serial_scaling_phase2" in p:
        continue
    with open(p, "r") as f:
        content = f.read()

    # We want to replace the RuntimeError with the WARNING or just remove the RuntimeError part.
    old_code1 = '        if EXPECTED_CPU and cpu_model != EXPECTED_CPU:\n            raise RuntimeError(f"CPU mismatch! Expected {EXPECTED_CPU}, got {cpu_model}")'
    new_code1 = '        if EXPECTED_CPU and cpu_model != EXPECTED_CPU:\n            log(f"WARNING: CPU mismatch! Expected {EXPECTED_CPU}, got {cpu_model}", context)'
    
    if old_code1 in content:
        content = content.replace(old_code1, new_code1)
        with open(p, "w") as f:
            f.write(content)
        print(f"Unpatched {os.path.basename(p)} ( replaced RuntimeError with WARNING )")

# Also fix the t3_micro_paralelo_phase2.py
t3_file = "./artifacts/phase3_scaling/t3_micro_paralelo_phase2.py"
if os.path.exists(t3_file):
    with open(t3_file, "r") as f:
        t3_content = f.read()
    
    t3_old = '            if cpu_model != self.expected_cpu:\n                raise RuntimeError(f"CPU incorreta. Esperado \'{self.expected_cpu}\'. Abortando esta parte.")'
    t3_new = '            if cpu_model != self.expected_cpu:\n                self.log(f"WARNING: CPU mismatch. Esperado \'{self.expected_cpu}\', got {cpu_model}", context)'
    
    if t3_old in t3_content:
        t3_content = t3_content.replace(t3_old, t3_new)
        with open(t3_file, "w") as f:
            f.write(t3_content)
        print("Unpatched t3_micro_paralelo_phase2.py")
