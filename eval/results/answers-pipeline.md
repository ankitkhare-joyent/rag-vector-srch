# Answer eval, mode=pipeline (36 questions)

| metric | value |
|---|---|
| citation_hit | 0.969 |
| fact_coverage | 0.875 |
| abstention | 1.0 |
| p50_latency_ms | 20514 |
| p95_latency_ms | 33233 |
| avg_input_tokens | 2615 |
| avg_output_tokens | 793 |
| avg_tool_calls | 0 |

Input tokens for the agentic mode are summed over all its model calls. Ran with the earlier reranker (MiniLM-L12) and claude-opus-5-5 at medium effort. Abstention re-scored after widening the phrase check: all 4 unanswerable answers did decline, the first regex missed phrasings like "don't list" and "couldn't find".

## q01 (lexical): What does VcpuLimitExceeded mean and how do I fix it?

relevant: ['RB-020']; cited: ['RB-004', 'RB-013', 'RB-020']; tool calls: none

**`VcpuLimitExceeded` is a quota problem in our account.** Fix it by checking usage, requesting an increase, and shedding load in the meantime.

**What it means**
- EC2 On-Demand and Spot limits are counted in **vCPUs per instance family group per region per account**, not in instances.[1]
- It is not an AWS capacity shortage. That is `InsufficientInstanceCapacity` (It is not a quota problem: quotas fail with `VcpuLimitExceeded` instead[2]). If you see ICE instead, use RB-004.

**Steps (RB-020)**

1. **Check current quota and usage:**
   ```
   aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A
   ```
   CloudWatch publishes usage in the `AWS/Usage` namespace; we alarm at 80% of each quota.[3]

2. **Request an increase:**
   ```
   aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-1216C47A --desired-value 2048
   ```
   Standard increases are often approved within an hour; large jumps (more than double) or GPU quotas (`L-DB2E81BA`, `L-417A185B`) can take days and may need a support case with a business justification.[4]

3. **Free up headroom while you wait:**
   - Move part of the load to another instance family group with headroom (for example Spot quota is separate from On-Demand).[5]
   - Scale down idle fleets (RB-014) to free vCPUs.[5]

**If this is the CI runner fleet:** check RB-013. If you need to raise the ASG `MaxSize` (hard limit 400 per region; above that, request a vCPU quota increase first, see RB-020)[6].

For the future, plan ahead for launches (GUIDE-019) and peak events.[4]

## q02 (lexical): Which quota code covers running on-demand standard instances?

relevant: ['RB-020', 'GUIDE-019']; cited: ['RB-020']; tool calls: none

The quota code is **`L-1216C47A`**. It covers Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances[1].

**If you're hitting the limit:**

1. Confirm it's a quota problem. EC2 On-Demand and Spot limits are counted in **vCPUs per instance family group per region per account**, not in instances.[2] A `VcpuLimitExceeded` error means you've hit your account's quota. This is unlike `InsufficientInstanceCapacity`, which is an AWS capacity shortage (RB-004).[2]
2. Request an increase:
   ```
   aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-1216C47A --desired-value 2048
   ```
   Standard increases are often approved within an hour; large jumps (more than double) or GPU quotas (`L-DB2E81BA`, `L-417A185B`) can take days and may need a support case with a business justification.[3]
3. Use these workarounds while you wait:
   - Move part of the load to another instance family group with headroom (for example Spot quota is separate from On-Demand).[4] Standard Spot uses a different code: `L-34B43A08`[1].
   - Scale down idle fleets (RB-014) to free vCPUs.[4]

Source: RB-020.

## q03 (lexical): What should HttpPutResponseHopLimit be on EKS nodes?

relevant: ['POL-SEC-004']; cited: ['POL-SEC-004', 'RB-011']; tool calls: none

**Set it to `2` on EKS nodes.**

Per POL-SEC-004, the value is `2` on EKS nodes and Docker hosts, `1` elsewhere[1]. The reason is that containers add one network hop; with limit 1 pods cannot reach IMDS at all[1].

RB-011 agrees. It lists this as a common cause of NotReady nodes: IMDS hop limit set to 1, which breaks pods that need the node role (POL-SEC-004 requires 2 on EKS nodes)[2].

**Related required settings on the same nodes:**
- `HttpTokens`: `required`[1]
- `HttpEndpoint`: `enabled`[1]
- `InstanceMetadataTags`: `enabled`[1]

**If you find a node with limit 1:**
1. Fix it at the source. Launch templates managed by Terraform set these values[1], so correct the launch template in Terraform rather than patching the instance.
2. Replace the affected nodes using the RB-011 procedure:
   ```
   kubectl cordon <node>
   kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=10m
   aws autoscaling terminate-instance-in-auto-scaling-group --instance-id i-... --no-should-decrement-desired-capacity
   ```
3. If more than 3 nodes go NotReady at once, stop and look for a shared cause (AMI rollout, CNI version, AZ event) before replacing nodes.[3] A bad launch template change would be one such cause.

The runbooks don't include a command for changing the hop limit on a single running instance. The account-level default command in POL-SEC-004 only sets `--http-tokens required`. Use the Terraform-managed launch template.

## q04 (lexical): InsufficientInstanceCapacity when launching p4d.24xlarge in us-east-1a

relevant: ['RB-004']; cited: ['RB-004', 'RB-014']; tool calls: none

This is an **AWS capacity shortage in us-east-1a, not a quota problem**, so don't raise a quota. Quotas fail with `VcpuLimitExceeded` instead (see RB-020). Retrying the same request in the same AZ often keeps failing for minutes to hours.[1]

**What to do now (RB-004):**

1. **Switch AZs.** Retry in a different AZ. Our VPCs have subnets in every AZ listed for the region.[2]
2. **If it's an Auto Scaling group,** make sure the group spans all AZs and uses a mixed-instances policy, so a single type shortage does not block scaling.[2]
3. **Consider smaller GPU nodes.** Larger types are the hardest to get. Ask the ML team whether the job can run on more `g5.12xlarge` nodes instead of one `p4d.24xlarge`.[2]
4. **Escalate if production is blocked.** If ICE blocks a production scale-out for more than 30 minutes, open a severity 2 incident and an AWS support case of severity "Production system down", quoting the instance type, AZ and request IDs.[3]

**If you're restarting a stopped instance,** this failure is common. RB-014 notes it happens especially `p4d.24xlarge`[4].

**To prevent it next time:**
- Capacity Blocks for ML reserve GPU instances for a fixed future window (1 to 182 days). This is the preferred way to get `p4d` and `p5` capacity for training runs longer than a day.[5]
- On-Demand Capacity Reservations (ODCR) guarantee capacity in one AZ, billed whether used or not.[5] Create them at least 2 weeks ahead.
- Savings Plans and Reserved Instances give a discount but do **not** guarantee capacity unless they are zonal RIs.[5]

The runbooks don't include specific CLI commands for retrying in another AZ or booking a Capacity Block.

## q05 (lexical): What is the quota code for P instances?

relevant: ['RB-020']; cited: ['GUIDE-019', 'RB-004', 'RB-020']; tool calls: none

The quota code for **Running On-Demand P instances** is **`L-417A185B`**. | Running On-Demand P instances | `L-417A185B` |[1]

