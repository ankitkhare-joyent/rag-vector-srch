---
id: POL-SEC-004
title: IMDSv2 is mandatory on all EC2 instances
doc_type: policy
team: security
services: [all]
updated: 2026-04-09
---
# POL-SEC-004: IMDSv2 is mandatory on all EC2 instances

## Policy

Every EC2 instance in every account must require Instance Metadata Service version 2 (IMDSv2). In API terms the instance metadata options must be `HttpTokens=required`. IMDSv1 (`HttpTokens=optional`) is forbidden because a server-side request forgery (SSRF) bug in any application on the instance could otherwise read the instance role's temporary credentials from `http://169.254.169.254/latest/meta-data/iam/security-credentials/`.

## Required settings

| Setting | Value | Why |
|---|---|---|
| `HttpTokens` | `required` | Session token needed for every metadata call |
| `HttpPutResponseHopLimit` | `2` on EKS nodes and Docker hosts, `1` elsewhere | Containers add one network hop; with limit 1 pods cannot reach IMDS at all |
| `HttpEndpoint` | `enabled` | Disable only on instances that never need a role |
| `InstanceMetadataTags` | `enabled` | Lets software read instance tags without IAM calls |

Launch templates managed by Terraform set these values. The account-level default (`aws ec2 modify-instance-metadata-defaults --http-tokens required`) is enabled in every region as a backstop.

## Enforcement

- A Service Control Policy denies `ec2:RunInstances` when `ec2:MetadataHttpTokens` is not `required`.
- AWS Config rule `ec2-imdsv2-check` reports non-compliant instances daily to #sec-findings.
- Non-compliant instances found after 2026-05-01 are stopped by the security team after 7 days' notice to the owning team (tag `Team`).

## Fixing a non-compliant instance

```
aws ec2 modify-instance-metadata-options --instance-id i-... --http-tokens required --http-put-response-hop-limit 2
```
No reboot is needed. Before switching, check that the software on the instance uses an SDK version that supports IMDSv2 (all AWS SDKs released after 2020 do). Old scripts using `curl http://169.254.169.254/...` without first fetching a token with `PUT /latest/api/token` will break.

## Exceptions

Exceptions require a ticket in the SEC project approved by the security lead, and expire after 90 days.
