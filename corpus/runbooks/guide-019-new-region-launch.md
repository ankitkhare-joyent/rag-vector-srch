---
id: GUIDE-019
title: Launching a service in a new region (fulfillment-edge in ap-southeast-1)
doc_type: guide
team: logistics
services: [fulfillment-edge]
updated: 2026-04-20
---
# Launching a service in a new region

In April 2026 the logistics team launched `fulfillment-edge` in `ap-southeast-1` (Singapore), our first service there. These are the steps and lessons, kept as the checklist for the next region launch.

## Four weeks before

- **Service quotas**: new regions start with low default quotas. Request increases for "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances" (quota code `L-1216C47A`), Elastic IPs and Application Load Balancers. Quota requests can take several days (RB-020).
- **Networking**: VPC from the IPAM pool (CIDR `10.40.0.0/16` for ap-southeast-1), Transit Gateway attachment, VPC endpoints for SSM, S3 and ECR.
- **Golden AMI**: copy the AMIs to the new region and add the region to the Packer build.
- **Security**: GuardDuty, Config rules and the IMDSv2 account default enabled in the region before any workload.

## Launch week

- Start with On-Demand capacity only; add Spot after two weeks of stable traffic.
- `fulfillment-edge` uses `c7i.xlarge` and `c7i.2xlarge` behind a public ALB, so it is one of the services allowed public 443 ingress (POL-SEC-007).
- Load test from the region at 2x the expected peak.

## Lessons learned

- The vCPU quota increase took 6 days; request it earlier.
- We forgot to add the region to the tagging policy's enforced regions, so the first week's instances lacked `CostCenter`.
- Latency to the `eu-central-1` order database was 160 ms; read replicas in-region fixed it.
