# 部署指南 (DEPLOYMENT.md)

从零在一台新机器上复现 AIOps Agent。预计耗时 2–4 小时（多数时间在等镜像拉取和服务启动）。

## 0. 硬件 / 系统要求

| 项 | 最低 | 推荐 |
|---|---|---|
| OS | Ubuntu 22.04 / WSL2 | 同左 |
| 内存 | 16 GB | 24 GB+ |
| GPU | 8 GB VRAM | RTX 3060 Ti+ |
| 磁盘 | 40 GB | 60 GB+ |
| Python | 3.10+ | 3.10 |
| Node.js | 20+ | 20 |

## 1. 拉取项目 + 配置环境变量

```bash
git clone https://github.com/yajunDu/aiops-agent.git
cd aiops-agent

# 配置环境变量
cp .env.example .env
# 编辑 .env，至少填写 NEO4J_PWD 和 VLLM_MODEL_PATH
# AIOPS_ROOT 可留空（自动推断为当前仓库目录）

# 让环境变量生效
set -a && source .env && set +a
```

## 2. 安装依赖

```bash
# Python 后端 + Agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# vLLM 单独装（体积大，按你的 CUDA 版本选）
pip install vllm==0.21

# 前端
cd ui && pnpm install && cd ..
```

## 3. 下载基座模型

```bash
# 从 HuggingFace 下载 Qwen2.5-7B-AWQ（约 6GB）
pip install huggingface_hub
huggingface-cli download Qwen/Qwen2.5-7B-Instruct-AWQ \
  --local-dir ./models/Qwen2.5-7B-Instruct-AWQ

# 更新 .env 里的 VLLM_MODEL_PATH 指向该目录
```

## 4. 部署 Kubernetes 集群

```bash
# 安装 K3s
curl -sfL https://get.k3s.io | sh -
mkdir -p ~/.kube && sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config

# 验证
kubectl get nodes   # 应看到 1 个 Ready 节点
```

## 5. 部署 TrainTicket 微服务（关键步骤）

TrainTicket 是评测用的基准微服务平台（41 个服务）。

```bash
kubectl create namespace train-ticket

# 方式 A：用上游官方部署清单（推荐）
git clone https://github.com/FudanSELab/train-ticket.git /tmp/train-ticket
kubectl apply -f /tmp/train-ticket/deployment/kubernetes-manifests/quickstart-k8s/ \
  -n train-ticket

# 等待核心服务起来（约 5-10 分钟，Java 应用启动慢）
kubectl get pods -n train-ticket -w
```

> ⚠️ 注意：部分边缘服务（payment / food / news 等约 20 个）依赖 SkyWalking 后端，
> 若未部署 SkyWalking 它们会持续 CrashLoopBackOff。**这是预期现象**——
> 本项目刻意将其作为"嘈杂集群"背景噪声，核心调用链的 10 个服务 Ready 即可演示。

## 6. 部署监控 / 混沌 / 图谱组件

```bash
# 添加 helm 仓库
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm repo add neo4j https://helm.neo4j.com/neo4j
helm repo update

# Prometheus + Grafana
kubectl create namespace monitoring
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring

# Chaos Mesh
kubectl create namespace chaos-mesh
helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/k3s/containerd/containerd.sock

# Neo4j（密码用 .env 里的 NEO4J_PWD）
kubectl create namespace neo4j
helm install neo4j neo4j/neo4j -n neo4j \
  --set neo4j.password="$NEO4J_PWD"

# 等待全部 Ready
kubectl get pods -A | grep -E "monitoring|chaos-mesh|neo4j"
```

## 7. 一键启动所有服务

```bash
# 确保 .env 已 source
set -a && source .env && set +a

# 一键启动（port-forward + vLLM + 图谱 + 后端 + 前端 + 健康检查）
chmod +x start_all.sh start_vllm.sh
./start_all.sh
```

健康检查 7 个端口全部 200 后，访问 **http://localhost:3000**。

## 8. 跑实验（可选）

```bash
source venv/bin/activate

# 故障注入 + 采集
cd experiments && python batch_runner.py --types cpu,network,pod_kill --count 30 && cd ..

# 系统1 训练
cd system1 && python train_iforest.py && cd ..

# 系统2 端到端评测
cd system2/agent && python coordinator.py 57 && cd ../..

# 通用性测试（5 服务 × 多故障类型）
python test_5pods.py
```

## 常见问题

**Q: vLLM 启动失败 "CUDA out of memory"**
A: 调低 `start_vllm.sh` 里的 `--gpu-memory-utilization`（如 0.7）或 `--max-model-len`。

**Q: 大量 Pod 一直 CrashLoopBackOff**
A: 边缘服务依赖 SkyWalking，属预期噪声。只要核心 10 服务（gateway/order/seat/travel/auth/user/station/train/route/config）Ready 即可。

**Q: Neo4j 图谱构建失败**
A: 确认 `NEO4J_PWD` 与 helm 部署时一致，且 7687 端口 port-forward 正常。

**Q: 前端能开但数据全空**
A: 检查后端 9001 是否 200，以及 kubectl 在后端进程的环境里可用（`kubectl get pods -n train-ticket` 能跑通）。
