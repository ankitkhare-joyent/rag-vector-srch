---
id: PM-2026-03
title: "Postmortem: checkout-api latency spike after AMI rollout"
doc_type: postmortem
team: payments
services: [checkout-api]
updated: 2026-03-19
incident_date: 2026-03-12
severity: 2
---
# Postmortem PM-2026-03: checkout-api latency spike after AMI rollout

**Date:** 2026-03-12, 14:05 to 15:20 UTC (75 minutes). **Severity:** 2. **Impact:** p99 checkout latency rose from 280 ms to 2.4 s in `us-east-1`; about 3% of checkouts timed out.

## Summary

The monthly golden AMI (RB-017) was rolled out to the `checkout-api-prd-asg` Auto Scaling group with an instance refresh at 50% minimum healthy percentage. The new AMI shipped a kernel with a changed default for transparent huge pages, which caused long JVM garbage-collection pauses under load. Because the instance refresh replaced half of the fleet at once, the healthy capacity was too small to absorb traffic.

## Timeline

- 13:40 instance refresh started on `checkout-api-prd-asg`.
- 14:05 p99 latency alert fired; payments on-call paged.
- 14:30 correlation with the instance refresh found from the ASG activity history.
- 14:38 instance refresh cancelled; rollback started to the previous launch template version.
- 15:20 latency back to normal.

## What went well

- Launch template versions made rollback a single command.

## What went wrong

- The AMI was not load-tested for JVM services before production.
- Instance refresh used `MinHealthyPercentage=50`, too aggressive for a latency-sensitive service.

## Action items

1. Instance refresh for `checkout-api` now uses `MinHealthyPercentage=90` and checkpoints at 10%, 50% (done).
2. AMI pipeline runs a 30-minute JVM load test before promotion (done).
3. Pin `transparent_hugepage=madvise` in the AMI build (done).
