<div align="center">

# 🤖 AIOps Agent

### 基于大模型的运维智能体研究与实现

**双过程认知架构 · GraphRAG · Tool-Calling · K8s 自治自愈**

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-green.svg)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-K3s-326CE5.svg)](https://k3s.io/)
[![LLM](https://img.shields.io/badge/LLM-Qwen2.5--7B-orange.svg)](https://github.com/QwenLM/Qwen2.5)

</div>

---

## 📖 项目简介

**AIOps Agent** 是一个面向 Kubernetes 微服务环境的智能运维系统，将卡尼曼双过程认知理论工程化落地于云原生运维领域。系统通过"快慢双系统协同"实现从异常检测到自治自愈的完整闭环，在 TrainTicket 微服务基准平台上的 67 次真实故障注入实验中达到 **Acc@1 = 82.5%** 的根因诊断准确率。

> 🎓 本项目是南京邮电大学软件工程毕业设计成果，论文题目《基于大模型的运维智能体研究与实现》

---

## ✨ 核心特性

- 🧠 **双过程认知架构** — 边缘侧孤立森林（系统 1 · 快）+ 云端 LLM Agent（系统 2 · 慢）协同
- 🕸️ **GraphRAG 拓扑强约束** — Neo4j 物理拓扑 + Cypher 工具调用，从机理上抑制 LLM 幻觉
- 🛠️ **Tool-Calling 多轮推理** — LangGraph StateGraph 编排 perceive → plan → act → reflect → finalize
- 🛡️ **4 道安全护栏** — 命名空间白名单 / 图谱存在性 / 风险-置信度匹配 / 5 分钟去重
- 🤖 **5 类原子 SOP** — restart_pod / scale / cordon / rollback / network_policy
- 📊 **真实可观测大盘** — Next.js + FastAPI · 5s 实时刷新 · 真实联动 K8s / Neo4j / Prometheus
- 💬 **自由问诊 + 真推理** — UI 内直连 Qwen2.5 的运维助手
- 🔥 **混沌工程评测** — Chaos Mesh 注入 67 次真实故障，全方法对比验证

---

## 📊 实验结果

### 四方法 Acc@1 对比（n=57 个有效切片）

| 方法 | 整体 | CPU 故障 | 网络劣化 | 拓扑硬中断 | 平均耗时 |
|---|---:|---:|---:|---:|---:|
| Rule-Based | 64.9% | 96.8% | 10.0% | 83.3% | <0.1s |
| MicroRCA [Wu et al. 2020] | 43.9% | 48.4% | 30.0% | 66.7% | 0.5 s |
| Naive LLM+RAG | 59.6% | 100.0% | 10.0% | 16.7% | 0.8 s |
| **本文（双过程）** | **82.5%** | **100.0%** | **55.0%** | **83.3%** | 4.7 s |

### 端到端核心指标

| 指标 | 数值 | 说明 |
|---|---:|---|
| 异常检测率 | 85.1% | 系统 1 在 67 实验上 |
| 告警压缩率 (ACR) | 63.0% | 告警风暴收敛能力 |
| MTTD 中位数 | 9 s | 系统 1 首次告警延迟 |
| 根因诊断 Acc@1 | **82.5%** | 系统 2 在 57 切片上 |
| 平均推理时长 | 4.7 s | 含 3 轮工具调用 |
| 平均 MTTR | 85.7 s | kubectl + JVM 冷启动 |
| SOP 命令成功率 | 100% | 真实 kubectl 执行 |

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│  数据源:  Prometheus  │  Kubernetes API  │  Neo4j  │  Chaos │
└────────┬────────────────────┬────────────────────┬──────────┘
         ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────────┐   ┌─────────────────┐
│   系统 1     │    │     系统 2       │   │   执行层 SOP    │
│   感知中枢   │ ─→ │     认知中枢     │ ─→│   自愈中枢      │
│              │    │                  │   │                 │
│ • IsoForest  │    │ • Qwen2.5-7B     │   │ • 5 类 SOP      │
│ • 22 维特征  │    │ • LangGraph      │   │ • 4 道护栏      │
│ • 切片合并   │    │ • GraphRAG       │   │ • kubectl 执行  │
│ • 边缘部署   │    │ • Tool-Calling   │   │ • post-check    │
└──────────────┘    └──────────────────┘   └─────────────────┘
        └─────────────── 反馈环 (MTTR / 业务恢复信号) ◀────────┘
```

---

## 🚀 快速开始

### 前置条件

- Linux 系统（推荐 Ubuntu 22.04 / WSL2）
- Docker + Kubernetes (K3s 推荐)
- Python 3.10+
- Node.js 20+
- GPU 推荐（8GB+ VRAM，用于 vLLM）

### 1. 拉取项目

```bash
git clone https://github.com/YOUR_USERNAME/aiops-agent.git
cd aiops-agent
```

### 2. 部署测试集群

```bash
# 安装 K3s
curl -sfL https://get.k3s.io | sh -

# 部署 TrainTicket（参考上游：FudanSELab/train-ticket）
kubectl create namespace train-ticket

# 部署 Prometheus + Grafana + Chaos Mesh + Neo4j
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring
helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh
helm install neo4j neo4j/neo4j -n neo4j
```

### 3. 启动后端服务

```bash
# 启动 vLLM 推理引擎
cd system2
./start_vllm.sh

# 启动 UI 后端
cd ../ui-backend
python -m venv venv && source venv/bin/activate
pip install fastapi uvicorn pandas requests neo4j openai langgraph
export NEO4J_PWD=your-neo4j-password
python server.py  # http://localhost:9001
```

### 4. 启动 Web UI

```bash
cd ../ui
pnpm install
pnpm dev  # http://localhost:3000
```

### 5. 运行实验（可选）

```bash
# 故障注入
cd experiments
python batch_runner.py --types cpu,network,pod_kill --count 30

# 系统 1 训练 + 评估
cd ../system1
python train_iforest.py
python evaluate.py

# 系统 2 端到端推理
cd ../system2/agent
python coordinator.py 57
```

---

## 📂 项目结构

```
aiops-agent/
├── experiments/                # Chaos Mesh 故障注入框架
│   ├── batch_runner.py
│   └── ground-truth/          # 故障真实标签
├── system1/                    # 感知中枢 · 孤立森林
│   ├── train_iforest.py
│   ├── anomaly_slicer.py
│   └── outputs/
├── system2/                    # 认知中枢 · LLM Agent
│   ├── agent/
│   │   ├── coordinator.py            # 主流程协调
│   │   ├── agent_core.py             # LangGraph 状态机
│   │   ├── build_neo4j_graph.py      # 图谱构建脚本
│   │   └── tools/
│   │       ├── tools_neo4j.py        # Cypher 查询工具
│   │       └── tools_prom_replay.py  # 指标历史回放
│   ├── sop/                    # 执行层 SOP
│   │   ├── templates/          # 5 个 YAML 模板
│   │   ├── sop_planner.py      # 选模板 + 4 道护栏
│   │   └── sop_executor.py     # kubectl 真实执行
│   ├── baselines/              # 3 类对比基线
│   │   ├── rule_based.py
│   │   ├── microrca.py
│   │   └── naive_llm_rag.py
│   └── start_vllm.sh           # vLLM 启动脚本
├── ui/                         # 前端 Next.js 16
│   ├── app/                    # 5 个页面（总览/推理/图谱/实验/异常）
│   ├── components/             # 5 个核心组件
│   └── lib/api.ts              # API 客户端
├── ui-backend/                 # FastAPI 后端
│   └── server.py               # 7 个 RESTful endpoint
└── docs/                       # 文档与图片
```

---

## 🛠️ 技术栈

| 层次 | 组件 | 版本 |
|---|---|---|
| **基础设施** | Kubernetes (K3s) | v1.31.5 |
| **可观测性** | Prometheus + Grafana | latest |
| **混沌工程** | Chaos Mesh | v2.7.2 |
| **知识图谱** | Neo4j | 5.x |
| **LLM 推理** | vLLM | 0.21 |
| **基座模型** | Qwen2.5-7B-Instruct-AWQ | 4-bit 量化 |
| **Agent 框架** | LangGraph | 1.2 |
| **后端** | FastAPI + Python | 3.10 |
| **前端** | Next.js + React + Tailwind | 16 / 19 / 4 |
| **拓扑可视化** | reactflow | 11 |

---

## 🔬 研究方法

本项目采用 **"理论建模 → 系统实现 → 实证评估"** 的递进式技术路线：

1. **理论层** — 基于卡尼曼双过程认知理论解构运维诊断流程
2. **架构层** — 设计感知 + 认知 + 执行三层垂直架构
3. **实现层** — 全栈实现，覆盖从底层指标采集到上层 UI 交互
4. **评估层** — 67 次真实混沌注入 + 三类基线对比验证

### 核心创新点

- 🎯 **理论创新** — 将卡尼曼双过程模型工程化落地于 AIOps 领域
- 🎯 **技术创新** — 提出 GraphRAG + Tool-Calling 拓扑强约束机制，从机理上抑制 LLM 幻觉
- 🎯 **评估创新** — 同基座模型下证明方法本身贡献 22.9 个百分点性能增益
- 🎯 **架构创新** — 边缘 + 云端 + 执行解耦设计，预留多 Agent 协同扩展接口

---

## 📖 论文与文档

本项目为《基于大模型的运维智能体研究与实现》毕业设计的工程实现部分，论文重点章节：

- **第 3 章** 系统总体设计 — 双过程架构形式化建模
- **第 4 章** 实验结果与分析 — 67 次故障注入 + 三基线对比
- **第 5 章** 总结与展望 — 多 Agent 协同 + 神经符号 AI

---

## 🎓 致谢

本项目工作建立在以下开源生态之上：

- [FudanSELab/train-ticket](https://github.com/FudanSELab/train-ticket) — 微服务基准平台
- [chaos-mesh/chaos-mesh](https://github.com/chaos-mesh/chaos-mesh) — 混沌工程框架
- [vLLM](https://github.com/vllm-project/vllm) — 高性能 LLM 推理引擎
- [Qwen](https://github.com/QwenLM/Qwen2.5) — 阿里通义千问开源模型
- [LangChain / LangGraph](https://github.com/langchain-ai/langgraph) — Agent 编排框架
- [Neo4j](https://neo4j.com/) — 图数据库
- [Next.js](https://nextjs.org/) · [reactflow](https://reactflow.dev/) — 前端可视化

特别感谢导师 **程海涛老师** 在研究方向、架构设计与论文写作中给予的悉心指导。

---

## 📜 License

[MIT License](LICENSE) © 2026 Du Yajun

---

<div align="center">

**如果这个项目对你有帮助，欢迎 Star ⭐**

</div>