To check current usage, use the RB-020 command with the P quota code swapped in. RB-020's example uses the Standard code `L-1216C47A`.

```
aws service-quotas get-service-quota --service-code ec2 --quota-code L-417A185B
```

**Things to keep in mind:**
- Limits are counted in **vCPUs per instance family group per region per account**, not in instances.[2]
- If you're seeing `InsufficientInstanceCapacity` rather than `VcpuLimitExceeded`, it's not a quota issue. `InsufficientInstanceCapacity` (ICE) means AWS does not currently have enough capacity of the requested instance type in that Availability Zone.[3] Follow RB-004 instead.
- Quota requests can take several days (RB-020).[4] If you need relief now, RB-020's short-term workarounds are to move part of the load to another instance family group with headroom (for example Spot quota is separate from On-Demand)[5] or scale down idle fleets (RB-014) to free vCPUs.[5]

## q06 (lexical): How do I handle an instance-retirement scheduled event?

relevant: ['RB-021']; cited: ['RB-012', 'RB-021']; tool calls: none

**First, determine the instance type.** The fix depends on whether it's EBS-backed, instance-store, or in an Auto Scaling group.

**What the event means:** the host has degraded and the instance will be stopped or terminated on the date[1]. Events appear in `describe-instance-status` under `Events` and in the AWS Health Dashboard, usually with two weeks' notice.[2]

**By case:**

1. **In an Auto Scaling group:** No action is normally needed. The `scheduled-event-drainer` Lambda replaces instances in Auto Scaling groups automatically 48 hours before the event.[3]
2. **EBS-backed, standalone:** Stop and start before the date[1].
3. **`kafka-broker` (`i4i`):** An `instance-retirement` means data on the instance store will be lost. Follow RB-012 for brokers[4]. Do not stop and start it. Never stop and start a broker to "move it to new hardware" as you would for EBS-backed instances; that wipes its data, which is fine only if you follow this runbook.[5]
4. **`opensearch-data` (`i4g`):** Exclude the node from allocation (`cluster.routing.allocation.exclude._name`) and wait for shards to move before stopping.[4]

**Tracking:** An EventBridge rule on `AWS Health` events opens a ticket for the team in the instance's `Team` tag, 14 days ahead, and reminds again 3 days ahead[3]. Check that ticket for ownership.

**If there was no warning:** If the instance already failed unexpectedly, that is a status check failure, not a scheduled event; see RB-001.[6]

**Gaps:** These excerpts don't include the actual broker replacement steps from RB-012 or the exact stop/start or `describe-instance-status` CLI invocations. Open RB-012 directly before touching a broker.

## q07 (lexical): What did postmortem PM-2026-05 find as the root cause?

relevant: ['PM-2026-05']; cited: ['PM-2026-05', 'RB-002']; tool calls: none

**Root cause:** The index state management (ISM) policy that deletes log-style indices older than 30 days stopped running after an OpenSearch upgrade renamed a policy field.[1] Two monitoring gaps let it go unnoticed: the ISM policy silently failed after the upgrade and nothing alerted on ISM failures. The disk alert existed but went to a channel nobody watched at night.[2]

**How it escalated:**
1. Old indices accumulated for three weeks.[1]
2. On 2026-05-17 the data nodes' EBS volumes crossed the 95% flood-stage watermark, OpenSearch set every index to read-only, and indexing from `search-indexer` failed.[1]
3. Two nodes then ran completely out of disk and their shards went unassigned, turning the cluster red.[1]

**Impact:** 2026-05-17, 02:10 to 06:45 UTC. Severity: 1. Product search returned errors or stale results for 4.5 hours in `eu-central-1`.[3]

**If you're seeing similar disk growth now:** RB-002 says to open a ticket for the owning team with the growth rate (GiB per day) from the `disk_used_percent` graph. For OpenSearch, check whether index lifecycle (ISM) policies stopped deleting old indices; this was the cause in PM-2026-05.[4]

## q08 (lexical): What does StatusCheckFailed_System mean?

relevant: ['RB-001']; cited: ['RB-001']; tool calls: none

**`StatusCheckFailed_System` means the AWS host is bad, not your instance.** AWS has a problem with the hardware, power, or network of the underlying host. You cannot fix the host. The fix is to move the instance to new hardware by **stopping and starting** it (a reboot does not move it).[1]

**What to do (RB-001):**

1. Confirm which check failed:
   ```
   aws ec2 describe-instance-status --instance-ids i-... --include-all-instances
   ```
2. **If it's in an Auto Scaling group** (tag `aws:autoscaling:groupName`), do not repair it. Mark it unhealthy and let the group replace it[2]:
   ```
   aws autoscaling set-instance-health --instance-id i-... --health-status Unhealthy
   ```
3. **If it's standalone**, take an EBS snapshot of the root volume before any change.[2]
4. Stop, then start the instance (not reboot).

**Caution:** Instances with instance-store volumes (for example `i4i` and `i4g` families) lose their local data on stop, so follow the broker or data-node runbook instead of stopping blindly.[1] Instance-store families do not support recovery.[3]

**Auto recovery:** All standalone production instances must have the CloudWatch alarm `StatusCheckFailed_System >= 1 for 2 datapoints` with the `ec2:recover` action.[3] If this alarm fired, check whether recovery already happened before stopping manually.

**Contrast:** `StatusCheckFailed_Instance` is a problem *inside* the instance (kernel panic, full disk, OOM). Stopping and starting rarely helps on its own.[1]

Note: RB-001's overview says every instance has two status checks, but its later section also describes a third, `StatusCheckFailed_AttachedEBS`. That doesn't change the steps above.

## q09 (lexical): Which tag is used to exempt a GPU training run from the 72 hour auto-stop?

relevant: ['RB-014']; cited: ['RB-004', 'RB-014']; tool calls: none

Tag the instance with **`LongRun=true`** and **`LongRunTicket=<ticket>`**.

1. Apply both tags. Per RB-014's exemptions section, you should set `LongRun=true` plus `LongRunTicket=<ticket>` for training runs expected to exceed 72 hours.[1]
2. Watch the expiry. The tag is removed automatically after 14 days.[1] If your run goes past that, it falls back under the 72-hour rule.
3. Know what happens without the tag. Any GPU instance running more than 72 hours without the tag `LongRun=true`[2] gets this action: Notify owner, stop after 24 more hours[2].

**Minor conflict:** The auto-stop table in RB-014#1 only mentions `LongRun=true`. The exemptions section in RB-014#4 is more specific and also requires `LongRunTicket`. Set both.

**Caveats:**
- The excerpts don't say that `LongRun` exempts you from the `ml-training` idle rule (GPU utilization below 5% for **2 hours**[2] triggers a stop). Keep the GPUs busy.
- Instances without the CloudWatch agent's NVIDIA metrics cannot be evaluated and are reported as non-compliant.[2]
- Keep checkpointing. Training jobs must checkpoint to S3 at least every 30 minutes[3].
- For long runs, consider a Capacity Block instead. For runs longer than a day, book a Capacity Block instead of keeping instances running "just in case".[4] These reserve GPU instances for a fixed future window (1 to 182 days)[5]; see RB-004.

