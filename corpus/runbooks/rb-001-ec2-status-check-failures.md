---
id: RB-001
title: EC2 status check failures
doc_type: runbook
team: platform
services: [all]
updated: 2026-08-14
---
# EC2 status check failures

Every EC2 instance has two automated status checks, evaluated every minute. The console shows them as `2/2 checks passed`. When one fails, the instance is still billed but may not be serving traffic.

## Which check failed?

**System status check** (`StatusCheckFailed_System`) means AWS has a problem with the hardware, power, or network of the underlying host. You cannot fix the host. The fix is to move the instance to new hardware by **stopping and starting** it (a reboot does not move it). Instances with instance-store volumes (for example `i4i` and `i4g` families) lose their local data on stop, so follow the broker or data-node runbook instead of stopping blindly.

**Instance status check** (`StatusCheckFailed_Instance`) means the problem is inside your instance: a kernel panic, a full root disk, exhausted memory, a broken network configuration, or an incompatible kernel after patching. Stopping and starting rarely helps on its own.

**Attached EBS status check** (`StatusCheckFailed_AttachedEBS`) means one of the attached EBS volumes is impaired. Check the volume in the EBS console and see RB-025 for restoring from snapshot.

## Triage steps

1. Find the failing check: `aws ec2 describe-instance-status --instance-ids i-... --include-all-instances`.
2. Pull the serial console output: `aws ec2 get-console-output --instance-id i-... --latest`. Look for `Kernel panic`, `Out of memory: Killed process`, or `No space left on device`.
3. If the instance belongs to an Auto Scaling group (tag `aws:autoscaling:groupName`), do not repair it. Mark it unhealthy and let the group replace it: `aws autoscaling set-instance-health --instance-id i-... --health-status Unhealthy`.
4. For standalone instances, take an EBS snapshot of the root volume before any change.
5. System check failed: stop, then start. Instance check failed: use EC2 Serial Console (via SSM, see RB-008) to fix the root cause.

## Automatic recovery

All standalone production instances must have the CloudWatch alarm `StatusCheckFailed_System >= 1 for 2 datapoints` with the `ec2:recover` action. Simplified automatic recovery is on by default for supported instance types, but the explicit alarm also pages the owning team. Instance-store families do not support recovery.

## Escalation

If more than five instances in one Availability Zone fail system checks within 15 minutes, treat it as an AWS event: open a severity 2 incident (see GUIDE-024) and check the AWS Health Dashboard before replacing instances one by one.
