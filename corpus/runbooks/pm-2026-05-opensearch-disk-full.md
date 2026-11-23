---
id: PM-2026-05
title: "Postmortem: opensearch-data cluster red after disks filled"
doc_type: postmortem
team: search
services: [opensearch-data, search-indexer]
updated: 2026-05-22
incident_date: 2026-05-17
severity: 1
---
# Postmortem PM-2026-05: opensearch-data cluster red after disks filled

**Date:** 2026-05-17, 02:10 to 06:45 UTC. **Severity:** 1. **Impact:** product search returned errors or stale results for 4.5 hours in `eu-central-1`.

## Summary

The index state management (ISM) policy that deletes log-style indices older than 30 days stopped running after an OpenSearch upgrade renamed a policy field. Old indices accumulated for three weeks. On 2026-05-17 the data nodes' EBS volumes crossed the 95% flood-stage watermark, OpenSearch set every index to read-only, and indexing from `search-indexer` failed. Two nodes then ran completely out of disk and their shards went unassigned, turning the cluster red.

## Timeline

- 02:10 `DiskUsedPercent > 85` had been firing since 23:00 but routed to a low-priority channel.
- 02:40 cluster status red; search on-call paged.
- 03:30 decision to grow EBS volumes online (RB-002) rather than delete indices under pressure.
- 04:15 volumes grown 40%; read-only block cleared with `index.blocks.read_only_allow_delete: null`.
- 06:45 all shards assigned, green.

## Root cause

The ISM policy silently failed after the upgrade and nothing alerted on ISM failures. The disk alert existed but went to a channel nobody watched at night.

## Action items

1. Alert on ISM policy execution failures (done).
2. Route `DiskUsedPercent > 85` on `opensearch-data` and `kafka-broker` to the paging rotation (done).
3. Add a 20% headroom target to capacity reviews for data volumes (in progress).
4. Document the safe order of operations in RB-002 (done).
