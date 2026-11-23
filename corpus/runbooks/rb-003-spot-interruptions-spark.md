---
id: RB-003
title: Spot interruptions on spark-batch and ci-runner
doc_type: runbook
team: data
services: [spark-batch, ci-runner]
updated: 2026-06-20
---
# Spot interruptions on spark-batch and ci-runner

About 70% of `spark-batch` capacity and 80% of `ci-runner` capacity runs on Spot. Spot instances can be reclaimed by AWS with a **two-minute interruption notice**. This is expected, not an incident, unless job SLAs are missed.

## How we receive the notice

- The instance metadata endpoint `/latest/meta-data/spot/instance-action` returns the action and time once a notice is issued (IMDSv2 token required, see POL-SEC-004).
- EventBridge emits `EC2 Spot Instance Interruption Warning`. Our rule forwards it to the `spot-events` SNS topic and to Datadog.
- Auto Scaling groups have **Capacity Rebalancing** enabled, so the group launches a replacement as soon as AWS sends a rebalance recommendation, which usually arrives before the two-minute notice.

## Spark behaviour

Spark 4 executors on our clusters run with graceful decommissioning (`spark.decommission.enabled=true` and `spark.storage.decommission.shuffleBlocks.enabled=true`). On notice, the executor migrates shuffle and cached RDD blocks to surviving executors, so stages do not restart from scratch. The driver always runs on On-Demand capacity; never schedule a driver on Spot.

## When interruptions become a problem

If more than 30% of the Spot fleet is interrupted within one hour, or a nightly job misses its 06:00 UTC SLA twice in a week:

1. Check the interruption frequency per instance type in the Spot placement score and the Spot Instance Advisor.
2. Add more instance types to the mixed-instances policy. We require at least **six** instance types across at least two families (for example `c7g.4xlarge`, `c6g.4xlarge`, `m7g.4xlarge`, `r7g.4xlarge`, `c7gd.4xlarge`, `m6g.4xlarge`). Diversification is the single most effective fix.
3. Use the `price-capacity-optimized` allocation strategy, never `lowest-price`.
4. As a last resort, raise `OnDemandBaseCapacity` temporarily and tell the data team in #data-platform.

## CI runners

CI jobs are retried automatically once on interruption. If a job is interrupted twice, the runner label `spot-fallback` routes the retry to On-Demand runners.
