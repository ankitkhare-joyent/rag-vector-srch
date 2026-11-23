---
id: RB-020
title: VcpuLimitExceeded and EC2 service quotas
doc_type: runbook
team: platform
services: [all]
updated: 2026-06-11
---
# VcpuLimitExceeded and EC2 service quotas

EC2 On-Demand and Spot limits are counted in **vCPUs per instance family group per region per account**, not in instances. Launching beyond the limit fails with:

`VcpuLimitExceeded: You have requested more vCPU capacity than your current vCPU limit of 1152 allows for the instance bucket that the specified instance type belongs to.`

This is a quota problem in your account, unlike `InsufficientInstanceCapacity`, which is an AWS capacity shortage (RB-004).

## Relevant quota codes

| Quota | Code |
|---|---|
| Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances | `L-1216C47A` |
| Running On-Demand G and VT instances | `L-DB2E81BA` |
| Running On-Demand P instances | `L-417A185B` |
| All Standard (A, C, D, H, I, M, R, T, Z) Spot Instance Requests | `L-34B43A08` |

## Check current usage

```
aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A
```
CloudWatch publishes usage in the `AWS/Usage` namespace; we alarm at 80% of each quota.

## Request an increase

```
aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-1216C47A --desired-value 2048
```
Standard increases are often approved within an hour; large jumps (more than double) or GPU quotas (`L-DB2E81BA`, `L-417A185B`) can take days and may need a support case with a business justification. Plan ahead for launches (GUIDE-019) and peak events.

## Short-term workarounds

- Move part of the load to another instance family group with headroom (for example Spot quota is separate from On-Demand).
- Scale down idle fleets (RB-014) to free vCPUs.
