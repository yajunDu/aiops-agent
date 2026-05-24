import requests
import sys

PROM = "http://localhost:30090"

# 1. 健康检查
r = requests.get(f"{PROM}/-/healthy", timeout=3)
print(f"健康检查: {r.status_code} {r.text.strip()}")

# 2. 查 gateway CPU
print("\n===== 查 ts-gateway CPU =====")
q = 'rate(container_cpu_usage_seconds_total{namespace="train-ticket",pod=~"ts-gateway.*"}[1m])'
r = requests.get(f"{PROM}/api/v1/query", params={"query": q}, timeout=5)
data = r.json()
result = data.get("data", {}).get("result", [])
if result:
    print(f"✅ 找到 {len(result)} 条记录")
    for x in result[:3]:
        pod = x['metric'].get('pod', '?')
        val = float(x['value'][1])
        print(f"  Pod: {pod:50s}  CPU: {val:.6f} cores")
else:
    print(f"⚠️ 没数据，原始响应：{data}")

# 3. 查所有 train-ticket Pod 的 CPU（看看到底有多少 Pod 在被监控）
print("\n===== 所有 train-ticket Pod CPU =====")
q = 'rate(container_cpu_usage_seconds_total{namespace="train-ticket",container!=""}[1m])'
r = requests.get(f"{PROM}/api/v1/query", params={"query": q}, timeout=5)
data = r.json()
result = data.get("data", {}).get("result", [])
print(f"被监控的 container 数: {len(result)}")
# 列出去重的 pod 名前缀
pods = set()
for x in result:
    pod = x['metric'].get('pod', '')
    if pod.startswith('ts-'):
        # 提取服务名（去掉 hash 后缀）
        parts = pod.rsplit('-', 2)
        svc_name = parts[0] if len(parts) >= 3 else pod
        pods.add(svc_name)
print(f"独立服务数: {len(pods)}")
for s in sorted(pods):
    print(f"  - {s}")

# 4. 查网络指标
print("\n===== 网络指标可用性 =====")
q = 'rate(container_network_receive_bytes_total{namespace="train-ticket"}[1m])'
r = requests.get(f"{PROM}/api/v1/query", params={"query": q}, timeout=5)
data = r.json()
result = data.get("data", {}).get("result", [])
print(f"✅ {len(result)} 条网络流量记录")
