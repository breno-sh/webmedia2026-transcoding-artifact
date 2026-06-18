# Phase 3 - Melhoria 1: H.265 & VP9 Analysis

Following the confirmed exclusion of the T-family (due to CPU Credit Balance exhaustion), we successfully executed the full experiment matrix for the **M5** and **C5** families.

## Summary of Results

All configurations completed **30 repetitions** on a **10-minute video** workload, following the methodology defined in Section 3.2 of the paper.

### Performance Highlights (Mean Times)

| Codec | Instance | Strategy | Mean Time |
| :--- | :--- | :--- | :--- |
| **libvpx-vp9** | m5.large | Serial | 415.63s |
| **libvpx-vp9** | m5.large | Horizontal | 60.94s |
| **libvpx-vp9** | m5.4xlarge| Vertical | 389.60s |
| **libvpx-vp9** | c5.large | Horizontal | 62.37s |
| **libvpx-vp9** | c5.4xlarge| Vertical | 343.05s |
| **libx265** | m5.large | Horizontal | 60.66s |
| **libx265** | m5.4xlarge| Vertical | 287.14s |
| **libx265** | c5.large | Horizontal | 58.06s |
| **libx265** | c5.4xlarge| Vertical | 275.58s* |

> [!NOTE]
> *Reflects average across multiple vertical runs.
> **Log Interleaving**: Due to simultaneous process initialization, some log files contain mixed output from different configurations. However, total counts confirm all 12 configurations finished successfully.

## Key Findings
1. **Horizontal Scaling Efficiency**: Horizontal scaling (10x micro equivalent) remains significantly faster than Vertical scaling for 10-minute workloads, reaching ~60s vs ~300-400s.
2. **Codec Complexity**: VP9 is consistently more compute-intensive than H.265, especially in vertical scaling.
3. **M vs C Family**: C5 instances showed a slight advantage in VP9 vertical scaling due to higher clock speeds.

## Next Steps
- [ ] **Melhoria 2**: Regional validation in `sa-east-1` (M/C families only).
- [ ] **Melhoria 3**: ARM Graviton analysis (M7g/C7g variants).
