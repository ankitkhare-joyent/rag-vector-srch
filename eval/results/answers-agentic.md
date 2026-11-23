# Answer eval, mode=agentic (36 questions)

| metric | value |
|---|---|
| citation_hit | 1.0 |
| fact_coverage | 0.984 |
| abstention | 1.0 |
| p50_latency_ms | 25905 |
| p95_latency_ms | 42349 |
| avg_input_tokens | 5822 |
| avg_output_tokens | 865 |
| avg_tool_calls | 1.61 |

Input tokens for the agentic mode are summed over all its model calls. Ran with the earlier reranker (MiniLM-L12) and claude-opus-5-5 at medium effort. Abstention re-scored after widening the phrase check: all 4 unanswerable answers did decline, the first regex missed phrasings like "don't list" and "couldn't find".

## q01 (lexical): What does VcpuLimitExceeded mean and how do I fix it?

relevant: ['RB-020']; cited: ['RB-020']; tool calls: ["search_runbooks {'query': 'VcpuLimitExceeded'}", "search_runbooks {'query': 'service quota increase approval policy', 'doc_type': 'policy'}"]

**It means you've hit your account's vCPU quota, not an AWS capacity shortage.** You need to free up vCPUs or get the quota raised.

**What it is:** EC2 On-Demand and Spot limits are counted in **vCPUs per instance family group per region per account**, not in instances.[1] This is a quota problem in your account, unlike `InsufficientInstanceCapacity`, which is an AWS capacity shortage (RB-004).[1]

**Fix (RB-020):**

1. **Find the right quota code** for the instance family:
   - On-Demand Standard (A, C, D, H, I, M, R, T, Z): `L-1216C47A`[2]
   - On-Demand G and VT: `L-DB2E81BA`[2]
   - On-Demand P: `L-417A185B`[2]
   - Standard Spot requests: `L-34B43A08`[2]

2. **Check the current limit:**
   ```
   aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A
   ```
   Usage is in the CloudWatch `AWS/Usage` namespace, and we alarm at 80% of each quota.[3]

3. **Request an increase:**
   ```
   aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-1216C47A --desired-value 2048
   ```
   Standard increases are often approved within an hour. Large jumps (more than double) or GPU quotas (`L-DB2E81BA`, `L-417A185B`) can take days and may need a support case with a business justification.[4]

4. **Stopgaps while you wait:**
   - Move part of the load to another instance family group with headroom (for example, Spot quota is separate from On-Demand).[5]
   - Scale down idle fleets (RB-014) to free vCPUs.[5]

To avoid this next time, plan quota increases ahead of launches (GUIDE-019) and peak events.[4]

## q02 (lexical): Which quota code covers running on-demand standard instances?

relevant: ['RB-020', 'GUIDE-019']; cited: ['RB-020']; tool calls: ["search_runbooks {'query': 'quota code running on-demand standard instances'}"]

The quota code is **`L-1216C47A`**. It covers Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances[1].

This limit is counted in vCPUs, not in number of instances. EC2 On-Demand and Spot limits are counted in **vCPUs per instance family group per region per account**[2]. When you go over it, launches fail with `VcpuLimitExceeded`.

To request an increase (RB-020):
```
aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-1216C47A --desired-value 2048
```
Standard increases are often approved within an hour; large jumps (more than double) or GPU quotas (`L-DB2E81BA`, `L-417A185B`) can take days[3].

Related codes from RB-020:
- G and VT On-Demand instances: `L-DB2E81BA`
- P On-Demand instances: `L-417A185B`
- Standard Spot requests: `L-34B43A08`. This is a separate pool from On-Demand, so move part of the load to another instance family group with headroom (for example Spot quota is separate from On-Demand)[4] if you need room right away.

## q03 (lexical): What should HttpPutResponseHopLimit be on EKS nodes?

relevant: ['POL-SEC-004']; cited: ['POL-SEC-004']; tool calls: ["search_runbooks {'query': 'HttpPutResponseHopLimit EKS nodes IMDSv2'}"]

It should be **2** on EKS nodes. Per POL-SEC-004, the hop limit is `2` on EKS nodes and Docker hosts, `1` elsewhere[1]. The reason: containers add one network hop; with limit 1 pods cannot reach IMDS at all[1].

**To fix a non-compliant node:**

1. Run:
   ```
   aws ec2 modify-instance-metadata-options --instance-id i-... --http-tokens required --http-put-response-hop-limit 2
   ```
   No reboot is needed.[2]
2. First, make sure the software on the node can use IMDSv2 (session tokens). All AWS SDKs released after 2020 do. Old scripts using `curl http://169.254.169.254/...` without first fetching a token with `PUT /latest/api/token` will break.[2]

**Related settings to keep:**
- `HttpTokens` must be `required`. A Service Control Policy denies `ec2:RunInstances` when `ec2:MetadataHttpTokens` is not `required`.[3]
- Launch templates managed by Terraform set these values.[1] For a lasting fix, change the launch template, not just the running instance.
- Non-compliant instances found after 2026-05-01 are stopped by the security team after 7 days' notice to the owning team (tag `Team`).[3]

## q04 (lexical): InsufficientInstanceCapacity when launching p4d.24xlarge in us-east-1a

relevant: ['RB-004']; cited: ['RB-004', 'RB-014']; tool calls: ["search_runbooks {'query': 'InsufficientInstanceCapacity p4d.24xlarge'}", "search_runbooks {'query': 'GPU capacity reservation p4d us-east-1'}"]

AWS is out of p4d.24xlarge capacity in us-east-1a right now. **Retry in another AZ.** This is not a quota problem: quotas fail with `VcpuLimitExceeded` instead (see RB-020). Retrying the same request in the same AZ often keeps failing for minutes to hours.[1]

**What to do now (RB-004):**

1. **Launch in a different AZ.** Our VPCs have subnets in every AZ listed for the region.[2]
2. **If this is an Auto Scaling group,** make sure the group spans all AZs and uses a mixed-instances policy, so a single type shortage does not block scaling.[2]
3. **Try a different instance type.** For GPU training (`g5`, `p4d`), larger types are the hardest to get. Ask the ML team whether the job can run on more `g5.12xlarge` nodes instead of one `p4d.24xlarge`.[2]
4. **If production is blocked:** If ICE blocks a production scale-out for more than 30 minutes, open a severity 2 incident and an AWS support case of severity "Production system down", quoting the instance type, AZ and request IDs.[3]

**To avoid this next time:**
- **Capacity Blocks for ML** reserve GPU instances for a fixed future window (1 to 182 days). This is the preferred way to get `p4d` and `p5` capacity for training runs longer than a day.[4]
- **On-Demand Capacity Reservations (ODCR)** guarantee capacity in one AZ, billed whether used or not.[4] Create them at least 2 weeks ahead.
- Savings Plans and Reserved Instances give a discount but do **not** guarantee capacity unless they are zonal RIs.[4]

If you're restarting a stopped instance, the same advice applies. Starting a stopped GPU instance can fail with `InsufficientInstanceCapacity`, especially `p4d.24xlarge`.[5] Also note that `p4d` has NVMe instance store used as scratch only[6], and that storage doesn't survive a stop. Only EBS volumes do.

## q05 (lexical): What is the quota code for P instances?

relevant: ['RB-020']; cited: ['RB-020']; tool calls: ["search_runbooks {'query': 'P instances quota code vCPU limit'}"]

The quota code for **Running On-Demand P instances** is **`L-417A185B`**. Running On-Demand P instances | `L-417A185B`[1]

To check your current limit, RB-020 gives this command for Standard instances: `aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A`[2]. Swap in the P code:

```
aws service-quotas get-service-quota --service-code ec2 --quota-code L-417A185B
```

