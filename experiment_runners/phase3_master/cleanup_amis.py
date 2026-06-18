import boto3

REGION = "sa-east-1"
# AMIs to keep:
KEEP = {"ami-0ecbc0dab130caeda", "ami-0653a33fe2919af93"}

ec2 = boto3.client('ec2', region_name=REGION)

response = ec2.describe_images(Owners=['self'])
for image in response['Images']:
    ami_id = image['ImageId']
    if ami_id in KEEP:
        print(f"Keeping {ami_id}")
        continue
    
    print(f"Deregistering {ami_id}...")
    # Find snapshots
    snapshots = [
        bdm['Ebs']['SnapshotId'] 
        for bdm in image.get('BlockDeviceMappings', []) 
        if 'Ebs' in bdm and 'SnapshotId' in bdm['Ebs']
    ]
    
    ec2.deregister_image(ImageId=ami_id)
    print(f"  Deregistered {ami_id}")
    
    for snap in snapshots:
        print(f"  Deleting snapshot {snap}...")
        try:
            ec2.delete_snapshot(SnapshotId=snap)
            print(f"    Deleted {snap}")
        except Exception as e:
            print(f"    Error deleting {snap}: {e}")
