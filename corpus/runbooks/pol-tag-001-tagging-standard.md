---
id: POL-TAG-001
title: Resource tagging standard
doc_type: policy
team: finops
services: [all]
updated: 2026-03-30
---
# POL-TAG-001: Resource tagging standard

Tags drive cost allocation, ownership lookups during incidents, and automation. Every EC2 instance, EBS volume and snapshot must carry the required tags below.

## Required tags

| Key | Example | Rules |
|---|---|---|
| `Name` | `checkout-api-prd-a` | Lowercase, service name plus environment |
| `Environment` | `prd` | One of `prd`, `stg`, `dev`, `sandbox` |
| `Team` | `payments` | Must match a team in the on-call directory |
| `Service` | `checkout-api` | Must match the service catalog |
| `CostCenter` | `cc-4821` | Four digits after `cc-`; finance maps it to a budget |

Optional but encouraged: `ManagedBy` (`terraform`, `eksctl`, `manual`), `DataClassification` (`public`, `internal`, `confidential`).

Auto Scaling groups must propagate tags to instances at launch (`PropagateAtLaunch=true`). EKS managed node groups inherit tags through the launch template.

## Enforcement and reporting

- Tag policies in AWS Organizations enforce the allowed values for `Environment`.
- The FinOps team publishes a weekly **untagged resources report** every Monday, built from the EC2 inventory lakehouse. Around 6% of instances are currently missing `CostCenter`, mostly from manually launched instances.
- Untagged spend is charged to the owning account's team budget at a 10% penalty rate from Q3 2026.
- Instances missing `Team` and `Service` for more than 14 days are flagged to the account owner and may be stopped.

## How to fix missing tags

```
aws ec2 create-tags --resources i-... vol-... --tags Key=CostCenter,Value=cc-4821
```
For Terraform-managed resources, set `default_tags` in the AWS provider block so every resource gets the tags automatically. Do not tag by hand resources that Terraform owns; the next apply will drift.
