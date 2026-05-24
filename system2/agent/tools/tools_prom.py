"""
12.4 Prometheus 指标查询工具（替换占位）
==========================================
从 Prometheus 拉 Pod 指标，返回 LLM 可读的摘要：
  - 均值 / 最大值 / 当前值
  - 相对基线的偏离倍数（给 LLM 直观判断）
"""
import json
import time
import requests


PROM = "http://localhost:30090"
NS = "train-ticket"

# 指标定义（与论文 11.1 节一致）
METRIC_QUERIES = {
    "cpu": 'rate(container_cpu_usage_seconds_total{{namespace="{ns}",pod=~"{pod}.*",container!=""}}[1m])',
    "memory": 'container_memory_usage_bytes{{namespace="{ns}",pod=~"{pod}.*",container!=""}}',
    "network": 'rate(container_network_receive_bytes_total{{namespace="{ns}",pod=~"{pod}.*"}}[1m]) + rate(container_network_transmit_bytes_total{{namespace="{ns}",pod=~"{pod}.*"}}[1m])',
    "net_drop": 'rate(container_network_receive_packets_dropped_total{{namespace="{ns}",pod=~"{pod}.*"}}[1m]) + rate(container_network_transmit_packets_dropped_total{{namespace="{ns}",pod=~"{pod}.*"}}[1m])',
    "restart": 'kube_pod_container_status_restarts_total{{namespace="{ns}",pod=~"{pod}.*"}}',
    "throttle": 'rate(container_cpu_cfs_throttled_periods_total{{namespace="{ns}",pod=~"{pod}.*",container!=""}}[1m])',
}


def _query_range(query: str, start: float, end: float, step: str = "30s"):
    try:
        r = requests.get(f"{PROM}/api/v1/query_range",
                         params={"query": query, "start": start, "end": end, "step": step},
                         timeout=10)
        if r.status_code != 200:
            return []
        return r.json().get("data", {}).get("result", [])
    except Exception:
        return []


def get_pod_metrics(pod: str, metric: str, minutes: int = 5) -> str:
    """供 Agent 调用：返回单个 Pod 指标的统计摘要"""
    if metric not in METRIC_QUERIES:
        return json.dumps({"error": f"unknown metric: {metric}",
                           "available": list(METRIC_QUERIES.keys())})

    end = time.time()
    start = end - minutes * 60
    query = METRIC_QUERIES[metric].format(ns=NS, pod=pod)
    series = _query_range(query, start, end)

    if not series:
        return json.dumps({"pod": pod, "metric": metric, "minutes": minutes,
                           "found": False, "hint": "Pod 不存在或 Prometheus 没采到"})

    # 聚合所有 series 的值（pod 可能有多个 container）
    all_vals = []
    for s in series:
        for _, v in s.get("values", []):
            try:
                all_vals.append(float(v))
            except ValueError:
                pass

    if not all_vals:
        return json.dumps({"pod": pod, "metric": metric, "found": False})

    summary = {
        "pod": pod,
        "metric": metric,
        "minutes": minutes,
        "found": True,
        "n_samples": len(all_vals),
        "min": round(min(all_vals), 4),
        "max": round(max(all_vals), 4),
        "mean": round(sum(all_vals) / len(all_vals), 4),
        "latest": round(all_vals[-1], 4),
    }
    # 简单异常提示
    if summary["max"] > 0 and summary["mean"] > 0:
        peak_ratio = summary["max"] / max(summary["mean"], 1e-9)
        summary["peak_to_mean_ratio"] = round(peak_ratio, 2)
        if peak_ratio > 3:
            summary["hint"] = "存在显著峰值（峰均比 > 3）"

    return json.dumps(summary, ensure_ascii=False)


if __name__ == "__main__":
    tests = [
        ("ts-gateway-service", "cpu", 5),
        ("ts-seat-service", "memory", 5),
        ("ts-order-service", "restart", 10),
        ("nonexistent-pod", "cpu", 5),
    ]
    for pod, metric, minutes in tests:
        print(f"\n📊 {pod} / {metric} / {minutes}min")
        print(f"   → {get_pod_metrics(pod, metric, minutes)}")