Things to know:
- EC2 On-Demand and Spot limits are counted in **vCPUs per instance family group per region per account**, not in instances.[3] So check the limit in each region and account you use.
- CloudWatch publishes usage in the `AWS/Usage` namespace; we alarm at 80% of each quota.[2]
- If launches fail with `VcpuLimitExceeded`, that's a quota limit in your account. `InsufficientInstanceCapacity`[3] is different: it means AWS is short on capacity, so use RB-004 for that.
- RB-020 only lists the On-Demand code for P instances. It gives no P-instance Spot quota code, so check the full RB-020 or ask the quota owners if you need that.

## q06 (lexical): How do I handle an instance-retirement scheduled event?

relevant: ['RB-021']; cited: ['RB-021']; tool calls: ["search_runbooks {'query': 'instance-retirement scheduled event'}", "read_runbook {'doc_id': 'RB-021'}"]

Before the retirement date, **stop and start the instance if it's EBS-backed, or replace it if it uses instance store**. Source: RB-021.

**Steps**

1. **Confirm the event.** `instance-retirement` means the host has degraded; the instance will be stopped or terminated on the date.[1] Scheduled events appear in `describe-instance-status` under `Events` and in the AWS Health Dashboard, usually with **two weeks' notice**.[2]
2. **Check whether it's in an Auto Scaling group.** If it is, you probably don't need to do anything: instances in Auto Scaling groups are replaced automatically by the `scheduled-event-drainer` Lambda 48 hours before the event.[3]
3. **EBS-backed, not in an ASG:** stop and start before the date[1]. That moves it off the degraded host.
4. **Instance-store nodes:** for `kafka-broker` (`i4i`) and `opensearch-data` on `i4g`, an `instance-retirement` means data on the instance store will be lost.[4]
   - **Kafka brokers:** follow RB-012[4].
   - **OpenSearch:** exclude the node from allocation (`cluster.routing.allocation.exclude._name`) and wait for shards to move before stopping.[4]

**Notes**
- You should already have a ticket. An EventBridge rule on `AWS Health` events opens a ticket for the team in the instance's `Team` tag, 14 days ahead, and reminds again 3 days ahead.[3]
- If the instance failed with no notice, this runbook doesn't apply. That is a status check failure, not a scheduled event; see RB-001.[5]

RB-021 doesn't give exact CLI commands for the stop/start or the OpenSearch allocation change. For the Kafka procedure, read RB-012.

## q07 (lexical): What did postmortem PM-2026-05 find as the root cause?

relevant: ['PM-2026-05']; cited: ['PM-2026-05']; tool calls: ["read_runbook {'doc_id': 'PM-2026-05'}"]

According to PM-2026-05, there were two root causes: the ISM policy silently failed after the upgrade and nothing alerted on ISM failures. The disk alert existed but went to a channel nobody watched at night.[1]

**How it happened:**
1. The index state management (ISM) policy that deletes log-style indices older than 30 days stopped running after an OpenSearch upgrade renamed a policy field. Old indices accumulated for three weeks.[1]
2. On 2026-05-17 the data nodes' EBS volumes crossed the 95% flood-stage watermark, OpenSearch set every index to read-only, and indexing from `search-indexer` failed.[1]
3. Two nodes then ran completely out of disk and their shards went unassigned, turning the cluster red.[1]

**Impact:** Severity 1. Product search returned errors or stale results for 4.5 hours in `eu-central-1`.[1]

**How it was fixed:** The team decided to grow EBS volumes online (RB-002) rather than delete indices under pressure[1]. Once the volumes were grown 40%, they cleared the read-only block with:
```
index.blocks.read_only_allow_delete: null
```

**Action items:**
- Done: Alert on ISM policy execution failures[1]
- Done: Route `DiskUsedPercent > 85` on `opensearch-data` and `kafka-broker` to the paging rotation[1]
- In progress: Add a 20% headroom target to capacity reviews for data volumes[1]
- Done: Document the safe order of operations in RB-002[1]

## q08 (lexical): What does StatusCheckFailed_System mean?

relevant: ['RB-001']; cited: ['RB-001']; tool calls: ["search_runbooks {'query': 'StatusCheckFailed_System'}"]

**An AWS host problem, not something inside your instance.** `StatusCheckFailed_System` means AWS has a problem with the hardware, power, or network of the underlying host. You cannot fix the host. The fix is to move the instance to new hardware by **stopping and starting** it (a reboot does not move it).[1]

**What to do (RB-001):**
1. Confirm which check is failing:
   ```
   aws ec2 describe-instance-status --instance-ids i-... --include-all-instances
   ```
2. If it's in an Auto Scaling group, don't repair it. Mark it unhealthy so the group replaces it: `aws autoscaling set-instance-health --instance-id i-... --health-status Unhealthy`[2]
3. If it's a standalone instance, take an EBS snapshot of the root volume before any change[2]. Then stop it and start it again.

**Warnings:**
- **Instance-store families (i4i, i4g):** these lose their local data on stop, so follow the broker or data-node runbook instead of stopping blindly.[1] Automatic recovery doesn't work on these families either.
- **Many failures at once:** If more than five instances in one Availability Zone fail system checks within 15 minutes, treat it as an AWS event: open a severity 2 incident (see GUIDE-024) and check the AWS Health Dashboard before replacing instances one by one.[3]

**Compared with the other checks:** `StatusCheckFailed_Instance` means the problem is inside your instance, such as a kernel panic, a full disk or running out of memory. Stopping and starting rarely fixes that one.

**Required alarm:** All standalone production instances must have the CloudWatch alarm `StatusCheckFailed_System >= 1 for 2 datapoints` with the `ec2:recover` action.[4]

## q09 (lexical): Which tag is used to exempt a GPU training run from the 72 hour auto-stop?

relevant: ['RB-014']; cited: ['RB-014']; tool calls: ["search_runbooks {'query': 'GPU training 72 hour auto-stop exemption tag'}"]

Use the `LongRun=true` tag, along with a `LongRunTicket` tag.

```
LongRun=true
LongRunTicket=<ticket>
```

**Details from RB-014:**
- Set `LongRun=true` plus `LongRunTicket=<ticket>` for training runs expected to exceed 72 hours.[1]
- **The exemption expires:** The tag is removed automatically after 14 days.[1] If the run will last longer than that, you'll need to put the tag back on.
- **What happens without the tag:** for any GPU instance running more than 72 hours without the tag `LongRun=true`[2], the system will notify owner, stop after 24 more hours[2].
- **The tag doesn't stop the idle rule:** `ml-training` instances are still stopped when GPU utilization below 5% for **2 hours**[2]. The auto-stop also needs the CloudWatch agent's NVIDIA metrics. Instances without the CloudWatch agent's NVIDIA metrics cannot be evaluated and are reported as non-compliant.[2]
- **Checkpoint anyway:** Training jobs must checkpoint to S3 at least every 30 minutes, so a stop loses at most 30 minutes of work.[3]

## q10 (lexical): What is the coverage target in POL-COST-002?

relevant: ['POL-COST-002']; cited: ['POL-COST-002']; tool calls: ["read_runbook {'doc_id': 'POL-COST-002'}"]

The coverage target is **70%**. At least 70% of steady-state On-Demand compute spend should be covered by commitments. Spot, burst and short-lived workloads are excluded from the target.[1]

Other targets in the same policy:
- **Utilization:** above 95% of purchased commitments used each month.[1]
- **Who buys:** Only FinOps purchases them; teams request coverage through the FinOps intake form.[1]
- **Reporting:** FinOps publishes coverage and utilization monthly per team, using Cost Explorer and the EC2 inventory lakehouse.[1]

## q11 (semantic): The search cluster's data disks are almost full, what do I do right now?

relevant: ['RB-002', 'PM-2026-05']; cited: ['PM-2026-05', 'RB-002']; tool calls: ["search_runbooks {'query': 'search cluster data disk full'}", "read_runbook {'doc_id': 'RB-002'}"]

Grow the EBS data volumes online now, following **RB-002**. Don't delete indices while under pressure. At 95% the service is at risk: OpenSearch puts indices into read-only mode at the flood-stage watermark[1].

1. **Find the full mount:**
   ```
   df -h
   du -xh --max-depth=1 /data | sort -h
   ```
