---
id: RB-017
title: Golden AMI build and patching cadence
doc_type: runbook
team: platform
services: [all]
updated: 2026-04-24
---
# Golden AMI build and patching cadence

All production instances boot from a **golden AMI** built by the platform team with Packer. Images are rebuilt on the first Tuesday of every month, and out of cycle within 72 hours for critical CVEs (CVSS 9.0 or higher).

## What is in the golden AMI

- Amazon Linux 2023 base, latest security updates, hardened per CIS Level 1.
- SSM Agent, CloudWatch agent (with memory, disk and NVIDIA metrics), the Datadog agent.
- IMDSv2-only defaults (POL-SEC-004) and `transparent_hugepage=madvise` (from PM-2026-03).
- Variants: `al2023-base` (x86_64 and arm64), `al2023-eks-node`, `al2023-gpu` (NVIDIA driver and CUDA), and `win2022-base` for the remaining Windows fleet.

## Promotion pipeline

1. Build in the `devex` tooling account, both architectures.
2. Automated tests: boot, agent registration, CIS scan, 30-minute JVM load test.
3. Share to `stg` accounts; teams have 5 working days to roll out to staging.
4. Promote to `prd`; the SSM Parameter `/golden-ami/<variant>/latest` is updated.

## Maximum AMI age

A production instance must not run an AMI older than **30 days** (60 days for instance-store fleets such as `kafka-broker`, because each replacement re-replicates data). The weekly compliance report lists offenders by `Team` tag.

## Rolling out a new AMI

- Auto Scaling groups: update the launch template to the new SSM parameter version and start an instance refresh. Use `MinHealthyPercentage=90` for latency-sensitive services.
- EKS node groups: update the node group's AMI release version; nodes are drained and replaced one AZ at a time.
- Standalone instances: replace, do not patch in place, unless the owning team has an approved exception.

Roll back by pointing the launch template at the previous version; old AMIs are kept for 90 days.
