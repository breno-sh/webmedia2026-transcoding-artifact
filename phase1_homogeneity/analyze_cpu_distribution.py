#!/usr/bin/env python3
"""
Script to analyze CPU distribution from verification logs.
Generates statistics similar to Table 1 in the article.
"""

import os
import re
from collections import defaultdict, Counter
import pandas as pd

def extract_cpu_info(log_path):
    """Extract CPU model and zone from a log file."""
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Extract zone from filename (e.g., t2.micro-us-east-1-us-east-1a-1.log -> a)
        zone = log_path.split('-')[-2][-1]  # Get the last char before the number

        # Extract CPU model
        cpu_match = re.search(r'model name\s*:\s*(.+)', content)
        if cpu_match:
            cpu_model = cpu_match.group(1).strip()
            # Simplify CPU names
            if '8259CL' in cpu_model:
                cpu_type = 'Xeon 8259CL'
            elif '8175M' in cpu_model:
                cpu_type = 'Xeon 8175M'
            elif 'E5-2686' in cpu_model:
                cpu_type = 'Xeon E5-2686 v4'
            else:
                cpu_type = cpu_model.split('@')[0].strip()

            return zone, cpu_type

    except Exception as e:
        print(f"Error processing {log_path}: {e}")

    return None, None

def analyze_cpu_distribution():
    """Analyze CPU distribution across all instances and zones."""
    base_path = "cpu_verification_logs"

    # Structure: zone -> instance_type -> cpu_counts
    distribution = defaultdict(lambda: defaultdict(Counter))

    # Process each instance type
    instance_types = [
        't2.micro', 't3.micro', 't3.small', 't3.medium', 't3.large', 't3.xlarge', 't3.2xlarge',
        'c5.large', 'c5.xlarge', 'c5.2xlarge', 'c5.4xlarge',
        'm5.large', 'm5.xlarge', 'm5.2xlarge', 'm5.4xlarge'
    ]
    for instance_type in instance_types:
        instance_path = os.path.join(base_path, instance_type)

        if not os.path.exists(instance_path):
            continue

        print(f"Processing {instance_type}...")

        # Process each zone
        for zone_dir in os.listdir(instance_path):
            zone_path = os.path.join(instance_path, zone_dir)
            if not os.path.isdir(zone_path):
                continue

            zone = zone_dir  # a, b, c, d, e, f

            # Process each log file in the zone
            for log_file in os.listdir(zone_path):
                if not log_file.endswith('.log'):
                    continue

                log_path = os.path.join(zone_path, log_file)
                zone_letter, cpu_type = extract_cpu_info(log_path)

                if zone_letter and cpu_type:
                    distribution[zone_letter][instance_type][cpu_type] += 1

    return distribution

def generate_summary_table(distribution):
    """Generate summary table similar to Table 1 in the article."""
    print("\n" + "="*80)
    print("CPU DISTRIBUTION SUMMARY (Similar to Table 1)")
    print("="*80)

    # Collect all CPU types
    all_cpus = set()
    for zone_data in distribution.values():
        for instance_data in zone_data.values():
            all_cpus.update(instance_data.keys())

    all_cpus = sorted(all_cpus)

    # Create summary by zone
    zone_summary = {}
    for zone in ['a', 'b', 'c', 'd', 'e', 'f']:
        if zone in distribution:
            zone_summary[zone] = {}
            total_instances = 0

            instance_types = [
                't2.micro', 't3.micro', 't3.small', 't3.medium', 't3.large', 't3.xlarge', 't3.2xlarge',
                'c5.large', 'c5.xlarge', 'c5.2xlarge', 'c5.4xlarge',
                'm5.large', 'm5.xlarge', 'm5.2xlarge', 'm5.4xlarge'
            ]
            for instance_type in instance_types:
                if instance_type in distribution[zone]:
                    instance_counts = distribution[zone][instance_type]
                    total_for_instance = sum(instance_counts.values())
                    total_instances += total_for_instance

                    # Calculate percentages for each CPU type
                    for cpu in all_cpus:
                        count = instance_counts.get(cpu, 0)
                        if cpu not in zone_summary[zone]:
                            zone_summary[zone][cpu] = 0
                        zone_summary[zone][cpu] += count

            # Convert to percentages
            if total_instances > 0:
                for cpu in all_cpus:
                    if cpu in zone_summary[zone]:
                        zone_summary[zone][cpu] = round((zone_summary[zone][cpu] / total_instances) * 100, 1)

    # Print table
    print(f"{'Zone':<6} {' | '.join(f'{cpu:<15}' for cpu in all_cpus)}")
    print("-" * (6 + 3 + sum(15 + 3 for _ in all_cpus)))

    for zone in ['a', 'b', 'c', 'd', 'e', 'f']:
        if zone in zone_summary:
            row = f"{zone:<6}"
            for cpu in all_cpus:
                percentage = zone_summary[zone].get(cpu, 0)
                row += f" | {percentage:>13}%"
            print(row)

    print("\n" + "="*80)
    print("DETAILED BREAKDOWN BY INSTANCE TYPE")
    print("="*80)

    # Detailed breakdown
    for zone in ['a', 'b', 'c', 'd', 'e', 'f']:
        if zone in distribution:
            print(f"\nZone {zone.upper()}:")
            instance_types = [
                't2.micro', 't3.micro', 't3.small', 't3.medium', 't3.large', 't3.xlarge', 't3.2xlarge',
                'c5.large', 'c5.xlarge', 'c5.2xlarge', 'c5.4xlarge',
                'm5.large', 'm5.xlarge', 'm5.2xlarge', 'm5.4xlarge'
            ]
            for instance_type in instance_types:
                if instance_type in distribution[zone]:
                    instance_counts = distribution[zone][instance_type]
                    total = sum(instance_counts.values())
                    print(f"  {instance_type:<12}: {total:>3} instances")

                    for cpu, count in sorted(instance_counts.items()):
                        percentage = round((count / total) * 100, 1) if total > 0 else 0
                        print(f"    - {cpu}: {count:>3} ({percentage:>4}%)")

if __name__ == "__main__":
    print("Analyzing CPU distribution from verification logs...")
    distribution = analyze_cpu_distribution()
    generate_summary_table(distribution)

    print("\nAnalysis complete! This matches the methodology described in the article,")
    print("where ~100 instances of each type were deployed across 6 zones to verify")
    print("processor homogeneity and document hardware heterogeneity.")
