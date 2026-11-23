---
id: RB-013
title: CI runner queue backlog
doc_type: runbook
team: devex
services: [ci-runner]
updated: 2026-09-10
---
# CI runner queue backlog

`ci-runner` instances (`c7a.2xlarge` and `c7a.4xlarge`, mostly Spot) run CI jobs in `us-east-1` and `eu-central-1`. They scale on queue depth during office hours and scale to a floor of 2 at night and weekends.

## Symptoms

- Developers report jobs "queued" for more than 5 minutes.
- The metric `ci.queue.pending_jobs` is above 50 for 10 minutes, which pages devex on-call.

## Checks

1. Is the Auto Scaling group at its maximum? `aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names ci-runner-prd-asg`. If `DesiredCapacity == MaxSize`, raise `MaxSize` (hard limit 400 per region; above that, request a vCPU quota increase first, see RB-020).
2. Are launches failing? Check the group's activity history for `InsufficientInstanceCapacity` (RB-004) or `VcpuLimitExceeded` (RB-020).
3. Are many Spot instances being interrupted? See RB-003; the `spot-fallback` label sends retried jobs to On-Demand runners.
4. Are runners registered but idle? A broken runner AMI can boot without registering. Compare running instances to registered runners; if they differ, roll back the launch template to the previous version.

## Fixes

- Temporarily raise the minimum: `aws autoscaling set-desired-capacity --desired-capacity <n>`.
- Large monorepo builds can be pinned to `c7a.4xlarge` with the `large` runner label.
- Warm pools keep 10 stopped, pre-initialised runners per region so scale-out takes about 40 seconds instead of 3 minutes.
