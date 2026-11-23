---
id: RB-018
title: Decommissioning the legacy-reporting Windows fleet
doc_type: runbook
team: finance
services: [legacy-reporting]
updated: 2026-03-31
---
# Decommissioning the legacy-reporting Windows fleet

The `legacy-reporting` service (finance team, `m5.large` and `m5.xlarge`, about 60% Windows Server) was replaced by dashboards on the Trino lakehouse. It was decommissioned in March 2026. This runbook records how, and is the template for future decommissions.

## Checklist

1. **Confirm no traffic** for 30 days: ALB request count is zero and no scheduled tasks ran. Owners sign off in the decommission ticket.
2. **Final backups**: take EBS snapshots of every data volume, tagged `RetainUntil=<date 90 days out>` and `DecommissionTicket=<id>`. Finance requires report archives for 7 years; those were exported to S3 Glacier Deep Archive, not kept as snapshots.
3. **Stop, then wait**: stop all instances and wait 14 days. Stopped instances cost only their EBS storage, and the wait catches forgotten dependencies.
4. **Terminate** after the 14 days, and delete the Auto Scaling groups, launch templates, target groups, DNS records and security groups.
5. **Licenses**: Windows license-included instances stop billing at termination; tell procurement to cancel any SQL Server licenses brought under BYOL.
6. **Clean up commitments**: check whether Reserved Instances or EC2 Instance Savings Plans covered the `m5` family in that region, and resell or reassign them (POL-COST-002).
7. **Remove monitoring**: dashboards, alerts and on-call routes for the service.

## Outcome

The last instances were terminated on 2026-03-28. Snapshots expire on 2026-06-26. Monthly EC2 spend for the finance account fell by about 85%.
