---
id: RB-012
title: Replacing a Kafka broker on instance storage
doc_type: runbook
team: platform
services: [kafka-broker]
updated: 2026-05-15
---
# Replacing a Kafka broker on instance storage

Our self-managed Kafka brokers run on `i4i.2xlarge` instances with NVMe **instance store** for log segments. Instance store is ephemeral: data is lost when the instance is stopped, terminated, or the host fails. Durability comes from Kafka replication (replication factor 3, `min.insync.replicas=2`), not from the disk.

## When to replace

- The instance failed a system status check or has a scheduled retirement event (RB-021).
- An NVMe device shows I/O errors in `dmesg`.
- Never stop and start a broker to "move it to new hardware" as you would for EBS-backed instances; that wipes its data, which is fine only if you follow this runbook.

## Procedure

1. Confirm the cluster is healthy: no under-replicated partitions (`kafka-topics.sh --describe --under-replicated-partitions` returns nothing).
2. Stop the broker process cleanly with `systemctl stop kafka` so it hands over leadership.
3. Launch the replacement from the `kafka-broker` launch template **with the same `broker.id`** in the same AZ. Terraform module `kafka_broker` does this when you taint the old instance.
4. The new broker starts empty and re-replicates its partitions from the other replicas. On our cluster this takes 2 to 4 hours; throttle it with `leader.replication.throttled.rate` at 200 MB/s so client traffic is not affected.
5. Wait until under-replicated partitions are zero before touching another broker. Only one broker may be replaced at a time.
6. Run preferred leader election at the end.

## Do not

- Do not replace two brokers in the same AZ at once; with rack awareness, that could take two replicas of a partition offline.
- Do not copy log directories between hosts manually.