2. **Delete only safe files:** old heap dumps in `/data/dumps`, rotated logs older than 7 days, and orphaned temp files from failed jobs. Never delete Kafka log segments or OpenSearch shard directories by hand.[1]
3. **Grow each data node's volume online:**
   ```
   aws ec2 modify-volume --volume-id vol-... --size <new GiB>
   aws ec2 describe-volumes-modifications --volume-id vol-...   # wait for "optimizing" or "completed"
   sudo growpart /dev/nvme1n1 1      # only if the filesystem sits on a partition
   sudo xfs_growfs /data             # XFS (our default)
   sudo resize2fs /dev/nvme1n1p1     # ext4
   ```
   Grow by at least 30% so the alert does not fire again next week.[1]
4. **Check the 6-hour limit:** A volume can only be modified once every 6 hours. If you already modified it today, mitigate by deleting data or moving shards instead.[1]
5. **If indices already went read-only (over 95%):** in the PM-2026-05 incident, after the volumes were grown the read-only block cleared with `index.blocks.read_only_allow_delete: null`[2]. RB-002 doesn't give the exact command for this.

**Follow-up:** Check whether the ISM policies that delete old indices have stopped running. The index state management (ISM) policy that deletes log-style indices older than 30 days stopped running after an OpenSearch upgrade renamed a policy field[3], and that caused PM-2026-05. Then open a ticket for the owning team with the growth rate (GiB per day) from the `disk_used_percent` graph.[1]

## q12 (semantic): How can I get a shell on a production box without SSH keys?

relevant: ['RB-008']; cited: ['RB-008']; tool calls: ["search_runbooks {'query': 'get shell on production instance without SSH keys'}", "search_runbooks {'query': 'Session Manager SSM access production instance shell'}"]

Use **SSM Session Manager**, not SSH. We do not use SSH keys for interactive access. Use AWS Systems Manager Session Manager, which needs no open inbound ports, logs every session to S3 and CloudWatch, and authenticates with your SSO role.[1] (RB-008)

**Start a session:**

1. Log in and open the shell:
```
aws sso login --profile prd-readonly
aws ssm start-session --target i-0abc123 --profile prd-operator
```
For port forwarding, for example to reach a database proxy on 5432:[2]
```
aws ssm start-session --target i-0abc123 --document-name AWS-StartPortForwardingSession \
  --parameters portNumber=5432,localPortNumber=15432
```

**Prerequisites:** the instance runs the SSM Agent (on our golden AMIs, see RB-017); the instance profile includes the managed policy `AmazonSSMManagedInstanceCore`; the instance can reach the SSM endpoints via the VPC interface endpoints (`ssm`, `ssmmessages`, `ec2messages`) or the egress proxy; and locally you need AWS CLI v2 and the Session Manager plugin.[3]

**If you lack access / it's urgent:** The `prd-breakglass` SSO role allows Session Manager on every production instance. Using it pages the security on-call automatically and requires an incident ticket reference within 1 hour.[4]

**If the instance won't connect or boot:** check that it appears in `aws ssm describe-instance-information` — if not, the agent is not registering (common causes: missing instance profile policy, no route to the SSM endpoints, or a stopped agent after a full root disk). Use the EC2 Serial Console as a fallback for instances that cannot boot or register (needs the `ec2-serial-console` permission in the break-glass role).[5]

## q13 (semantic): Our nightly Spark jobs keep losing machines halfway through, how do we make them more reliable?

relevant: ['RB-003']; cited: ['RB-003']; tool calls: ["search_runbooks {'query': 'Spark batch jobs spot instance interruption reliability'}", "search_runbooks {'query': 'spot interruption notice capacity rebalancing allocation strategy'}"]

Your Spark jobs are most likely being hit by Spot interruptions. The best fix is to spread the fleet across more instance types. About 70% of `spark-batch` capacity runs on Spot. AWS can take Spot instances back with a **two-minute interruption notice**. This is expected, not an incident, unless job SLAs are missed.[1]

**When to act (RB-003):** if more than 30% of the Spot fleet is interrupted within one hour, or a nightly job misses its 06:00 UTC SLA twice in a week[2].

**Steps:**
1. Check the interruption frequency per instance type in the Spot placement score and the Spot Instance Advisor.[2]
2. Add more instance types to the mixed-instances policy. We require at least **six** instance types across at least two families[2], for example:
   ```
   c7g.4xlarge, c6g.4xlarge, m7g.4xlarge, r7g.4xlarge, c7gd.4xlarge, m6g.4xlarge
   ```
   Diversification is the single most effective fix.[2]
3. Use the `price-capacity-optimized` allocation strategy, never `lowest-price`.[2]
4. As a last resort, raise `OnDemandBaseCapacity` temporarily and tell the data team in #data-platform.[2]

**Check these settings too:**
- **Graceful decommissioning.** Executors should run with:
  ```
  spark.decommission.enabled=true
  spark.storage.decommission.shuffleBlocks.enabled=true
  ```
  With these on, the executor migrates shuffle and cached RDD blocks to surviving executors, so stages do not restart from scratch.[3] If your jobs restart whole stages, check that these are set.
- **Driver placement.** The driver always runs on On-Demand capacity; never schedule a driver on Spot.[3] If the driver is landing on Spot, the whole job will fail.
- **Capacity Rebalancing.** Make sure it's turned on so the group launches a replacement as soon as AWS sends a rebalance recommendation, which usually arrives before the two-minute notice.[4]

## q14 (semantic): How do I tell if a server is too big for what it does?

relevant: ['GUIDE-010']; cited: ['GUIDE-010']; tool calls: ["search_runbooks {'query': 'rightsizing oversized instance underutilized CPU memory'}"]

Look at 14 days of p95 CPU **and** memory in CloudWatch, then compare them to the GUIDE-010 thresholds below.

**1. Pull the metrics.** Look at 14 days of CloudWatch metrics (or 30 days for monthly-cycle workloads)[1].

**2. Compare to the thresholds:**

| Signal | What it means |
|---|---|
| p95 CPU < 20% **and** p95 memory < 40% | Too big: downsize one size (e.g. `m6i.4xlarge` → `m6i.2xlarge`) |
| p95 CPU < 10% for 14 days | Downsize two sizes or move to a burstable `t` type |
| Memory-bound, low CPU | Wrong family: switch `m` → `r` |
| CPU-bound, low memory | Wrong family: switch `m` → `c` |
| p95 CPU > 80% or memory > 85% | Too small: upsize or scale out |

**3. Check memory data exists.** Memory metrics require the CloudWatch agent; without them, never downsize on CPU alone.[1]

**4. Cross-check with tools.** AWS Compute Optimizer gives per-instance recommendations with a performance risk score. Treat it as input, not truth: it does not know about batch peaks at month end.[2] To rank the biggest savings per team, use the EC2 inventory lakehouse.

**Don't rightsize these** (GUIDE-010):
- Instances in Auto Scaling groups: tune the scaling policy instead.[3]
- `kafka-broker` and `opensearch-data`: their size is driven by storage and network throughput, not CPU.[3]
- Anything with an active On-Demand Capacity Reservation, until the reservation is changed.[3]

**If you resize:** Each change gets a ticket, is applied in staging first, and is monitored for one week. Changing the instance type requires a stop and start, so schedule it in the service's maintenance window.[4]

## q15 (semantic): Developers are complaining their builds wait a long time before starting

relevant: ['RB-013']; cited: ['RB-013']; tool calls: ["search_runbooks {'query': 'CI build jobs queued waiting for runner, slow start'}"]

This matches **RB-013 (CI runner queue backlog)**. It applies when developers report jobs "queued" for more than 5 minutes[1]. Work through these checks in order:

1. **Is the Auto Scaling group at its maximum size?**
   ```
   aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names ci-runner-prd-asg
   ```
   If `DesiredCapacity == MaxSize`, raise `MaxSize` (hard limit 400 per region; above that, request a vCPU quota increase first, see RB-020).[2]