## q10 (lexical): What is the coverage target in POL-COST-002?

relevant: ['POL-COST-002']; cited: ['POL-COST-002']; tool calls: none

**The coverage target is 70%.** Per POL-COST-002, the goal is 70% of steady-state On-Demand compute spend under commitments. Spot, burst and short-lived workloads are excluded from the target.[1]

Related targets and rules in the same policy:

1. **Utilization:** above 95% of purchased commitments used each month.[1]
2. **Who buys:** Only FinOps purchases them; teams request coverage through the FinOps intake form.[2]
3. **Reporting:** FinOps publishes coverage and utilization monthly per team, using Cost Explorer and the EC2 inventory lakehouse.[3]
4. **Before buying:** Graviton migrations (GUIDE-009) and rightsizing (GUIDE-010) happen before buying, not after, so we do not commit to waste.[4]
5. **Capacity:** Savings Plans give a discount but do not reserve capacity; use On-Demand Capacity Reservations for that (RB-004).[4]

## q11 (semantic): The search cluster's data disks are almost full, what do I do right now?

relevant: ['RB-002', 'PM-2026-05']; cited: ['PM-2026-05', 'RB-002']; tool calls: none

**Grow the EBS volumes online now (RB-002). Don't delete shard data by hand.** In PM-2026-05, the data nodes' EBS volumes crossed the 95% flood-stage watermark, OpenSearch set every index to read-only[1], and the cluster went red.

1. **Confirm which mount is full:** `df -h` and `du -xh --max-depth=1 /data | sort -h`[2]
2. **Clear only safe files:** old heap dumps in `/data/dumps`, rotated logs older than 7 days, and orphaned temp files from failed jobs. Never delete Kafka log segments or OpenSearch shard directories by hand.[2]
3. **Grow each volume online:**
   ```
   aws ec2 modify-volume --volume-id vol-... --size <new GiB>
   aws ec2 describe-volumes-modifications --volume-id vol-...   # wait for "optimizing" or "completed"
   sudo growpart /dev/nvme1n1 1      # only if the filesystem sits on a partition
   sudo xfs_growfs /data             # XFS (our default)
   sudo resize2fs /dev/nvme1n1p1     # ext4
   ```
   Grow by at least 30% so the alert does not fire again next week.[2] In the postmortem the team grew them 40%.
4. **Check the 6-hour limit:** A volume can only be modified once every 6 hours. If you already modified it today, mitigate by deleting data or moving shards instead.[2]
5. **If the indices went read-only,** clear the block after you've freed space. The postmortem used `index.blocks.read_only_allow_delete: null`[3].

**After you've stabilized,** check whether the ISM retention policy is running. In PM-2026-05 it stopped running after an OpenSearch upgrade renamed a policy field. Old indices accumulated for three weeks.[1] The runbooks I have don't include commands for checking ISM. Use PM-2026-05 or ask the search team.

## q12 (semantic): How can I get a shell on a production box without SSH keys?

relevant: ['RB-008']; cited: ['POL-SEC-007', 'RB-008']; tool calls: none

Use **AWS Systems Manager Session Manager**. We do not use SSH keys for interactive access. Use AWS Systems Manager Session Manager, which needs no open inbound ports, logs every session to S3 and CloudWatch, and authenticates with your SSO role.[1] (RB-008)

**Steps**

1. **Check prerequisites.** The instance profile includes the managed policy `AmazonSSMManagedInstanceCore`. The instance can reach the SSM endpoints, either through the VPC interface endpoints (`ssm`, `ssmmessages`, `ec2messages`) or the egress proxy.[2] Locally you need AWS CLI v2 and the Session Manager plugin.[2]
2. **Log in and start the session:**
   ```
   aws sso login --profile prd-readonly
   aws ssm start-session --target i-0abc123 --profile prd-operator
   ```
   Note: RB-008 logs in with `prd-readonly` but starts the session with `prd-operator`. If the session fails with an auth error, make sure you've run `aws sso login` for the `prd-operator` profile too.
3. **If the instance shows "not connected":** Check that the instance appears in `aws ssm describe-instance-information`. If not, the agent is not registering.[3] Most common causes: missing instance profile policy, no route to the SSM endpoints, or a stopped agent after a full root disk.[3]
4. **Last resort:** Use the EC2 Serial Console as a fallback for instances that cannot boot or register (needs the `ec2-serial-console` permission in the break-glass role).[3]

**Break-glass:** The `prd-breakglass` SSO role allows Session Manager on every production instance. Using it pages the security on-call automatically and requires an incident ticket reference within 1 hour.[4]

**Don't open port 22.** Under POL-SEC-007, SSH (port 22) and RDP (port 3389) must never be open to the internet.[5] Also, the `bastion` hosts are being retired[5], so don't rely on them.

## q13 (semantic): Our nightly Spark jobs keep losing machines halfway through, how do we make them more reliable?

relevant: ['RB-003']; cited: ['RB-003']; tool calls: none

**Diversify the Spot instance types first.** Per RB-003, diversification is the single most effective fix.[1]

**Is it an incident?** Losing machines mid-job is normal: about 70% of `spark-batch` capacity runs on Spot. Spot instances can be reclaimed by AWS with a two-minute interruption notice. This is expected, not an incident, unless job SLAs are missed.[2] RB-003 says to act if more than 30% of the Spot fleet is interrupted within one hour, or a nightly job misses its 06:00 UTC SLA twice in a week[1].

**Steps (RB-003):**
1. Check the interruption frequency per instance type in the Spot placement score and the Spot Instance Advisor.[1]
2. Add instance types to the mixed-instances policy. We require at least six instance types across at least two families (for example `c7g.4xlarge`, `c6g.4xlarge`, `m7g.4xlarge`, `r7g.4xlarge`, `c7gd.4xlarge`, `m6g.4xlarge`).[1]
3. Use the `price-capacity-optimized` allocation strategy, never `lowest-price`.[1]
4. As a last resort, raise `OnDemandBaseCapacity` temporarily and tell the data team in #data-platform.[1]

**Check the job config too:**
- Executors should use graceful decommissioning: `spark.decommission.enabled=true` and `spark.storage.decommission.shuffleBlocks.enabled=true`[3]. With these, stages do not restart from scratch.[3]
- The driver always runs on On-Demand capacity; never schedule a driver on Spot.[3] If a driver is on Spot, a single interruption can kill the whole job.

The runbooks don't include the exact CLI commands for editing the mixed-instances policy or `OnDemandBaseCapacity`. Coordinate those changes with the data team in #data-platform.

## q14 (semantic): How do I tell if a server is too big for what it does?

relevant: ['GUIDE-010']; cited: ['GUIDE-026', 'PM-2026-03']; tool calls: none

**The excerpts I have don't explain how to tell if an instance is oversized.** None of them give rightsizing criteria such as CPU or memory utilization thresholds, lookback windows, or tooling commands. I won't guess at numbers.

**Closest fit: GUIDE-010.** GUIDE-026 points to it as the source on downsizing, so it's likely the rightsizing guide. Pull that document, or ask whoever owns cost and rightsizing guidance on the platform team.

**What the excerpts do say about sizing:**

