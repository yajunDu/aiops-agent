#!/bin/bash
# TrainTicket 部署进度监控
clear
echo "🚂 TrainTicket 部署进度（更新时间：$(date +%H:%M:%S)）"
echo "================================================"

TOTAL=$(kubectl get pods -n train-ticket --no-headers 2>/dev/null | wc -l)
RUNNING=$(kubectl get pods -n train-ticket --no-headers 2>/dev/null | grep -c "Running")
PENDING=$(kubectl get pods -n train-ticket --no-headers 2>/dev/null | grep -cE "Pending|ContainerCreating|Init")
ERROR=$(kubectl get pods -n train-ticket --no-headers 2>/dev/null | grep -cE "Error|CrashLoop|ImagePullBackOff|OOMKilled")

echo "📊 总 Pod 数:       $TOTAL"
echo "✅ Running:        $RUNNING"
echo "⏳ Pending/Init:   $PENDING"
echo "❌ Error/Crash:    $ERROR"
echo ""
echo "📈 完成率: $(( RUNNING * 100 / (TOTAL == 0 ? 1 : TOTAL) ))%"
echo ""
echo "===== 非 Running 的 Pod ====="
kubectl get pods -n train-ticket --no-headers 2>/dev/null | grep -v "Running" | head -15

echo ""
echo "===== 资源占用 ====="
free -h | head -2
echo ""
echo "（再次刷新：bash ~/aiops-project/check-ts.sh）"
