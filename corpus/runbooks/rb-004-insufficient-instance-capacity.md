---
id: RB-004
title: InsufficientInstanceCapacity launch errors
doc_type: runbook
team: platform
services: [ml-training, eks-general, spark-batch]
updated: 2026-05-28
---
# InsufficientInstanceCapacity launch errors

`InsufficientInstanceCapacity` (ICE) means AWS does not currently have enough capacity of the requested instance type in that Availability Zone. It is not a quota problem: quotas fail with `VcpuLimitExceeded` instead (see RB-020). Retrying the same request in the same AZ often keeps failing for minutes to hours.

## What to do

1. Read the full error. It names the instance type and AZ, for example: `We currently do not have sufficient p4d.24xlarge capacity in the Availability Zone you requested (us-east-1a)`.
2. Retry in a different AZ. Our VPCs have subnets in every AZ listed for the region.
3. For Auto Scaling groups, make sure the group spans all AZs and uses a mixed-instances policy, so a single type shortage does not block scaling.
4. For GPU training (`g5`, `p4d`), larger types are the hardest to get. Ask the ML team whether the job can run on more `g5.12xlarge` nodes instead of one `p4d.24xlarge`.

## Guaranteeing capacity

- **On-Demand Capacity Reservations (ODCR)** guarantee capacity in one AZ, billed whether used or not. Use them for planned events (Black Friday for `checkout-api`) and create them at least 2 weeks ahead.
- **Capacity Blocks for ML** reserve GPU instances for a fixed future window (1 to 182 days). This is the preferred way to get `p4d` and `p5` capacity for training runs longer than a day.
- Savings Plans and Reserved Instances give a discount but do **not** guarantee capacity unless they are zonal RIs.

## Communication

If ICE blocks a production scale-out for more than 30 minutes, open a severity 2 incident and an AWS support case of severity "Production system down", quoting the instance type, AZ and request IDs.