1. **Each size step doubles capacity.** Each size step doubles vCPUs and memory: `large` = 2 vCPUs, `xlarge` = 4, `2xlarge` = 8, `4xlarge` = 16, `12xlarge` = 48, `24xlarge` = 96.[1] If an instance would fit comfortably in half its current vCPUs and memory, it's a candidate to drop one size.
2. **Savings are large.** Price roughly doubles with each step too, which is why downsizing one step saves about 50% (GUIDE-010).[1]
3. **Be careful with latency-sensitive services.** In PM-2026-03, because the instance refresh replaced half of the fleet at once, the healthy capacity was too small to absorb traffic.[2] If you downsize via instance refresh, avoid the setting that caused that incident: `MinHealthyPercentage=50`, too aggressive for a latency-sensitive service.[3]

If you send me GUIDE-010 or the relevant section, I can give you the exact thresholds and steps.

## q15 (semantic): Developers are complaining their builds wait a long time before starting

relevant: ['RB-013']; cited: ['RB-004', 'RB-013']; tool calls: none

This matches **RB-013: CI runner queue backlog**. First confirm it's a real backlog, then engage devex on-call.

**Confirm the symptoms (RB-013)**
1. Check how long jobs have been waiting. The runbook symptom is that developers report jobs "queued" for more than 5 minutes.[1]
2. Check the queue metric. The metric `ci.queue.pending_jobs` is above 50 for 10 minutes, which pages devex on-call.[1]
   - If it's over 50 for 10+ minutes, devex on-call should already have been paged. Find out who is on point and coordinate with them.
   - If it's below that threshold, the wait may be specific to certain jobs or runners rather than a fleet-wide backlog.

**What I can't tell you**
The excerpt I have from RB-013 only covers the **Symptoms** section. It doesn't include diagnosis or remediation steps, such as how to scale runners or clear the queue. I won't guess at those. Open the full **RB-013** for the remediation steps, or hand off to **devex on-call**, who own this alert.

**One thing to rule out**
If CI runners are EC2-backed and failing to launch, the cause may be capacity rather than CI itself. On-Demand Capacity Reservations (ODCR) guarantee capacity in one AZ[2], which suggests **RB-004 (InsufficientInstanceCapacity launch errors)** covers that scenario. Only the "Guaranteeing capacity" part of RB-004 is in my excerpts, though, so treat it as a lead to check, not a confirmed cause.

## q16 (semantic): Is it safe to reboot a Kafka machine to move it onto healthy hardware?

relevant: ['RB-012']; cited: ['RB-001', 'RB-012']; tool calls: none

**No. A reboot won't move the broker to healthy hardware, and stop/start (which does) wipes its data. Replace the broker using RB-012 instead.**

**Why:**
- The fix is to move the instance to new hardware by stopping and starting it (a reboot does not move it).[1]
- Brokers run on `i4i.2xlarge` instances with NVMe instance store for log segments. Instance store is ephemeral: data is lost when the instance is stopped, terminated, or the host fails.[2]
- Never stop and start a broker to "move it to new hardware" as you would for EBS-backed instances; that wipes its data, which is fine only if you follow this runbook.[3]

**What to do (RB-012):**
1. Confirm there are no under-replicated partitions. This command should return nothing:
   ```
   kafka-topics.sh --describe --under-replicated-partitions
   ```
2. Stop the broker cleanly so it hands over leadership:
   ```
   systemctl stop kafka
   ```
3. Launch the replacement from the `kafka-broker` launch template with the same `broker.id` in the same AZ. Terraform module `kafka_broker` does this when you taint the old instance.[4]
4. Let the new broker re-replicate. On our cluster this takes 2 to 4 hours; throttle it with `leader.replication.throttled.rate` at 200 MB/s so client traffic is not affected.[4]
5. Wait until under-replicated partitions are zero. Only one broker may be replaced at a time.[4]
6. Run preferred leader election at the end.

**Don't:**
- Do not replace two brokers in the same AZ at once; with rack awareness, that could take two replicas of a partition offline.[5]
- Do not copy log directories between hosts manually.[5]

If the instance has a scheduled retirement event, also see RB-021.

## q17 (semantic): How much cheaper are Arm instances and what breaks when moving to them?

relevant: ['GUIDE-009']; cited: ['GUIDE-009']; tool calls: none

**Graviton (Arm) instances are typically 20–30% cheaper per unit of work.** The runbooks here don't list what breaks when you move. The migration steps only imply where problems come up.

**Cost:** For our services they are typically **20 to 30% cheaper per unit of work** than the equivalent Intel (`i`) or AMD (`a`) types, with lower power use.[1] `spark-batch`, `search-indexer` and `opensearch-data` already run on Graviton.[1]

**Risks implied by the GUIDE-009 migration steps:**
1. **Images built only for amd64.** You need multi-arch images:
   ```
   docker buildx build --platform linux/amd64,linux/arm64
   ```
   Our CI runners produce both by default since March 2026.[2] Older images may lack an arm64 build.
2. **Performance regressions.** Run the service's load test on one Graviton instance and compare p99 latency and throughput per dollar.[2]
3. **Pods landing on the wrong architecture in EKS.** Add an arm64 managed node group and use node affinity on `kubernetes.io/arch`; remove the amd64 group when all pods have moved.[2]
4. **Savings Plans coverage.** Compute Savings Plans apply to Graviton automatically, EC2 Instance Savings Plans do not move between families (POL-COST-002).[2]

For ASGs, roll out gradually: add the Graviton type to the mixed-instances policy with a low weight first, then shift traffic over two weeks.[2]

**Gap:** None of these excerpts list specific incompatibilities, such as native libraries, agents or arm64 AMIs. Check the rest of **GUIDE-009**, since only the overview and migration-steps sections were retrieved. The **FinOps team** is the closest fit for cost questions.

## q18 (semantic): A Kubernetes worker stopped reporting to the control plane, what's the procedure?

relevant: ['RB-011']; cited: ['RB-011']; tool calls: none

**First check how many nodes are affected:** if more than 3 nodes go NotReady at once, stop and look for a shared cause (AMI rollout, CNI version, AZ event) before replacing nodes.[1] For a single node, follow RB-011.

A node goes NotReady when the kubelet stops posting status to the control plane for 40 seconds.[2]

**Procedure (RB-011):** Nodes are cattle. Cordon and drain, then terminate and let the Auto Scaling group replace it:[1]

1. Cordon and drain:
   ```
   kubectl cordon <node>
   kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=10m
   ```
   Respect PodDisruptionBudgets; if a drain hangs, find the blocking PDB rather than forcing.[1]
2. Terminate the instance. The ASG will replace it:
   ```
   aws autoscaling terminate-instance-in-auto-scaling-group --instance-id i-... --no-should-decrement-desired-capacity
   ```

**Common causes to note for follow-up:**
- **Disk pressure.** Image garbage collection starts at 85% usage. Our node AMI uses a 100 GiB root volume; grow it in the launch template if this repeats.[3]
- **IP exhaustion.** Pods stuck in `ContainerCreating` with `failed to assign an IP address` mean the subnet ran out of IPs.[3]
- **Expired kubelet certificate.** This can happen after a node was stopped for weeks.[3]
- **IMDS hop limit.** A hop limit set to 1 breaks pods that need the node role (POL-SEC-004 requires 2 on EKS nodes).[3]

