---
id: RB-011
title: EKS worker node NotReady
doc_type: runbook
team: platform
services: [eks-general]
updated: 2026-08-28
---
# EKS worker node NotReady

The `eks-general` node group in cluster `prd-main` runs on `m6i` and `m7i` instances in an Auto Scaling group. A node reports `NotReady` when the kubelet stops posting status to the control plane for 40 seconds.

## Triage

1. `kubectl get nodes -o wide | grep NotReady` and note the instance ID from the provider ID.
2. `kubectl describe node <node>` and read the Conditions. `MemoryPressure`, `DiskPressure` and `PIDPressure` point at resource exhaustion inside the node.
3. Check the EC2 status checks for the instance (RB-001). A failed system check means the host is bad.
4. Open a session with SSM (RB-008) and check `systemctl status kubelet containerd` and `journalctl -u kubelet --since -30m`.

## Common causes

- **Disk pressure** from container images and logs on the root volume. Image garbage collection starts at 85% usage. Our node AMI uses a 100 GiB root volume; grow it in the launch template if this repeats.
- **IP address exhaustion**: pods stuck in `ContainerCreating` with `failed to assign an IP address` mean the subnet ran out of IPs. Prefix delegation is enabled on new node groups.
- **kubelet certificate expiry** after a node was stopped for weeks.
- **IMDS hop limit** set to 1, which breaks pods that need the node role (POL-SEC-004 requires 2 on EKS nodes).

## Fix

Nodes are cattle. Cordon and drain, then terminate and let the Auto Scaling group replace it:
```
kubectl cordon <node>
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=10m
aws autoscaling terminate-instance-in-auto-scaling-group --instance-id i-... --no-should-decrement-desired-capacity
```
Respect PodDisruptionBudgets; if a drain hangs, find the blocking PDB rather than forcing. If more than 3 nodes go NotReady at once, stop and look for a shared cause (AMI rollout, CNI version, AZ event) before replacing nodes.
