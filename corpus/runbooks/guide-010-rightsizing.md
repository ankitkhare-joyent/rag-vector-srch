---
id: GUIDE-010
title: Rightsizing EC2 instances
doc_type: guide
team: finops
services: [all]
updated: 2026-08-02
---
# Rightsizing EC2 instances

Rightsizing means matching instance size to actual usage. It is the cheapest cost win we have, and the FinOps team reviews it monthly with each team.

## Thresholds we use

Look at 14 days of CloudWatch metrics (or 30 days for monthly-cycle workloads):

| Signal | Action |
|---|---|
| p95 CPU below 20% and p95 memory below 40% | Downsize one size (for example `m6i.4xlarge` to `m6i.2xlarge`) |
| p95 CPU below 10% for 14 days | Candidate for downsizing two sizes or switching to a burstable `t` type |
| p95 CPU above 80% or memory above 85% | Upsize or scale out |
| Memory-bound with low CPU | Switch family from `m` to `r` |
| CPU-bound with low memory | Switch family from `m` to `c` |

Memory metrics require the CloudWatch agent; without them, never downsize on CPU alone.

## Tools

- **AWS Compute Optimizer** gives per-instance recommendations with a performance risk score. Treat it as input, not truth: it does not know about batch peaks at month end.
- The EC2 inventory lakehouse joins instance types with utilization so you can rank the biggest savings per team.

## What not to rightsize

- Instances in Auto Scaling groups: tune the scaling policy instead.
- `kafka-broker` and `opensearch-data`: their size is driven by storage and network throughput, not CPU.
- Anything with an active On-Demand Capacity Reservation, until the reservation is changed.

## Process

Each change gets a ticket, is applied in staging first, and is monitored for one week. Changing the instance type requires a stop and start, so schedule it in the service's maintenance window.