## q19 (semantic): Who decides on the severity when production is down and how do I start an incident?

relevant: ['GUIDE-024']; cited: ['GUIDE-024', 'RB-004']; tool calls: none

**Declare now from Slack. You pick the severity when you declare, and if you're unsure, go higher.**

**Starting the incident**

1. In Slack, run:
   ```
   /incident declare sev2 <short title>
   ```
   The bot creates the channel, starts the timeline and pages the on-call of the service you name.[1] GUIDE-024 only shows the `sev2` form. I'm assuming `sev1` works the same way, but the runbook doesn't confirm it.
2. Make sure the affected resources have the `Team` tag. Ownership comes from the `Team` tag on the affected resources (POL-TAG-001), so untagged resources slow down paging.[1]
3. If AWS is the cause, still declare an incident for our impact, open an AWS support case, and link the AWS event ARN in the incident channel.[2]

**Choosing the severity**

- **Sev 1:** Customer-facing outage or data loss for a major service (checkout, search, fulfillment), or a security breach[3]. A production-down outage on a major service fits here.
- **Sev 2:** Major degradation, partial outage, or risk of a severity 1 within hours[3].
- **Sev 2 for capacity errors:** RB-004 sets this for one specific case: If ICE blocks a production scale-out for more than 30 minutes, open a severity 2 incident[4].
- When in doubt, declare the higher severity; downgrading is cheap.[3]

**Who decides**

GUIDE-024 doesn't say who assigns the initial severity. In practice, whoever runs the declare command sets it. After that, the **Incident commander** coordinates and decides; does not debug.[5] If the severity needs to be re-evaluated, the incident commander is the closest fit. Ask the SRE team, who own GUIDE-024, if you need a firmer answer.

## q20 (semantic): We deleted data by accident on a volume, how do we get it back?

relevant: ['RB-025']; cited: ['RB-025']; tool calls: none

Restore a new volume from the most recent snapshot taken **before** the deletion (RB-025). Don't overwrite the existing volume.

**Check first:** Data Lifecycle Manager takes daily snapshots of every volume tagged `Backup=daily` at 03:00 UTC and keeps 14 of them; weekly snapshots are kept for 8 weeks.[1] Root volumes are not backed up because instances are rebuilt from the golden AMI (RB-017).[1] If the data was on the root volume or the volume isn't tagged, there may be no snapshot.

**Steps:**

1. Find the snapshot. Pick one with a timestamp before the deletion:
   ```
   aws ec2 describe-snapshots --owner-ids self --filters Name=tag:Service,Values=<service>
   ```
2. Create a volume in the **same Availability Zone** as the target instance; volumes cannot attach across AZs[2]:
   ```
   aws ec2 create-volume --snapshot-id snap-... --availability-zone eu-central-1a --volume-type gp3 --tag-specifications ...
   ```
3. Expect slow first reads. A volume created from a snapshot loads blocks lazily from S3, so first reads are slow. For databases, enable Fast Snapshot Restore on the snapshot beforehand (costs extra per hour per AZ), or pre-warm by reading every block with `fio`.[2]
4. Attach the volume, mount it read-only first, check the data, then switch the application over.[2] If only some files were lost, you can copy them back from the read-only mount instead of switching the whole volume.
5. Keep the old volume, detached and tagged `RetainUntil`, for 7 days in case you need to compare.[2]

**Note:** Anything written after the snapshot (up to about 24 hours with daily snapshots) won't be in the restored copy. Reconcile it from the old volume before you retire that volume.

## q21 (semantic): What do the letters in r7gd.4xlarge mean?

relevant: ['GUIDE-026']; cited: ['GUIDE-026']; tool calls: none

Per GUIDE-026, an instance type like `r7gd.4xlarge` has four parts: **family** (`r`), **generation** (`7`), **attributes** (`gd`) and **size** (`4xlarge`).[1]

| Part | Value | Meaning |
|---|---|---|
| Family | `r` | Instance family. The excerpts don't say what `r` stands for. |
| Generation | `7` | 7th generation |
| Attribute | `g` | AWS Graviton (Arm) processor, for example `m7g` (see GUIDE-009).[2] |
| Attribute | `d` | local NVMe instance store included, for example `c7gd`.[2] |
| Size | `4xlarge` | Instance size within the family |

Other attribute letters you may see: `i`: Intel processor, for example `m7i`.[2] `a`: AMD processor, for example `c7a`.[2] `n`: enhanced networking bandwidth; `e`: extra memory or storage.[2]

**Gaps:**
- The retrieved runbooks don't define what the `r` family is for, or the vCPU and memory of `4xlarge`. Check the rest of GUIDE-026 (the family-letter section wasn't in these excerpts) or AWS's instance type documentation.
- `g` means Graviton (Arm), so make sure your AMI and binaries are arm64. GUIDE-009 covers Graviton.

## q22 (semantic): Checkout got slow right after we rolled out a new machine image, has this happened before?

relevant: ['PM-2026-03']; cited: ['PM-2026-03']; tool calls: none

**Yes, this has happened before: PM-2026-03 (2026-03-12).** If you're seeing it now, follow what resolved that incident:

1. **Confirm correlation.** Check the ASG activity history for a recent instance refresh. Last time, correlation with the instance refresh found from the ASG activity history[1] took 25 minutes after the alert.
2. **Cancel the instance refresh** on the affected ASG.
3. **Roll back to the previous launch template version.** Launch template versions made rollback a single command.[2]

The excerpts don't include the exact cancel or rollback commands, so check the ASG/instance-refresh runbook or RB-017 (golden AMI) for those.

**What happened last time**
- **Impact:** p99 checkout latency rose from 280 ms to 2.4 s in `us-east-1`; about 3% of checkouts timed out.[3] It lasted 75 minutes.
- **Root cause:** The new AMI shipped a kernel with a changed default for transparent huge pages, which caused long JVM garbage-collection pauses under load.[4]
- **Why it got worse:** Because the instance refresh replaced half of the fleet at once, the healthy capacity was too small to absorb traffic.[4]

**Fixes already in place.** If any of these didn't apply to this rollout, it's a strong lead:
- Instance refresh for `checkout-api` now uses `MinHealthyPercentage=90` and checkpoints at 10%, 50%[5]
- AMI pipeline runs a 30-minute JVM load test before promotion[5]
- Pin `transparent_hugepage=madvise` in the AMI build[5]

Worth checking: was this refresh run at `MinHealthyPercentage=90` with checkpoints, and does the new AMI still pin `transparent_hugepage=madvise`?

## q23 (semantic): Can I open port 22 to the internet for a quick debug session?

relevant: ['POL-SEC-007']; cited: ['POL-SEC-007', 'RB-008']; tool calls: none

**No. Port 22 must never be opened to the internet. Use SSM Session Manager instead.**

**Why not**
- Per POL-SEC-007, SSH (port 22) and RDP (port 3389) must never be open to the internet. Interactive access goes through AWS Systems Manager Session Manager (RB-008).[1]
- The AWS Config rule `restricted-ssh`[2] will catch it, and violations page the security on-call within 15 minutes.[2]
- Security automatically revokes rules that open 22 or 3389 to the internet within 1 hour, and notifies the team owning the security group. Opening it again without an exception counts as a security incident.[3]

