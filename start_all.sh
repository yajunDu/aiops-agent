#!/bin/bash
# 一键启动所有服务（假设 K8s 集群 + TrainTicket + 监控栈已部署）
set -e
LOG="${AIOPS_LOG_DIR:-$HOME/aiops-portforwards}"
mkdir -p "$LOG"

echo "[1/5] 启动 port-forward..."
pkill -f "port-forward" 2>/dev/null || true; sleep 2
kubectl port-forward -n monitoring svc/prometheus-grafana 30030:80 --address=0.0.0.0 > "$LOG/grafana.log" 2>&1 &
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 30090:9090 --address=0.0.0.0 > "$LOG/prom.log" 2>&1 &
kubectl port-forward -n chaos-mesh svc/chaos-dashboard 2333:2333 --address=0.0.0.0 > "$LOG/chaos.log" 2>&1 &
kubectl port-forward -n neo4j svc/neo4j 7474:7474 --address=0.0.0.0 > "$LOG/neo-http.log" 2>&1 &
kubectl port-forward -n neo4j svc/neo4j 7687:7687 --address=0.0.0.0 > "$LOG/neo-bolt.log" 2>&1 &
sleep 5

echo "[2/5] 启动 vLLM（需先设置 VLLM_MODEL_PATH）..."
bash "$(dirname "$0")/start_vllm.sh"
echo "    等 45s..."; sleep 45

echo "[3/5] 构建 Neo4j 拓扑图谱..."
python "$(dirname "$0")/system2/agent/build_neo4j_graph.py" 2>&1 | tail -3 || echo "  (图谱构建失败，检查 Neo4j 连接)"

echo "[4/5] 启动 UI 后端 (9001)..."
pkill -f "python.*server.py" 2>/dev/null || true; sleep 2
(cd "$(dirname "$0")/ui-backend" && nohup python server.py > "$LOG/ui-backend.log" 2>&1 &)
sleep 5

echo "[5/5] 启动前端 (3000)..."
(cd "$(dirname "$0")/ui" && nohup pnpm dev > "$LOG/ui-dev.log" 2>&1 &)
sleep 10

echo ""
echo "===== 健康检查 ====="
for s in "前端:3000" "后端:9001/" "Grafana:30030" "Prom:30090/-/healthy" "Neo4j:7474" "vLLM:8000/v1/models" "Chaos:2333"; do
  n=${s%%:*}; u=${s#*:}
  echo "  $n: $(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://localhost:$u)"
done
echo "全部 200 即就绪。访问 http://localhost:3000"
