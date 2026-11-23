---
id: GUIDE-009
title: Migrating workloads to Graviton (arm64)
doc_type: guide
team: platform
services: [eks-general, checkout-api, airflow-worker, spark-batch]
updated: 2026-06-05
---
# Migrating workloads to Graviton (arm64)

Graviton instances (instance types with a `g` after the generation number, such as `m7g`, `c7g`, `r7g`) use AWS-designed Arm processors. For our services they are typically **20 to 30% cheaper per unit of work** than the equivalent Intel (`i`) or AMD (`a`) types, with lower power use. Our target is 60% of eligible vCPUs on Graviton by end of 2026. `spark-batch`, `search-indexer` and `opensearch-data` already run on Graviton.

## Is my service eligible?

- Interpreted and JIT languages (Python, Java 17+, Node.js, Go) usually just work.
- Native dependencies need arm64 builds. Check Python wheels for `aarch64`, and any vendored binaries.
- Windows workloads are not eligible (no Windows on Graviton).
- GPU workloads stay on `g5` and `p4d` (x86).

## Migration steps

1. Build multi-architecture container images: `docker buildx build --platform linux/amd64,linux/arm64`. Our CI runners produce both by default since March 2026.
2. Run the service's load test on one Graviton instance and compare p99 latency and throughput per dollar.
3. For Auto Scaling groups, add the Graviton type to the mixed-instances policy with a low weight first, then shift traffic over two weeks.
4. For EKS, add an arm64 managed node group and use node affinity on `kubernetes.io/arch`; remove the amd64 group when all pods have moved.
5. Update Savings Plans forecasts; Compute Savings Plans apply to Graviton automatically, EC2 Instance Savings Plans do not move between families (POL-COST-002).

## Common pitfalls

- Container images built only for amd64 fail with `exec format error`.
- JVM services should use a recent JDK; older ones miss arm64 performance work.
- Benchmark per vCPU: a Graviton vCPU is a full physical core, while an x86 vCPU is a hyper-thread, so the same vCPU count usually does more work on Graviton.