**What to do instead (RB-008)**

Session Manager needs no open inbound ports, logs every session to S3 and CloudWatch, and authenticates with your SSO role.[4]

1. Log in and start a shell:
   ```
   aws sso login --profile prd-readonly
   aws ssm start-session --target i-0abc123 --profile prd-operator
   ```
2. If you need to reach a port on or through the instance, use port forwarding. For example, for a database proxy on 5432:
   ```
   aws ssm start-session --target i-0abc123 --document-name AWS-StartPortForwardingSession \
     --parameters portNumber=5432,localPortNumber=15432
   ```

Replace `i-0abc123` with your instance ID.

**Note on bastions:** The `bastion` hosts are being retired; their port 22 is restricted to the corporate VPN CIDR `10.200.0.0/16`.[1] Don't plan around them.

If SSM doesn't work on the instance, the excerpts I have don't cover how to fix that or how to request an exception. Check the rest of RB-008, or contact the security team that owns POL-SEC-007.

## q24 (semantic): What labels must every VM carry for cost allocation?

relevant: ['POL-TAG-001']; cited: ['POL-TAG-001']; tool calls: none

Under **POL-TAG-001**, every VM must carry **five required tags**. Tags drive cost allocation, ownership lookups during incidents, and automation. Every EC2 instance, EBS volume and snapshot must carry the required tags below.[1]

**Required tags**

| Key | Example | Rule |
|---|---|---|
| `Name` | `checkout-api-prd-a` | Lowercase, service name plus environment |
| `Environment` | `prd` | One of `prd`, `stg`, `dev`, `sandbox` |
| `Team` | `payments` | Must match a team in the on-call directory |
| `Service` | `checkout-api` | Must match the service catalog |
| `CostCenter` | `cc-4821` | Four digits after `cc-`; finance maps it to a budget |

`CostCenter` is the tag that ties spend to a budget. The policy requires all five tags on every instance, not just the cost-related ones.

**Optional:** Optional but encouraged: `ManagedBy` (`terraform`, `eksctl`, `manual`), `DataClassification` (`public`, `internal`, `confidential`).[2]

**Auto-scaled capacity:** Auto Scaling groups must propagate tags to instances at launch (`PropagateAtLaunch=true`). EKS managed node groups inherit tags through the launch template.[2] If instances are missing tags, check the ASG or launch template first, not the individual instances.

The excerpts don't include a command to audit or fix missing tags. For that, ask the policy owner for POL-TAG-001. For questions about cost reporting, contact FinOps.

## q25 (semantic): How often are base images rebuilt and how old can they get in production?

relevant: ['RB-017']; cited: ['RB-017', 'RB-025']; tool calls: none

**Rebuild cadence and max age (RB-017):**

1. **Scheduled rebuilds:** Images are rebuilt on the first Tuesday of every month, and out of cycle within 72 hours for critical CVEs (CVSS 9.0 or higher).[1] All production instances boot from a **golden AMI** built by the platform team with Packer.[1]

2. **Maximum AMI age in production:** A production instance must not run an AMI older than **30 days** (60 days for instance-store fleets such as `kafka-broker`, because each replacement re-replicates data).[2]

3. **Tracking offenders:** The weekly compliance report lists offenders by `Team` tag.[2]

**If you need to bring a fleet into compliance:**
- **Auto Scaling groups:** update the launch template to the new SSM parameter version and start an instance refresh. Use `MinHealthyPercentage=90` for latency-sensitive services.[3]
- **EKS node groups:** update the node group's AMI release version; nodes are drained and replaced one AZ at a time.[3]
- **Standalone instances:** replace, do not patch in place, unless the owning team has an approved exception.[3]
- **Rollback:** point the launch template at the previous version; old AMIs are kept for 90 days.[3]

Note: root volumes aren't a recovery path here. Root volumes are not backed up because instances are rebuilt from the golden AMI (RB-017).[4]

## q26 (semantic): How did we shut down the old Windows reporting servers?

relevant: ['RB-018']; cited: ['RB-018']; tool calls: none

The `legacy-reporting` shutdown is documented in **RB-018**. The service (finance team, `m5.large` and `m5.xlarge`, about 60% Windows Server) was replaced by dashboards on the Trino lakehouse. It was decommissioned in March 2026. This runbook records how, and is the template for future decommissions.[1]

**Steps we followed (RB-018 checklist):**

1. **Confirmed there was no traffic for 30 days.** ALB request count is zero and no scheduled tasks ran. Owners sign off in the decommission ticket.[2]
2. **Took final backups.** We created EBS snapshots of every data volume, tagged `RetainUntil=<date 90 days out>` and `DecommissionTicket=<id>`[2]. Finance requires report archives for 7 years; those were exported to S3 Glacier Deep Archive, not kept as snapshots.[2]
3. **Stopped the instances, then waited 14 days.** Stopped instances cost only their EBS storage, and the wait catches forgotten dependencies.[2]
4. **Terminated the instances and removed related resources.** Delete the Auto Scaling groups, launch templates, target groups, DNS records and security groups.[2]
5. **Handled licenses.** Windows license-included instances stop billing at termination; tell procurement to cancel any SQL Server licenses brought under BYOL.[2]
6. **Cleaned up commitments.** Check whether Reserved Instances or EC2 Instance Savings Plans covered the `m5` family in that region, and resell or reassign them (POL-COST-002).[2]
7. **Removed monitoring.** This covered dashboards, alerts and on-call routes for the service.[2]

**Outcome:** The last instances were terminated on 2026-03-28. Snapshots expire on 2026-06-26. Monthly EC2 spend for the finance account fell by about 85%.[3]

RB-018 doesn't list specific CLI commands for these steps. If you're running a similar decommission, use RB-018 as the template and POL-COST-002 for the commitments step.

## q27 (semantic): The PgBouncer boxes in front of the payments database are failing health checks

relevant: ['RB-023']; cited: ['RB-001', 'RB-023']; tool calls: none

**First, check whether one proxy is failing or all of them. That decides the path.** If all proxies fail at once, the problem is the database or the network, not the proxies. Page the payments database owner and check the Aurora cluster status.[1]

**If only one or a few proxies are failing (RB-023):**

1. Check NLB target health and which proxy is failing.[1]
2. Confirm which EC2 check is failing:
   ```
   aws ec2 describe-instance-status --instance-ids i-... --include-all-instances
   ```
3. **The EC2 status check failed:** the CloudWatch recovery alarm (RB-001) recovers it on new hardware with the same private IP. Wait 10 minutes before intervening.[1]
4. **The instance is healthy but PgBouncer is stuck:** connect via SSM (RB-008) and run:
   ```
   systemctl restart pgbouncer
   ```
   Connections on that proxy drop; clients retry.[1]
5. **The logs show `auth failed`:** A proxy that failed to fetch credentials logs `auth failed` for every client; restarting PgBouncer re-reads them.[2]

