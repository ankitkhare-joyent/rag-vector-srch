---
id: RB-025
title: Restoring an EBS volume from a snapshot
doc_type: runbook
team: platform
services: [all]
updated: 2026-06-29
---
# Restoring an EBS volume from a snapshot

Use this when a volume is impaired, data was deleted or corrupted, or you need an older copy of data for investigation.

## Snapshot policy recap

Data Lifecycle Manager takes daily snapshots of every volume tagged `Backup=daily` at 03:00 UTC and keeps 14 of them; weekly snapshots are kept for 8 weeks. Snapshots are incremental and stored in S3 by AWS. Root volumes are not backed up because instances are rebuilt from the golden AMI (RB-017).

## Restore steps

1. Find the snapshot: `aws ec2 describe-snapshots --owner-ids self --filters Name=tag:Service,Values=<service>`.
2. Create a volume in the **same Availability Zone** as the target instance; volumes cannot attach across AZs:
   ```
   aws ec2 create-volume --snapshot-id snap-... --availability-zone eu-central-1a --volume-type gp3 --tag-specifications ...
   ```
3. **Initialization**: a volume created from a snapshot loads blocks lazily from S3, so first reads are slow. For databases, enable Fast Snapshot Restore on the snapshot beforehand (costs extra per hour per AZ), or pre-warm by reading every block with `fio`.
4. Attach the volume, mount it read-only first, check the data, then switch the application over.
5. Keep the old volume, detached and tagged `RetainUntil`, for 7 days in case you need to compare.

## Cross-region and cross-account

Copy the snapshot first (`aws ec2 copy-snapshot`). Encrypted snapshots need the KMS key shared with the target account.

## Restoring a whole instance

Create an AMI from the root volume snapshot only for forensic work. For normal recovery, launch a fresh instance from the golden AMI and attach the restored data volume.
