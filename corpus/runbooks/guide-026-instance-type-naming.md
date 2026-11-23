---
id: GUIDE-026
title: How to read EC2 instance type names
doc_type: guide
team: platform
services: [all]
updated: 2026-01-12
---
# How to read EC2 instance type names

An instance type like `r7gd.4xlarge` has four parts: **family** (`r`), **generation** (`7`), **attributes** (`gd`) and **size** (`4xlarge`).

## Families we use

| Letter | Family | Typical memory per vCPU | Our services |
|---|---|---|---|
| `m` | General purpose | 4 GiB | `eks-general`, `airflow-worker`, `jupyter` |
| `c` | Compute optimized | 2 GiB | `ci-runner`, `fulfillment-edge`, `spark-batch` |
| `r` | Memory optimized | 8 GiB | `search-indexer`, `payments-db-proxy` |
| `i` | Storage optimized, local NVMe | 8 GiB | `kafka-broker`, `opensearch-data` |
| `t` | Burstable | varies | `bastion`, small `jupyter` |
| `g` / `p` | GPU | varies | `ml-training` |

## Attribute letters

- `g`: AWS Graviton (Arm) processor, for example `m7g` (see GUIDE-009).
- `i`: Intel processor, for example `m7i`.
- `a`: AMD processor, for example `c7a`.
- `d`: local NVMe instance store included, for example `c7gd`.
- `n`: enhanced networking bandwidth; `e`: extra memory or storage.

## Sizes

Each size step doubles vCPUs and memory: `large` = 2 vCPUs, `xlarge` = 4, `2xlarge` = 8, `4xlarge` = 16, `12xlarge` = 48, `24xlarge` = 96. Price roughly doubles with each step too, which is why downsizing one step saves about 50% (GUIDE-010).

## Generations

Newer generations are usually cheaper per unit of performance. Our minimum for new launches is generation 6; generation 5 types (`m5`) are only allowed for existing fleets awaiting decommission.