**Cautions:**
- These proxies are standalone. Each has a fixed private IP registered with the payment processor's allow-list.[3] There is no Auto Scaling group to replace them.
- RB-001's generic advice for a failed system check is "stop, then start." For these proxies, follow the more specific RB-023 instead and wait for the recovery alarm first.
- If you do have to intervene by hand, take an EBS snapshot of the root volume before any change.[4]
- **Escalate:** If more than five instances in one Availability Zone fail system checks within 15 minutes, treat it as an AWS event: open a severity 2 incident (see GUIDE-024) and check the AWS Health Dashboard[5].

## q28 (semantic): What did we learn from opening the Singapore region?

relevant: ['GUIDE-019']; cited: ['GUIDE-019']; tool calls: none

From the `fulfillment-edge` launch in `ap-southeast-1` (GUIDE-019), there are three lessons. In April 2026 the logistics team launched `fulfillment-edge` in `ap-southeast-1` (Singapore), our first service there. These are the steps and lessons, kept as the checklist for the next region launch.[1]

**Lessons learned**

1. **Request quotas early.** The vCPU quota increase took 6 days; request it earlier.[2] The checklist says to do this four weeks before launch: request increases for "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances" (quota code `L-1216C47A`), Elastic IPs and Application Load Balancers. Quota requests can take several days (RB-020).[3]
2. **Add the region to tagging enforcement.** We forgot to add the region to the tagging policy's enforced regions, so the first week's instances lacked `CostCenter`.[2]
3. **Plan for cross-region data latency.** Latency to the `eu-central-1` order database was 160 ms; read replicas in-region fixed it.[2]

**Related launch-week practices**
- Start with On-Demand capacity only; add Spot after two weeks of stable traffic.[4]
- Load test from the region at 2x the expected peak.[4]
- GuardDuty, Config rules and the IMDSv2 account default enabled in the region before any workload.[3]

For the next region launch, use GUIDE-019's "Four weeks before" section as the checklist. Add the tagging-policy region step to it, because the excerpt doesn't list that step explicitly.

## q29 (multi): Scaling out CI fails with launch errors. Is it a quota or an AWS capacity problem, and what do I do for each?

relevant: ['RB-013', 'RB-004', 'RB-020']; cited: ['RB-004', 'RB-013', 'RB-020']; tool calls: none

**Check the ASG's activity history for the error text.** Check the group's activity history for `InsufficientInstanceCapacity` (RB-004) or `VcpuLimitExceeded` (RB-020).[1]

Also confirm you're not just at max size:
```
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names ci-runner-prd-asg
```
If `DesiredCapacity == MaxSize`, raise `MaxSize` (hard limit 400 per region; above that, request a vCPU quota increase first, see RB-020).[1]

**`VcpuLimitExceeded`: quota problem (RB-020)**
- This is a quota problem in your account[2]. Limits are counted in **vCPUs per instance family group per region per account**, not in instances.[2]
- **Fix:** request a vCPU quota increase. The RB-020 excerpt I have doesn't include the request steps or quota codes, so follow the full RB-020.

**`InsufficientInstanceCapacity`: AWS capacity problem (RB-004)**
- AWS does not currently have enough capacity of the requested instance type in that Availability Zone.[3] Retrying the same request in the same AZ often keeps failing for minutes to hours.[3]
- **Fix:**
  1. Read the full error. It names the instance type and AZ[4].
  2. Retry in a different AZ. Our VPCs have subnets in every AZ listed for the region.[4]
  3. Make sure the group spans all AZs and uses a mixed-instances policy, so a single type shortage does not block scaling.[4]
  4. Escalate if it persists. If ICE blocks a production scale-out for more than 30 minutes, open a severity 2 incident and an AWS support case of severity "Production system down", quoting the instance type, AZ and request IDs.[5]

**If neither error appears:** A broken runner AMI can boot without registering. Compare running instances to registered runners; if they differ, roll back the launch template to the previous version.[1]

## q30 (multi): Before buying Savings Plans for a fleet, what cost work should happen first?

relevant: ['POL-COST-002', 'GUIDE-009', 'GUIDE-010']; cited: ['GUIDE-009', 'POL-COST-002']; tool calls: none

**Do Graviton migration and rightsizing first, then request the commitment through FinOps.** Per POL-COST-002:

1. **Migrate and rightsize before buying.** Graviton migrations (GUIDE-009) and rightsizing (GUIDE-010) happen before buying, not after, so we do not commit to waste.[1] GUIDE-009's last step is to update Savings Plans forecasts; Compute Savings Plans apply to Graviton automatically, EC2 Instance Savings Plans do not move between families (POL-COST-002).[2] The excerpts don't include GUIDE-010's steps, so check that guide directly.

2. **Exclude fleets that are going away.** Do not buy commitments for workloads planned for decommission or migration within the term (for example the old `m5` fleet before RB-018).[1]

3. **Check existing commitments if you're changing families.** Changing a large fleet's instance family requires a FinOps check that no EC2 Instance Savings Plan would become unused.[1]

4. **Request through FinOps. Don't buy it yourself.** Only FinOps purchases them; teams request coverage through the FinOps intake form.[3] The defaults are 1-year no-upfront by default; 3-year only for platforms with a committed multi-year roadmap (`kafka-broker`, `opensearch-data`).[4]

**Caveat:** a Savings Plan is not a capacity guarantee. Savings Plans give a discount but do not reserve capacity; use On-Demand Capacity Reservations for that (RB-004).[1]

For sizing, the targets are **Coverage target: 70%** of steady-state On-Demand compute spend under commitments[4] and **Utilization target: above 95%** of purchased commitments used each month.[4]

## q31 (multi): An i4i Kafka broker got an AWS retirement notice. What exactly do I do?

relevant: ['RB-021', 'RB-012']; cited: ['RB-012', 'RB-021']; tool calls: none

**Don't stop/start the broker to move hosts. Replace it using RB-012.** For `kafka-broker` (`i4i`) ... an `instance-retirement` means data on the instance store will be lost. Follow RB-012 for brokers[1]. Never stop and start a broker to "move it to new hardware" as you would for EBS-backed instances; that wipes its data, which is fine only if you follow this runbook.[2] Retirement notices usually[3] come with two weeks' notice, so check the event date before you start.

**Procedure (RB-012):**

1. Confirm the cluster is healthy. This should return nothing:
   ```
   kafka-topics.sh --describe --under-replicated-partitions
   ```
2. Stop the broker cleanly so it hands off leadership:
   ```
   systemctl stop kafka
   ```
3. Launch the replacement from the `kafka-broker` launch template **with the same `broker.id`** in the same AZ. Terraform module `kafka_broker` does this when you taint the old instance.[4]
4. Let the new broker re-replicate. On our cluster this takes 2 to 4 hours; throttle it with `leader.replication.throttled.rate` at 200 MB/s so client traffic is not affected.[4]
5. Wait until under-replicated partitions are back to zero. Re-run the command from step 1 to check.
6. Run preferred leader election at the end.[4] RB-012 doesn't give the exact command for this.

**Guardrails:**
- Only one broker may be replaced at a time.[4]
- Do not replace two brokers in the same AZ at once; with rack awareness, that could take two replicas of a partition offline.[5]
- Do not copy log directories between hosts manually.[5]

