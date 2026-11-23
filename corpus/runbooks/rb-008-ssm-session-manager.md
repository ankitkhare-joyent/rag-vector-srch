---
id: RB-008
title: Getting a shell on an instance with SSM Session Manager
doc_type: runbook
team: platform
services: [all]
updated: 2026-07-21
---
# Getting a shell on an instance with SSM Session Manager

We do not use SSH keys for interactive access. Use AWS Systems Manager Session Manager, which needs no open inbound ports, logs every session to S3 and CloudWatch, and authenticates with your SSO role.

## Prerequisites

- The instance runs the SSM Agent (preinstalled on our golden AMIs, see RB-017).
- The instance profile includes the managed policy `AmazonSSMManagedInstanceCore`.
- The instance can reach the SSM endpoints, either through the VPC interface endpoints (`ssm`, `ssmmessages`, `ec2messages`) or the egress proxy.
- Locally: AWS CLI v2 and the Session Manager plugin.

## Start a session

```
aws sso login --profile prd-readonly
aws ssm start-session --target i-0abc123 --profile prd-operator
```
Port forwarding, for example to reach a database proxy on 5432:
```
aws ssm start-session --target i-0abc123 --document-name AWS-StartPortForwardingSession \
  --parameters portNumber=5432,localPortNumber=15432
```

## Instance shows as "not connected"

1. Check that the instance appears in `aws ssm describe-instance-information`. If not, the agent is not registering.
2. Most common causes: missing instance profile policy, no route to the SSM endpoints, or a stopped agent after a full root disk.
3. Use the EC2 Serial Console as a fallback for instances that cannot boot or register (needs the `ec2-serial-console` permission in the break-glass role).

## Break-glass access

The `prd-breakglass` SSO role allows Session Manager on every production instance. Using it pages the security on-call automatically and requires an incident ticket reference within 1 hour.
