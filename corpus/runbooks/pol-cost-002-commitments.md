---
id: POL-COST-002
title: Savings Plans and Reserved Instances
doc_type: policy
team: finops
services: [all]
updated: 2026-08-19
---
# POL-COST-002: Savings Plans and Reserved Instances

Commitments trade flexibility for a discount on steady usage. Only FinOps purchases them; teams request coverage through the FinOps intake form.

## Targets

- **Coverage target: 70%** of steady-state On-Demand compute spend under commitments. Spot, burst and short-lived workloads are excluded from the target.
- **Utilization target: above 95%** of purchased commitments used each month.
- Mix: **Compute Savings Plans** first (apply across families, regions, Graviton and x86, Fargate and Lambda, up to about 66% off); **EC2 Instance Savings Plans** for stable families such as `r6g`/`r7g` on `opensearch-data` (up to about 72% off but tied to one family in one region); Reserved Instances only for RDS and ElastiCache.
- Terms: 1-year no-upfront by default; 3-year only for platforms with a committed multi-year roadmap (`kafka-broker`, `opensearch-data`).

## Rules

1. Do not buy commitments for workloads planned for decommission or migration within the term (for example the old `m5` fleet before RB-018).
2. Graviton migrations (GUIDE-009) and rightsizing (GUIDE-010) happen before buying, not after, so we do not commit to waste.
3. Savings Plans give a discount but do not reserve capacity; use On-Demand Capacity Reservations for that (RB-004).
4. Changing a large fleet's instance family requires a FinOps check that no EC2 Instance Savings Plan would become unused.

## Reporting

FinOps publishes coverage and utilization monthly per team, using Cost Explorer and the EC2 inventory lakehouse.