2. **Are launches failing?** Check the group's activity history for `InsufficientInstanceCapacity` (RB-004) or `VcpuLimitExceeded` (RB-020).[2]
3. **Are many Spot instances being interrupted?** If so, see RB-003; the `spot-fallback` label sends retried jobs to On-Demand runners.[2]
4. **Are runners running but not registered?** A broken runner AMI can boot without registering. Compare running instances to registered runners; if they differ, roll back the launch template to the previous version.[2]

**Quick fixes:**
- Raise capacity for now:
  ```
  aws autoscaling set-desired-capacity --desired-capacity <n>
  ```
  The runbook leaves out the group name. The CLI also needs `--auto-scaling-group-name ci-runner-prd-asg`.
- Large monorepo builds can be pinned to `c7a.4xlarge` with the `large` runner label.[3]

**Check the time and region.** Runners scale on queue depth during office hours and scale to a floor of 2 at night and weekends[4]. If people are complaining outside office hours, that floor is the likely cause. Also note that warm pools keep 10 stopped, pre-initialised runners per region so scale-out takes about 40 seconds instead of 3 minutes[3]. If scale-out is taking around 3 minutes, check whether the warm pool is empty.

**Escalation:** if `ci.queue.pending_jobs` is above 50 for 10 minutes[1], devex on-call gets paged automatically.

## q16 (semantic): Is it safe to reboot a Kafka machine to move it onto healthy hardware?

relevant: ['RB-012']; cited: ['RB-001', 'RB-012', 'RB-021']; tool calls: ["search_runbooks {'query': 'Kafka broker reboot stop start move to healthy hardware'}", "search_runbooks {'query': 'scheduled maintenance event instance retirement stop start vs reboot'}"]

**No. A reboot won't get you onto new hardware, and stopping/starting the broker would wipe its data. Replace the broker using RB-012 instead.**

**Why:**
- The fix is to move the instance to new hardware by **stopping and starting** it (a reboot does not move it).[1]
- Brokers run on `i4i.2xlarge` instances with NVMe **instance store** for log segments. Instance store is ephemeral: data is lost when the instance is stopped, terminated, or the host fails.[2]
- Never stop and start a broker to "move it to new hardware" as you would for EBS-backed instances; that wipes its data, which is fine only if you follow this runbook.[3]

**What to do (RB-012):**
1. Check there are no under-replicated partitions. This command should return nothing:
   ```
   kafka-topics.sh --describe --under-replicated-partitions
   ```
2. Stop Kafka cleanly so it hands over leadership:
   ```
   systemctl stop kafka
   ```
3. Launch the replacement from the `kafka-broker` launch template **with the same `broker.id`** in the same AZ. Terraform module `kafka_broker` does this when you taint the old instance.[4]
4. The new broker starts empty and copies its partitions back from the other replicas. On our cluster this takes 2 to 4 hours; throttle it with `leader.replication.throttled.rate` at 200 MB/s so client traffic is not affected.[4]
5. Wait until under-replicated partitions are zero before touching another broker. Only one broker may be replaced at a time.[4]
6. Run preferred leader election at the end.[4]

If a scheduled retirement event triggered this, RB-021 says the same thing: an `instance-retirement` means data on the instance store will be lost. Follow RB-012 for brokers[5].

## q17 (semantic): How much cheaper are Arm instances and what breaks when moving to them?

relevant: ['GUIDE-009']; cited: ['GUIDE-009', 'POL-COST-002']; tool calls: ["search_runbooks {'query': 'Graviton Arm instances cost savings migration'}", "search_runbooks {'query': 'arm64 compatibility issues breaks multi-arch images'}"]

**Savings:** for our services, Graviton instances are typically **20 to 30% cheaper per unit of work** than the equivalent Intel (`i`) or AMD (`a`) types, and use less power.[1] These are the instance types with a `g` after the generation number, such as `m7g`, `c7g` and `r7g`.

**What breaks or blocks a move:**
1. **Images built only for x86:** container images built only for amd64 fail with `exec format error`.[2] Build for both architectures:
   ```
   docker buildx build --platform linux/amd64,linux/arm64
   ```
   Our CI runners have built both by default since March 2026.[3]
2. **Native dependencies:** these need arm64 builds. Check Python wheels for `aarch64`, and check any vendored binaries.[4] Python, Java 17+, Node.js and Go usually just work.[4]
3. **Windows:** not eligible, because Graviton doesn't run Windows.[4]
4. **GPU workloads:** these stay on `g5` and `p4d` (x86).[4]
5. **Old JDKs:** JVM services should use a recent JDK, because older ones miss the arm64 performance work.[2]
6. **Savings Plans:** Compute Savings Plans apply to Graviton automatically, but EC2 Instance Savings Plans don't move between families (POL-COST-002).[3] Switching a large fleet to a different instance family needs a FinOps check first, to make sure no EC2 Instance Savings Plan would go unused.[5]

**Sizing tip:** compare per vCPU. A Graviton vCPU is a full physical core, while an x86 vCPU is a hyper-thread, so the same vCPU count usually does more work on Graviton.[2]

**Rollout:** run the service's load test on one Graviton instance and compare p99 latency and throughput per dollar. Then add the Graviton type to the Auto Scaling group's mixed-instances policy with a low weight, and shift traffic over two weeks.[3] The full procedure is in GUIDE-009.

## q18 (semantic): A Kubernetes worker stopped reporting to the control plane, what's the procedure?

relevant: ['RB-011']; cited: ['RB-011']; tool calls: ["search_runbooks {'query': 'Kubernetes worker node NotReady stopped reporting to control plane'}"]

That's a `NotReady` node, so follow **RB-011**. The quick version: triage it, then cordon, drain and replace it. Don't try to repair the node in place.

**Check first:** If more than 3 nodes go NotReady at once, stop and look for a shared cause (AMI rollout, CNI version, AZ event) before replacing nodes.[1]

**Triage**
1. `kubectl get nodes -o wide | grep NotReady` and note the instance ID from the provider ID.[2]
2. `kubectl describe node <node>` and read the Conditions. `MemoryPressure`, `DiskPressure` and `PIDPressure` point at resource exhaustion inside the node.[2]
3. Check the EC2 status checks for the instance (RB-001). A failed system check means the host is bad.[2]
4. Open a session with SSM (RB-008) and check `systemctl status kubelet containerd` and `journalctl -u kubelet --since -30m`.[2]

**Common causes**
- Disk pressure from container images and logs on the root volume.[3]
- IP address exhaustion: pods stuck in `ContainerCreating` with `failed to assign an IP address` mean the subnet ran out of IPs.[3]
- kubelet certificate expiry after a node was stopped for weeks.[3]
- IMDS hop limit set to 1, which breaks pods that need the node role (POL-SEC-004 requires 2 on EKS nodes).[3]

**Fix**
```
kubectl cordon <node>
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=10m
aws autoscaling terminate-instance-in-auto-scaling-group --instance-id i-... --no-should-decrement-desired-capacity
```
The Auto Scaling group launches the replacement. Respect PodDisruptionBudgets; if a drain hangs, find the blocking PDB rather than forcing.[1]

If the cause was disk pressure and it keeps happening, grow it in the launch template[3]. The node AMI's root volume is currently 100 GiB.

## q19 (semantic): Who decides on the severity when production is down and how do I start an incident?

relevant: ['GUIDE-024']; cited: ['GUIDE-024']; tool calls: ["search_runbooks {'query': 'incident severity declaration who decides SEV1 production down'}", "search_runbooks {'query': 'how to start declare an incident incident commander channel'}"]

**If production is down, declare it now. Don't wait for someone else to choose the severity.** GUIDE-024 says when in doubt, declare the higher severity; downgrading is cheap.[1]

**Who decides:** GUIDE-024 doesn't name anyone who sets the starting severity. You pick it when you declare. After that, the **Incident commander** coordinates and decides; does not debug.[2] So the IC owns severity decisions, including upgrades and downgrades, once the incident is running.

