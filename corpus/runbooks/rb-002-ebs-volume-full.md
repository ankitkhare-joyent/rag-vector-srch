---
id: RB-002
title: EBS data volume running out of space
doc_type: runbook
team: platform
services: [opensearch-data, search-indexer, kafka-broker, ml-training]
updated: 2026-07-02
---
# EBS data volume running out of space

The alert `DiskUsedPercent > 85` fires from the CloudWatch agent metric `disk_used_percent` on the data mount (`/data`). At 95% the service is at risk: OpenSearch puts indices into read-only mode at the flood-stage watermark, and Kafka brokers crash when a log segment cannot be written.

## Immediate mitigation (under 15 minutes)

1. Confirm which mount is full: `df -h` and `du -xh --max-depth=1 /data | sort -h`.
2. Delete what is safe to delete: old heap dumps in `/data/dumps`, rotated logs older than 7 days, and orphaned temp files from failed jobs. Never delete Kafka log segments or OpenSearch shard directories by hand.
3. Grow the volume online. EBS volumes can be enlarged without downtime:
   ```
   aws ec2 modify-volume --volume-id vol-... --size <new GiB>
   aws ec2 describe-volumes-modifications --volume-id vol-...   # wait for "optimizing" or "completed"
   sudo growpart /dev/nvme1n1 1      # only if the filesystem sits on a partition
   sudo xfs_growfs /data             # XFS (our default)
   sudo resize2fs /dev/nvme1n1p1     # ext4
   ```
   Grow by at least 30% so the alert does not fire again next week.
4. A volume can only be modified once every 6 hours. If you already modified it today, mitigate by deleting data or moving shards instead.

## Root cause follow-up

Open a ticket for the owning team with the growth rate (GiB per day) from the `disk_used_percent` graph. For OpenSearch, check whether index lifecycle (ISM) policies stopped deleting old indices; this was the cause in PM-2026-05. For Kafka, check `retention.bytes` and `retention.ms` on the largest topics.

## Volume type

Data volumes use `gp3`. When growing a volume you may also raise throughput (up to 1,000 MiB/s) and IOPS (up to 16,000) in the same `modify-volume` call. Do not switch to `io2` without a cost review (POL-COST-002).
