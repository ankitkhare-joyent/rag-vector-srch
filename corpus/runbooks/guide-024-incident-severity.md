---
id: GUIDE-024
title: Incident severity levels and escalation
doc_type: guide
team: sre
services: [all]
updated: 2026-09-15
---
# Incident severity levels and escalation

## Severity levels

| Severity | Definition | Response |
|---|---|---|
| 1 | Customer-facing outage or data loss for a major service (checkout, search, fulfillment), or a security breach | Page incident commander and owning team immediately, status page update within 15 minutes, executive notification |
| 2 | Major degradation, partial outage, or risk of a severity 1 within hours | Page owning team, incident channel, updates every 30 minutes |
| 3 | Minor degradation with a workaround, internal tools down | Ticket, fix within 2 business days |
| 4 | Cosmetic or no user impact | Ticket, backlog |

When in doubt, declare the higher severity; downgrading is cheap.

## How to declare

Type `/incident declare sev2 <short title>` in Slack. The bot creates the channel, starts the timeline and pages the on-call of the service you name. Ownership comes from the `Team` tag on the affected resources (POL-TAG-001), so untagged resources slow down paging.

## Roles

- **Incident commander** coordinates and decides; does not debug.
- **Operations lead** from the owning team debugs and fixes.
- **Communications lead** updates the status page and stakeholders.

## After the incident

Severity 1 and 2 incidents need a blameless postmortem within 5 business days, using the template (see PM-2026-03 and PM-2026-05 for examples). Action items get owners and due dates and are reviewed weekly by SRE.

## AWS-side incidents

If the cause is an AWS service event (check the AWS Health Dashboard), still declare an incident for our impact, open an AWS support case, and link the AWS event ARN in the incident channel.
