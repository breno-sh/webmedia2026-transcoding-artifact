import os
import glob

target_dir = "./artifacts2/phase3_scaling"
py_files = glob.glob(os.path.join(target_dir, "*.py"))

for p in py_files:
    if "chunk_sensitivity" in p or "run_n30" in p or "parallel_scaling_phase2" in p or "serial_scaling_phase2" in p:
        continue
    with open(p, "r") as f:
        content = f.read()
        
    old_code1 = '        if cpu_model != EXPECTED_CPU:\n            log(f"WARNING: CPU mismatch! Expected {EXPECTED_CPU}", context)'
    new_code1 = '        if EXPECTED_CPU and cpu_model != EXPECTED_CPU:\n            raise RuntimeError(f"CPU mismatch! Expected {EXPECTED_CPU}, got {cpu_model}")'
    
    if old_code1 in content:
        content = content.replace(old_code1, new_code1)
        with open(p, "w") as f:
            f.write(content)
        print(f"Patched {os.path.basename(p)} ( replaced WARNING with RuntimeError )")
        continue

    # For files that just log the CPU without any 'if' block
    old_code2 = '        log(f"CPU: {cpu_model}", context)'
    new_code2 = '        log(f"CPU: {cpu_model}", context)\n        if EXPECTED_CPU and cpu_model != EXPECTED_CPU:\n            raise RuntimeError(f"CPU mismatch! Expected {EXPECTED_CPU}, got {cpu_model}")'
    
    if old_code2 in content and 'raise RuntimeError(f"CPU mismatch!' not in content:
        content = content.replace(old_code2, new_code2)
        with open(p, "w") as f:
            f.write(content)
        print(f"Patched {os.path.basename(p)} ( inserted EXPECTED_CPU check )")

