---
id: RB-021
title: AWS scheduled events and instance retirement
doc_type: runbook
team: platform
services: [all]
updated: 2026-07-09
---
# AWS scheduled events and instance retirement

AWS schedules events on instances when the underlying host needs maintenance or has degraded. They appear in `describe-instance-status` under `Events` and in the AWS Health Dashboard, usually with **two weeks' notice**.

## Event types

| Event code | Meaning | What to do |
|---|---|---|
| `instance-retirement` | Host has degraded; the instance will be stopped or terminated on the date | Stop and start before the date (EBS-backed), or replace (instance store) |
| `system-reboot` | Host reboot for maintenance | Optionally reboot yourself earlier in your maintenance window |
| `instance-reboot` | Instance reboot needed | Reboot in your window |
| `system-maintenance` | Network or power maintenance, may cause brief loss of reachability | Usually no action |
| `instance-stop` | Instance will be stopped | Stop and start earlier to move host |

## Our automation

- An EventBridge rule on `AWS Health` events opens a ticket for the team in the instance's `Team` tag, 14 days ahead, and reminds again 3 days ahead.
- Instances in Auto Scaling groups are replaced automatically by the `scheduled-event-drainer` Lambda 48 hours before the event.

## Instance-store instances

For `kafka-broker` (`i4i`) and `opensearch-data` on `i4g`, an `instance-retirement` means data on the instance store will be lost. Follow RB-012 for brokers; for OpenSearch, exclude the node from allocation (`cluster.routing.allocation.exclude._name`) and wait for shards to move before stopping.

## Unscheduled failures

If an instance fails without warning, that is a status check failure, not a scheduled event; see RB-001.
