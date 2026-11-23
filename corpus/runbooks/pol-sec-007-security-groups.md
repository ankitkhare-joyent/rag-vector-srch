---
id: POL-SEC-007
title: Security group rules for EC2
doc_type: policy
team: security
services: [all]
updated: 2026-02-18
---
# POL-SEC-007: Security group rules for EC2

## Rules

1. No security group may allow inbound traffic from `0.0.0.0/0` or `::/0` on any port except 80 and 443, and only on load balancers or the approved public services (`fulfillment-edge`, `bastion`).
2. SSH (port 22) and RDP (port 3389) must never be open to the internet. Interactive access goes through AWS Systems Manager Session Manager (RB-008). The `bastion` hosts are being retired; their port 22 is restricted to the corporate VPN CIDR `10.200.0.0/16`.
3. Reference other security groups instead of CIDR ranges for traffic inside a VPC (for example, `checkout-api` allows 8080 only from the ALB security group).
4. Every rule needs a description saying why it exists, and every security group needs the `Team` tag.
5. Egress to `0.0.0.0/0` is allowed on 443 only. Other egress goes through the egress proxy.

## Detection

AWS Config rules `restricted-ssh` and `vpc-sg-open-only-to-authorized-ports` run continuously. Violations page the security on-call within 15 minutes. GuardDuty findings of type `Recon:EC2/PortProbeUnprotectedPort` are treated as severity 2.

## Remediation

Security automatically revokes rules that open 22 or 3389 to the internet within 1 hour, and notifies the team owning the security group. Opening it again without an exception counts as a security incident.
