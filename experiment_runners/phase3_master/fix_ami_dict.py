import glob

files = glob.glob("artifacts2/phase3_scaling/*_opt.py")
for f in files:
    with open(f, "r") as file:
        content = file.read()
    
    content = content.replace('CUSTOM_AMI', '"ami-0a0e5d9c7acc336f1"')
    
    with open(f, "w") as file:
        file.write(content)
print("Purged CUSTOM_AMI.")