**Which severity:**
- **Sev 1:** Customer-facing outage or data loss for a major service (checkout, search, fulfillment), or a security breach[1]. Response: Page incident commander and owning team immediately, status page update within 15 minutes, executive notification[1]
- **Sev 2:** Major degradation, partial outage, or risk of a severity 1 within hours[1]

**How to start:**
1. Run this in Slack, using sev1 if it's a full customer-facing outage:
   ```
   /incident declare sev1 <short title>
   ```
   The bot creates the channel, starts the timeline and pages the on-call of the service you name.[3]
2. Check that the affected resources have the `Team` tag. Ownership comes from the `Team` tag on the affected resources (POL-TAG-001), so untagged resources slow down paging.[3]
3. Fill the roles: the **Operations lead** from the owning team debugs and fixes. **Communications lead** updates the status page and stakeholders.[2]
4. If AWS caused it, still declare an incident for our impact, open an AWS support case, and link the AWS event ARN in the incident channel.[4]

**Afterwards:** Severity 1 and 2 incidents need a blameless postmortem within 5 business days[5].

## q20 (semantic): We deleted data by accident on a volume, how do we get it back?

relevant: ['RB-025']; cited: ['RB-025']; tool calls: ["search_runbooks {'query': 'restore EBS volume from snapshot accidental data deletion'}", "search_runbooks {'query': 'recycle bin snapshot recovery deleted'}"]

Restore from the latest DLM snapshot taken before the deletion into a **new** volume, following RB-025. RB-025 covers the case where data was deleted or corrupted.[1]

**First, check that a snapshot exists.** Data Lifecycle Manager takes daily snapshots of every volume tagged `Backup=daily` at 03:00 UTC and keeps 14 of them. Weekly snapshots are kept for 8 weeks. Root volumes are not backed up because instances are rebuilt from the golden AMI (RB-017).[2] If the data was on a root volume or a volume without that tag, RB-025 won't help you.

**Steps:**
1. Find the snapshot:
   ```
   aws ec2 describe-snapshots --owner-ids self --filters Name=tag:Service,Values=<service>
   ```
2. Create the volume in the **same Availability Zone** as the target instance; volumes cannot attach across AZs[3]:
   ```
   aws ec2 create-volume --snapshot-id snap-... --availability-zone eu-central-1a --volume-type gp3 --tag-specifications ...
   ```
3. Expect slow first reads, because a volume created from a snapshot loads blocks lazily from S3[3]. For databases, enable Fast Snapshot Restore on the snapshot beforehand (costs extra per hour per AZ), or pre-warm by reading every block with `fio`.[3]
4. Attach the volume, mount it read-only first, check the data, then switch the application over.[3]
5. Keep the old volume, detached and tagged `RetainUntil`, for 7 days in case you need to compare.[3]

**Notes:**
- Anything written after the last 03:00 UTC snapshot is not in that snapshot.
- If you only need a few files, the steps above should also work for that: mount the restored volume read-only and copy the files back. RB-025 doesn't spell this out.
- If the snapshot is in another region or account: Copy the snapshot first (`aws ec2 copy-snapshot`). Encrypted snapshots need the KMS key shared with the target account.[4]

## q21 (semantic): What do the letters in r7gd.4xlarge mean?

relevant: ['GUIDE-026']; cited: ['GUIDE-009', 'GUIDE-026']; tool calls: ["search_runbooks {'query': 'instance type naming convention family generation suffix letters (g Graviton, d local NVMe)'}", "read_runbook {'doc_id': 'GUIDE-026'}"]

`r7gd.4xlarge` is a memory-optimized, 7th-generation Graviton (Arm) instance with local NVMe storage and 16 vCPUs. The name has four parts: **family** (`r`), **generation** (`7`), **attributes** (`gd`) and **size** (`4xlarge`).[1] This comes from GUIDE-026.

1. **`r` (family):** Memory optimized, typically 8 GiB per vCPU. We use it for `search-indexer` and `payments-db-proxy`.[2]
2. **`7` (generation):** Newer generations are usually cheaper per unit of performance. New launches must be generation 6 or later.[3] Generation 7 meets that rule.
3. **`g` (attribute):** AWS Graviton (Arm) processor[4]. For our services, Graviton is typically **20 to 30% cheaper per unit of work** than the equivalent Intel (`i`) or AMD (`a`) types[5]. GUIDE-009 covers moving workloads to Graviton.
4. **`d` (attribute):** Local NVMe instance store included[4].
5. **`4xlarge` (size):** Each size step doubles vCPUs and memory: `large` = 2 vCPUs, `xlarge` = 4, `2xlarge` = 8, `4xlarge` = 16[6]. At about 8 GiB per vCPU, that comes to roughly 128 GiB of memory (my estimate). Price roughly doubles with each step too, which is why downsizing one step saves about 50% (GUIDE-010).[6]

Because of the `g`, this instance needs arm64 builds and AMIs.

## q22 (semantic): Checkout got slow right after we rolled out a new machine image, has this happened before?

relevant: ['PM-2026-03']; cited: ['PM-2026-03', 'RB-017']; tool calls: ["search_runbooks {'query': 'checkout latency after new AMI rollout', 'doc_type': 'postmortem'}", "search_runbooks {'query': 'AMI rollback slow latency regression'}", "read_runbook {'doc_id': 'RB-017'}"]

Yes, this has happened before. **PM-2026-03** describes the same pattern, and the fix was to stop the rollout and roll back. If your rollout is still running, do that first.

**What to do now (from how PM-2026-03 was resolved):**
1. Check the ASG activity history to confirm the slowdown started with the instance refresh. Last time, correlation with the instance refresh found from the ASG activity history[1] took 25 minutes.
2. Stop the instance refresh and roll back. In that incident, the instance refresh [was] cancelled; rollback started to the previous launch template version[1]. To roll back, point the launch template at the previous version; old AMIs are kept for 90 days.[2]
3. Look for long JVM garbage-collection pauses. Last time, the new AMI shipped a kernel with a changed default for transparent huge pages, which caused long JVM garbage-collection pauses under load.[3]

The runbooks don't include the exact CLI commands for cancelling the refresh or rolling back, so use your usual tooling.

**What happened last time:** On 2026-03-12, p99 checkout latency rose from 280 ms to 2.4 s in `us-east-1`; about 3% of checkouts timed out.[4] The kernel change was made worse by the rollout settings: because the instance refresh replaced half of the fleet at once, the healthy capacity was too small to absorb traffic.[3]