Durability comes from Kafka replication (replication factor 3, `min.insync.replicas=2`), not from the disk[6]. That's why step 1 matters: don't start if anything is already under-replicated.

## q32 (multi): Why can pods on EKS not reach instance metadata after we enforced IMDSv2?

relevant: ['POL-SEC-004', 'RB-011']; cited: ['POL-SEC-004', 'RB-011']; tool calls: none

**The likely cause is that the IMDS hop limit is set to 1 on your nodes. Raise it to 2 on every EKS node.**

**Why:** Under IMDSv2, the PUT response that carries the session token has a hop limit. Containers add one network hop; with limit 1 pods cannot reach IMDS at all[1]. RB-011 lists this as a known cause of NotReady nodes: IMDS hop limit set to 1, which breaks pods that need the node role (POL-SEC-004 requires 2 on EKS nodes).[2]

**Fix:**

1. Set the hop limit to 2 on each affected node:
   ```
   aws ec2 modify-instance-metadata-options --instance-id i-... --http-tokens required --http-put-response-hop-limit 2
   ```
   No reboot is needed.[3]
2. Make the change permanent in the node group's launch template. Launch templates managed by Terraform set these values[1], so check that the EKS template uses `2`. The account-level default only enforces `--http-tokens required` and doesn't set the hop limit for you.
3. If pods still fail after that, check the client code. Old scripts using `curl http://169.254.169.254/...` without first fetching a token with `PUT /latest/api/token` will break.[3] All AWS SDKs released after 2020[3] support IMDSv2.

**Note on a conflict:** The fix command in POL-SEC-004 uses hop limit `2` for every instance. However, the policy's settings table says `2` on EKS nodes and Docker hosts, `1` elsewhere[1]. The value of 2 is correct for EKS. For non-container hosts, follow the table and use 1.

Don't fall back to `HttpTokens=optional`. A Service Control Policy denies `ec2:RunInstances` when `ec2:MetadataHttpTokens` is not `required`.[4]

## q33 (unanswerable): How do I rotate the TLS certificate on the internal load balancer?

relevant: none; cited: ['POL-SEC-007', 'RB-023']; tool calls: none

**The runbooks I have don't cover TLS certificate rotation on the internal load balancer.** None of the excerpts include a procedure, commands or a document ID for it, so I won't guess at steps.

**Related documents that do *not* answer this:**

1. **RB-023 (payments-db-proxy failover)** mentions a load balancer: Clients connect through a Network Load Balancer on port 6432.[1] It doesn't cover certificates. Its "Credentials" section is about database credentials, not TLS. Proxies fetch database credentials at boot from the secrets manager; they are rotated every 30 days.[2]
2. **POL-SEC-007 (Security group rules for EC2)** only covers network access to load balancers, such as Reference other security groups instead of CIDR ranges for traffic inside a VPC (for example, `checkout-api` allows 8080 only from the ALB security group).[3]

**What to do next:**

1. Find out which internal load balancer you mean and which team owns it. Every security group must carry a `Team` tag under POL-SEC-007, so the load balancer's security group should identify the owner.
2. Escalate to that team, or to whoever owns the certificate and PKI process, for the approved procedure.
3. If this is the payments NLB, involve the RB-023 owners before touching anything.
4. Once the procedure is confirmed, it should be written up as a runbook so it's covered next time.

## q34 (unanswerable): What is the on-call phone number for the payments team?

relevant: none; cited: ['GUIDE-024', 'POL-TAG-001']; tool calls: none

**The runbooks don't list a phone number for the payments on-call.** None of these excerpts contain contact details. Instead, page them through the incident bot:

1. **Declare the incident in Slack** (GUIDE-024): Type `/incident declare sev2 <short title>` in Slack. The bot creates the channel, starts the timeline and pages the on-call of the service you name.[1]
   ```
   /incident declare sev2 <short title>
   ```
   Name the affected payments service (e.g. `checkout-api`) so the right rotation is paged.

2. **Check the `Team` tag on affected resources.** Ownership comes from the `Team` tag on the affected resources (POL-TAG-001), so untagged resources slow down paging.[1] Under POL-TAG-001, the `Team` tag (example `payments`) Must match a team in the on-call directory[2].

**Where to find actual contact details:** POL-TAG-001 references the **on-call directory**, which is the closest fit for a phone number. That directory isn't in the runbooks I have.

If this involves `checkout-api` connection errors or timeouts, also see **RB-023 (payments-db-proxy failover)**.

## q35 (unanswerable): How do I configure cross-region replication for our DynamoDB tables?

relevant: none; cited: ['GUIDE-019', 'RB-025']; tool calls: none

**The runbooks don't cover DynamoDB cross-region replication.** None of the excerpts mention DynamoDB, so I can't give you a vetted procedure, commands or settings for it.

The closest related material covers other services:

- **GUIDE-019 (new region launch)** is the best fit if you're replicating because you're expanding into a new region. Its lessons learned note that latency to the `eu-central-1` order database was 160 ms; read replicas in-region fixed it[1]. That was a database fix, not DynamoDB, and the guide gives no replication steps.
- **RB-025 (EBS snapshot restore)** covers cross-region copying for EBS only: Copy the snapshot first (`aws ec2 copy-snapshot`). Encrypted snapshots need the KMS key shared with the target account.[2] This doesn't apply to DynamoDB tables.

**Next steps:**
1. Escalate to whoever owns the DynamoDB tables or the data layer. None of the excerpts name an owning team.
2. If this is part of a region launch, follow GUIDE-019's prerequisites (quotas, networking, security baseline) alongside the replication work.
3. Ask that the eventual procedure be written up as a runbook so the next on-call has it.

## q36 (unanswerable): What's the process for upgrading Kafka to version 4?

relevant: none; cited: ['GUIDE-010', 'RB-012']; tool calls: none

**The runbooks I have don't cover a Kafka version upgrade (to 4 or any version).** There's no procedure, version-compatibility guidance, or config/protocol migration steps in the excerpts. Don't improvise one from the material below.

**Closest fit: RB-012 (Replacing a Kafka broker on instance storage).** It covers swapping broker hosts, not changing Kafka versions. Ask the owners of RB-012 or the `kafka_broker` Terraform module whether an upgrade runbook exists.

If an upgrade plan involves restarting or replacing brokers, these RB-012 guardrails still apply:

1. Brokers use ephemeral storage. They run on `i4i.2xlarge` instances with NVMe **instance store** for log segments. Instance store is ephemeral: data is lost when the instance is stopped, terminated, or the host fails.[1]
2. Check cluster health before touching anything. no under-replicated partitions[2]:
   ```
   kafka-topics.sh --describe --under-replicated-partitions
   ```
3. Do one broker at a time. Wait until under-replicated partitions are zero before touching another broker. Only one broker may be replaced at a time.[2]
4. Never stop/start a broker casually. Never stop and start a broker to "move it to new hardware" as you would for EBS-backed instances; that wipes its data, which is fine only if you follow this runbook.[3]
5. Do not copy log directories between hosts manually.[4]
6. Don't resize as part of the change. Per GUIDE-010, `kafka-broker` and `opensearch-data`: their size is driven by storage and network throughput, not CPU.[5]

The version-specific steps for Kafka 4 aren't documented here and need a proper upgrade plan.
