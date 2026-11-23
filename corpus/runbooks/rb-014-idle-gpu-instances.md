---
id: RB-014
title: Idle GPU and notebook instances
doc_type: runbook
team: ml
services: [ml-training, jupyter]
updated: 2026-07-30
---
# Idle GPU and notebook instances

GPU instances are our most expensive resources: one `p4d.24xlarge` costs more per hour than 100 `m7i.large` instances. The ML team's `ml-training` (`g5.2xlarge`, `g5.12xlarge`, `p4d.24xlarge`) and `jupyter` (`t3.xlarge`, `m6i.xlarge`) instances are stopped when idle.

## Auto-stop rules

| Fleet | Idle definition | Action |
|---|---|---|
| `ml-training` | GPU utilization below 5% for **2 hours** | Stop the instance, notify the owner in #ml-infra |
| `jupyter` | No kernel activity for 3 hours, or after 21:00 local time | Stop the instance |
| Any GPU instance | Running more than 72 hours without the tag `LongRun=true` | Notify owner, stop after 24 more hours |

The auto-stop Lambda reads `DCGM_FI_DEV_GPU_UTIL` from CloudWatch. Instances without the CloudWatch agent's NVIDIA metrics cannot be evaluated and are reported as non-compliant.

## Before stopping manually

- Training jobs must checkpoint to S3 at least every 30 minutes, so a stop loses at most 30 minutes of work.
- EBS data volumes survive a stop; instance store does not (`p4d` has NVMe instance store used as scratch only).

## Restarting

Starting a stopped GPU instance can fail with `InsufficientInstanceCapacity`, especially `p4d.24xlarge`. See RB-004; for runs longer than a day, book a Capacity Block instead of keeping instances running "just in case".

## Exemptions

Set `LongRun=true` plus `LongRunTicket=<ticket>` for training runs expected to exceed 72 hours. The tag is removed automatically after 14 days.