**Fixes made afterwards (worth checking they're still in place):**
- Instance refresh for `checkout-api` now uses `MinHealthyPercentage=90` and checkpoints at 10%, 50%[5]
- AMI pipeline runs a 30-minute JVM load test before promotion[5]
- `transparent_hugepage=madvise` (from PM-2026-03)[2] is pinned in the golden AMI.

If those fixes are all in place and it's still slow, the cause is probably something new. Collect evidence (GC logs, kernel/sysctl differences between the old and new AMI) for the platform team, who own the golden AMI under RB-017.

## q23 (semantic): Can I open port 22 to the internet for a quick debug session?

relevant: ['POL-SEC-007']; cited: ['POL-SEC-007', 'RB-008']; tool calls: ["search_runbooks {'query': 'open port 22 SSH to 0.0.0.0/0 security group policy'}", "search_runbooks {'query': 'debug access to instance SSM Session Manager break-glass'}"]

No, don't open it. Under POL-SEC-007, SSH (port 22) and RDP (port 3389) must never be open to the internet. Interactive access goes through AWS Systems Manager Session Manager (RB-008).[1] Even a short-lived rule gets caught:
- AWS Config rules `restricted-ssh` and `vpc-sg-open-only-to-authorized-ports` run continuously. Violations page the security on-call within 15 minutes.[2]
- Opening it again without an exception counts as a security incident.[3]

**Use Session Manager instead (RB-008).** It needs no open inbound ports, logs every session to S3 and CloudWatch, and authenticates with your SSO role.[4]

1. Log in and start a session:
   ```
   aws sso login --profile prd-readonly
   aws ssm start-session --target i-0abc123 --profile prd-operator
   ```
2. If you need a port on the instance, forward it to your machine:
   ```
   aws ssm start-session --target i-0abc123 --document-name AWS-StartPortForwardingSession \
     --parameters portNumber=5432,localPortNumber=15432
   ```
3. If the instance shows as "not connected": Check that the instance appears in `aws ssm describe-instance-information`. If not, the agent is not registering.[5] The usual causes are missing instance profile policy, no route to the SSM endpoints, or a stopped agent after a full root disk.[5] The instance profile needs the managed policy `AmazonSSMManagedInstanceCore`[6].
4. If you have no access or the instance won't boot: The `prd-breakglass` SSO role allows Session Manager on every production instance. Using it pages the security on-call automatically and requires an incident ticket reference within 1 hour.[7] You can also use the EC2 Serial Console as a fallback for instances that cannot boot or register (needs the `ec2-serial-console` permission in the break-glass role).[5]

## q24 (semantic): What labels must every VM carry for cost allocation?

relevant: ['POL-TAG-001']; cited: ['POL-TAG-001']; tool calls: ["search_runbooks {'query': 'required tags cost allocation EC2 instances'}", "read_runbook {'doc_id': 'POL-TAG-001'}"]

Under POL-TAG-001, every EC2 instance must carry five tags: `Name`, `Environment`, `Team`, `Service` and `CostCenter`. Tags drive cost allocation, ownership lookups during incidents, and automation. Every EC2 instance, EBS volume and snapshot must carry the required tags[1].

**Required tags:**

| Key | Example | Rule |
|---|---|---|
| `Name` | `checkout-api-prd-a` | Lowercase; service name plus environment |
| `Environment` | `prd` | Must be `prd`, `stg`, `dev` or `sandbox` |
| `Team` | `payments` | Must match a team in the on-call directory |
| `Service` | `checkout-api` | Must match the service catalog |
| `CostCenter` | `cc-4821` | `cc-` followed by four digits; finance maps it to a budget |

`ManagedBy` and `DataClassification` are optional but encouraged.

**Why it matters (enforcement):**
- Untagged spend is charged to the owning account's team budget at a 10% penalty rate from Q3 2026.[2]
- Instances missing `Team` and `Service` for more than 14 days are flagged to the account owner and may be stopped.[2]
- The FinOps team publishes a weekly **untagged resources report** every Monday[2].

**To fix missing tags:**
1. Tag the resource by hand:
   ```
   aws ec2 create-tags --resources i-... vol-... --tags Key=CostCenter,Value=cc-4821
   ```
2. For Terraform-managed resources, set `default_tags` in the AWS provider block instead. Don't tag these by hand, because the next apply will revert the change.
3. Auto Scaling groups must set `PropagateAtLaunch=true` so instances get the tags at launch. EKS managed node groups get their tags from the launch template.

All of the above comes from POL-TAG-001: Resource tagging standard[3].

## q25 (semantic): How often are base images rebuilt and how old can they get in production?

relevant: ['RB-017']; cited: ['RB-017']; tool calls: ["search_runbooks {'query': 'base image AMI rebuild cadence maximum age production'}"]

From RB-017 (golden AMI build and patching cadence):

**How often they're rebuilt**
- Images are rebuilt on the first Tuesday of every month, and out of cycle within 72 hours for critical CVEs (CVSS 9.0 or higher).[1]
- Each build is tested, then shared to `stg` accounts; teams have 5 working days to roll out to staging.[2] After that it's promoted to `prd`; the SSM Parameter `/golden-ami/<variant>/latest` is updated.[2]

**Maximum age in production**
- A production instance must not run an AMI older than **30 days**[3].
- The exception is 60 days for instance-store fleets such as `kafka-broker`, because each replacement re-replicates data.[3]
- The weekly compliance report lists offenders by `Team` tag.[3]

**If you need to catch up**
1. For Auto Scaling groups, update the launch template to the new SSM parameter version and start an instance refresh. Use `MinHealthyPercentage=90` for latency-sensitive services.[4]
2. For standalone instances, replace, do not patch in place, unless the owning team has an approved exception.[4]
3. To roll back, point the launch template at the previous version; old AMIs are kept for 90 days.[4]

## q26 (semantic): How did we shut down the old Windows reporting servers?

relevant: ['RB-018']; cited: ['RB-018']; tool calls: ["search_runbooks {'query': 'decommission Windows reporting servers'}"]

That was the `legacy-reporting` decommission, written up in **RB-018**. The service (finance team, `m5.large` and `m5.xlarge`, about 60% Windows Server) was replaced by dashboards on the Trino lakehouse and decommissioned in March 2026.[1] RB-018 is also the template for future decommissions.

**Steps followed:**

1. **Confirmed no traffic for 30 days.** ALB request count was zero and no scheduled tasks ran. Owners signed off in the decommission ticket.[2]
2. **Took final backups.** EBS snapshots of every data volume, tagged `RetainUntil=<date 90 days out>` and `DecommissionTicket=<id>`.[2] Finance needs report archives kept for 7 years, so those were exported to S3 Glacier Deep Archive, not kept as snapshots.[2]
3. **Stopped the instances, then waited 14 days.** Stopped instances cost only their EBS storage, and the wait catches forgotten dependencies.[2]
4. **Terminated** the instances and deleted the Auto Scaling groups, launch templates, target groups, DNS records and security groups.[2]
5. **Handled licenses.** Windows license-included instances stop billing at termination; procurement was told to cancel any SQL Server licenses brought under BYOL.[2]
6. **Cleaned up commitments.** Checked for Reserved Instances or EC2 Instance Savings Plans covering the `m5` family in that region, and resold or reassigned them (POL-COST-002).[2]
7. **Removed monitoring:** dashboards, alerts and on-call routes for the service.[2]

**Outcome:** The last instances were terminated on 2026-03-28. Snapshots expire on 2026-06-26. Monthly EC2 spend for the finance account fell by about 85%.[3]

## q27 (semantic): The PgBouncer boxes in front of the payments database are failing health checks

relevant: ['RB-023']; cited: ['RB-001', 'RB-023']; tool calls: ["search_runbooks {'query': 'PgBouncer health check failing payments database'}", "read_runbook {'doc_id': 'RB-023'}"]

First, work out how many proxies are failing. One failing proxy is a proxy problem. All of them failing means the problem is the database or the network. The steps below are from RB-023 (payments-db-proxy failover).

**Context:** The proxies are PgBouncer instances (`r6i.large`, 8 per region) in front of the payments PostgreSQL cluster. Clients connect through a Network Load Balancer on port 6432.[1] They aren't in an Auto Scaling group, so nothing will replace them automatically.

**Steps**
1. Check NLB target health and which proxy is failing.[2]
2. **If only one proxy failed its EC2 status checks:** the CloudWatch recovery alarm (RB-001) recovers it on new hardware with the same private IP. Wait 10 minutes before intervening.[2]
3. **If the instance is healthy but PgBouncer isn't:** connect via SSM (RB-008) and run[2]
   ```
   systemctl restart pgbouncer
   ```
   Connections on that proxy drop; clients retry.[2]
4. **If all proxies fail at once:** the problem is the database or the network, not the proxies. Page the payments database owner and check the Aurora cluster status.[2]

**Check the logs for `auth failed`.** A proxy that failed to fetch credentials logs `auth failed` for every client; restarting PgBouncer re-reads them.[3] The credentials are rotated every 30 days, so a recent rotation could be the cause.

**Do not:**
- Do not terminate a proxy: its private IP is on the payment processor allow-list and changing it requires a 5-day change process with the processor.[4]
- Do not raise `max_client_conn` above 5,000 without checking the database's `max_connections`.[4]

If a proxy is still failing its status checks after 10 minutes, follow RB-001. For standalone instances, take an EBS snapshot of the root volume before any change.[5]

## q28 (semantic): What did we learn from opening the Singapore region?

relevant: ['GUIDE-019']; cited: ['GUIDE-019']; tool calls: ["search_runbooks {'query': 'Singapore region launch ap-southeast-1 lessons learned'}"]

The Singapore launch taught us three things. All of them are in **GUIDE-019**. In April 2026 the logistics team launched `fulfillment-edge` in `ap-southeast-1` (Singapore), our first service there. These are the steps and lessons, kept as the checklist for the next region launch.[1]

**Lessons learned**
1. **Ask for quota increases sooner.** The vCPU quota increase took 6 days; request it earlier.[2]
2. **Add the region to the tagging policy.** We forgot to add the region to the tagging policy's enforced regions, so the first week's instances lacked `CostCenter`.[2]
3. **Keep database reads in the same region.** Latency to the `eu-central-1` order database was 160 ms; read replicas in-region fixed it.[2]

**How this changes the checklist for the next region**
- **Four weeks before:** new regions start with low default quotas. Request increases for "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances" (quota code `L-1216C47A`), Elastic IPs and Application Load Balancers. Quota requests can take several days (RB-020).[3]
- **Before any workload runs:** turn on GuardDuty, Config rules and the IMDSv2 account default[3] in the region. Also add the region to the tagging policy's enforced regions, since that step was missed last time.
- **Launch week:** Start with On-Demand capacity only; add Spot after two weeks of stable traffic.[4] Load test from the region at 2x the expected peak.[4]

For the full checklist, including networking and golden AMI steps, read GUIDE-019.

## q29 (multi): Scaling out CI fails with launch errors. Is it a quota or an AWS capacity problem, and what do I do for each?

relevant: ['RB-013', 'RB-004', 'RB-020']; cited: ['RB-004', 'RB-013', 'RB-020']; tool calls: ["search_runbooks {'query': 'InsufficientInstanceCapacity launch error'}", "search_runbooks {'query': 'VcpuLimitExceeded quota increase'}", "search_runbooks {'query': 'CI runner scale out launch failures'}", "read_runbook {'doc_id': 'RB-020'}"]

**Start with the error code in the ASG activity history.** It tells you which problem you have.

**1. Find the error** Check the group's activity history for `InsufficientInstanceCapacity` (RB-004) or `VcpuLimitExceeded` (RB-020).[1] Also check whether the group is just at its max:
```
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names ci-runner-prd-asg
```
If `DesiredCapacity == MaxSize`, raise `MaxSize` (hard limit 400 per region; above that, request a vCPU quota increase first, see RB-020).[1]

**2. `VcpuLimitExceeded` means a quota problem (RB-020)**
CI runners are `c7a.2xlarge` and `c7a.4xlarge`, mostly Spot[2]. That means the Spot quota `L-34B43A08` is probably the one you're hitting. On-Demand Standard is `L-1216C47A`. I've inferred this from the instance types, so confirm it against the error.
```
aws service-quotas get-service-quota --service-code ec2 --quota-code L-34B43A08
aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-34B43A08 --desired-value <n>
```
- Standard increases are often approved within an hour; large jumps (more than double) ... can take days[3].
- While you wait: Move part of the load to another instance family group with headroom (for example Spot quota is separate from On-Demand). Scale down idle fleets (RB-014) to free vCPUs.[4]

**3. `InsufficientInstanceCapacity` means AWS is out of capacity (RB-004)**
It is not a quota problem[5], and retrying the same request in the same AZ often keeps failing for minutes to hours.[5]
- Read the full error. It names the instance type and AZ[6].
- Retry in a different AZ.[6]
- Make sure the group spans all AZs and uses a mixed-instances policy, so a single type shortage does not block scaling.[6]
- Escalate if ICE blocks a production scale-out for more than 30 minutes[7]: open a Sev 2 incident and an AWS support case at "Production system down". Include the instance type, AZ and request IDs.

**If launches succeed but jobs still queue**, check the AMI. A broken runner AMI can boot without registering.[8] If the number of running instances doesn't match the number of registered runners, roll the launch template back to the previous version.

## q30 (multi): Before buying Savings Plans for a fleet, what cost work should happen first?

relevant: ['POL-COST-002', 'GUIDE-009', 'GUIDE-010']; cited: ['POL-COST-002']; tool calls: ["search_runbooks {'query': 'Savings Plans purchase prerequisites rightsizing before commitment'}"]

Do the Graviton migration and the rightsizing first, and leave out any fleet that will be decommissioned or migrated during the term. Only then ask FinOps for coverage. All of this comes from POL-COST-002.

**Before you buy:**
1. **Migrate to Graviton (GUIDE-009) and rightsize (GUIDE-010).** Graviton migrations (GUIDE-009) and rightsizing (GUIDE-010) happen before buying, not after, so we do not commit to waste.[1]
2. **Leave out short-lived fleets.** Do not buy commitments for workloads planned for decommission or migration within the term (for example the old `m5` fleet before RB-018).[1]
3. **Size only the steady baseline.** The goal is 70% of steady-state On-Demand compute spend under commitments. Spot, burst and short-lived workloads are excluded from the target.[2] Monthly utilization of purchased commitments should stay above 95%[2].
4. **Send the request to FinOps.** Only FinOps purchases them; teams request coverage through the FinOps intake form.[3]

**What FinOps will buy by default:**
- Compute Savings Plans first (apply across families, regions, Graviton and x86, Fargate and Lambda, up to about 66% off)[2]. EC2 Instance Savings Plans are only for stable families, because they are tied to one family in one region[2].
- 1-year no-upfront by default; 3-year only for platforms with a committed multi-year roadmap (`kafka-broker`, `opensearch-data`).[2]

**Two warnings:**
- Savings Plans give a discount but do not reserve capacity; use On-Demand Capacity Reservations for that (RB-004).[1]
- After you buy, changing a large fleet's instance family requires a FinOps check that no EC2 Instance Savings Plan would become unused.[1]

## q31 (multi): An i4i Kafka broker got an AWS retirement notice. What exactly do I do?

relevant: ['RB-021', 'RB-012']; cited: ['RB-012', 'RB-021']; tool calls: ["search_runbooks {'query': 'instance retirement notice i4i instance store Kafka broker'}", "search_runbooks {'query': 'scheduled event retirement replace broker', 'service': 'kafka-broker'}"]

**Don't stop/start it. Replace the broker using RB-012.** On i4i, an `instance-retirement` means data on the instance store will be lost. Follow RB-012 for brokers[1]. Durability comes from Kafka replication (replication factor 3, `min.insync.replicas=2`), not from the disk.[2]

**Steps (RB-012):**

1. Confirm the cluster is healthy: no under-replicated partitions[3]. This should return nothing:
   ```
   kafka-topics.sh --describe --under-replicated-partitions
   ```
2. Stop the broker process cleanly with `systemctl stop kafka` so it hands over leadership.[3]
   ```
   systemctl stop kafka
   ```
3. Launch the replacement from the `kafka-broker` launch template **with the same `broker.id`** in the same AZ. Terraform module `kafka_broker` does this when you taint the old instance.[3]
4. The new broker starts empty and re-replicates its partitions from the other replicas. On our cluster this takes 2 to 4 hours; throttle it with `leader.replication.throttled.rate` at 200 MB/s so client traffic is not affected.[3]
5. Wait until under-replicated partitions are zero before touching another broker. Only one broker may be replaced at a time.[3]
6. Run preferred leader election at the end.[3]

**Watch out for:**
- Never stop and start a broker to "move it to new hardware" as you would for EBS-backed instances; that wipes its data[4].
- Timing: an EventBridge rule on `AWS Health` events opens a ticket for the team in the instance's `Team` tag, 14 days ahead, and reminds again 3 days ahead.[5] Leave room for the 2–4 hour re-replication. If other brokers also have notices, you'll have to replace them one after another.
- If the instance fails before the retirement date, that's a status check failure, not a scheduled event. see RB-001.[6]

## q32 (multi): Why can pods on EKS not reach instance metadata after we enforced IMDSv2?

relevant: ['POL-SEC-004', 'RB-011']; cited: ['POL-SEC-004', 'RB-011']; tool calls: ["search_runbooks {'query': 'EKS pods cannot reach instance metadata IMDSv2 hop limit'}"]

Most likely the hop limit is set to 1. With IMDSv2, a container adds one network hop. with limit 1 pods cannot reach IMDS at all[1]. POL-SEC-004 requires `HttpPutResponseHopLimit` to be `2` on EKS nodes and Docker hosts, `1` elsewhere[1]. RB-011 also lists this as a known cause: an IMDS hop limit set to 1, which breaks pods that need the node role[2].

**Fix:**

1. Set the hop limit to 2 on each affected node. No reboot is needed.[3]
   ```
   aws ec2 modify-instance-metadata-options --instance-id i-... --http-tokens required --http-put-response-hop-limit 2
   ```
2. Fix the node group's launch template so new nodes don't come up with the same problem. Launch templates managed by Terraform set these values.[1] That means the Terraform for this node group is probably where the 1 came from.
3. If pods still fail after that, check their clients. Old scripts using `curl http://169.254.169.254/...` without first fetching a token with `PUT /latest/api/token` will break.[3] SDKs are generally fine, since all AWS SDKs released after 2020 do[3] support IMDSv2.

**Don't** go back to IMDSv1 to work around this. IMDSv1 (`HttpTokens=optional`) is forbidden[4], and A Service Control Policy denies `ec2:RunInstances` when `ec2:MetadataHttpTokens` is not `required`.[5]

## q33 (unanswerable): How do I rotate the TLS certificate on the internal load balancer?

relevant: none; cited: ['POL-SEC-004', 'POL-SEC-007', 'RB-023']; tool calls: ["search_runbooks {'query': 'rotate TLS certificate internal load balancer'}", "search_runbooks {'query': 'ACM certificate expiry renewal ALB listener HTTPS'}"]

The runbooks don't cover this. I ran two searches (one for "TLS certificate rotation, internal load balancer" and one for "ACM certificate renewal, ALB HTTPS listener") and found no procedure for rotating a load balancer certificate. I won't make up steps or commands.

**What I'd do now:**
1. **Find the owner first.** I couldn't find an "internal load balancer" in the runbooks. The closest match is in RB-023: payments-db-proxy clients connect through a Network Load Balancer on port 6432[1]. If that's your load balancer, contact the payments-db-proxy owners. RB-023 only covers how the proxies handle database passwords: they fetch them from the secrets manager at boot, the passwords are rotated every 30 days, and restarting PgBouncer re-reads them[2]. Nothing in it covers TLS certificates.
2. **Ask the security team.** They're the closest fit for certificate questions. The only security process in the docs is POL-SEC-004, where exceptions require a ticket in the SEC project approved by the security lead[3]. Raising a SEC ticket is a reasonable way to reach them.
3. **Don't change listener or security-group rules while you rotate.** Under POL-SEC-007, traffic inside a VPC should reference other security groups instead of CIDR ranges, and every rule needs a description[4].

**Afterwards:** once the rotation is done, write it up as a runbook so the next on-call has a procedure to follow.

If you can tell me which service sits behind the load balancer or what error you're seeing (for example, an expiry alert), I can search for that more specifically.

## q34 (unanswerable): What is the on-call phone number for the payments team?

relevant: none; cited: ['GUIDE-024', 'POL-TAG-001']; tool calls: ["search_runbooks {'query': 'payments team on-call phone number contact escalation'}"]

The runbooks don't list a phone number for the payments team, or for any team. They don't page people by phone number. Paging goes through the incident bot.

**To reach payments on-call now:**

1. Declare the incident in Slack:
   ```
   /incident declare sev2 <short title>
   ```
   The bot creates the channel, starts the timeline and pages the on-call of the service you name.[1]
2. Check that the affected resources have the `Team` tag set correctly. Ownership comes from the `Team` tag on the affected resources (POL-TAG-001), so untagged resources slow down paging.[1] In POL-TAG-001, `payments` is the example `Team` value, and the tag must match a team in the on-call directory[2].
3. Pick the right severity (GUIDE-024):
   - **Sev 1:** Customer-facing outage or data loss for a major service (checkout, search, fulfillment), or a security breach[3]. Response: Page incident commander and owning team immediately[3].
   - **Sev 2:** Major degradation, partial outage, or risk of a severity 1 within hours[3].
   - If you're unsure: When in doubt, declare the higher severity; downgrading is cheap.[3]

If you need an actual phone number, look in the on-call directory that POL-TAG-001 refers to. It isn't in these documents.

## q35 (unanswerable): How do I configure cross-region replication for our DynamoDB tables?

relevant: none; cited: ['GUIDE-019', 'RB-025']; tool calls: ["search_runbooks {'query': 'DynamoDB cross-region replication global tables'}"]

I couldn't find this in the runbooks. They cover running the EC2 fleet, and none of them explains how to set up DynamoDB cross-region replication (global tables). The search only returned EC2-related documents. I won't guess at a procedure.

**Closest matches, in case they help:**
- **RB-025** (Restoring an EBS volume from a snapshot): covers EBS snapshots across regions, not DynamoDB. Copy the snapshot first (`aws ec2 copy-snapshot`). Encrypted snapshots need the KMS key shared with the target account.[1]
- **GUIDE-019** (Launching a service in a new region): useful if you're replicating because you're expanding into a new region. Its lessons learned say Latency to the `eu-central-1` order database was 160 ms; read replicas in-region fixed it.[2] It also covers what to set up beforehand in the new region: quotas, networking, AMIs and security.

**What to do next:**
1. Ask whoever owns the DynamoDB tables or data platform. The runbooks don't name a DynamoDB team, so I can't tell you which one.
2. Use the AWS documentation on DynamoDB global tables for the actual setup.
3. If this is for a new-region launch, also work through the checklist in GUIDE-019.

If you're asking because of a specific EC2-side problem, like connectivity or latency to the tables, tell me the symptoms and I'll search for that.

## q36 (unanswerable): What's the process for upgrading Kafka to version 4?

relevant: none; cited: ['RB-012']; tool calls: ["search_runbooks {'query': 'Kafka upgrade to version 4'}", "search_runbooks {'query': 'Kafka version upgrade rolling KRaft inter.broker.protocol.version', 'service': 'kafka-broker'}"]

**There's no runbook for upgrading Kafka to version 4.** I searched twice and found nothing on Kafka version upgrades: no rolling upgrade steps, protocol version changes or KRaft migration. Please don't improvise this from a broker-replacement procedure. Ask the team that owns `kafka-broker` (the owners of the Terraform module `kafka_broker`) whether they have an upgrade plan.

The closest document is **RB-012: Replacing a Kafka broker on instance storage**. It isn't an upgrade guide, but any rolling change to our brokers should respect its rules:

1. **Start healthy:** no under-replicated partitions (`kafka-topics.sh --describe --under-replicated-partitions` returns nothing)[1].
   ```
   kafka-topics.sh --describe --under-replicated-partitions
   ```
2. **Stop brokers cleanly:** `systemctl stop kafka` so it hands over leadership.[1]
3. **One broker at a time:** Wait until under-replicated partitions are zero before touching another broker.[1] Do not replace two brokers in the same AZ at once; with rack awareness, that could take two replicas of a partition offline.[2]
4. **Finish with** preferred leader election[1].

**Risk if an upgrade involves new instances:** Our self-managed Kafka brokers run on `i4i.2xlarge` instances with NVMe instance store for log segments. Instance store is ephemeral: data is lost when the instance is stopped, terminated, or the host fails.[3] If a broker is replaced, it starts empty and re-replicates its partitions from the other replicas. On our cluster this takes 2 to 4 hours[1].

The Kafka 4–specific steps aren't in our runbooks. Get a written procedure from the owning team before you start.
