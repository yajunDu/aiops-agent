"""
指标证据工具
================================
重要的去规则化原则（支柱③）：本模块只【返回数值证据】（min/max/mean/latest
及若干派生量如峰均比、restart 台阶、丢包率），**不在这里套任何阈值判定故障类型**。
"x>3 就是 CPU 故障"这类决策交给 LLM 基于证据自己做，从而堵死"这只是规则不是
大模型推理"的质疑。

两种模式：
  • LIVE_MODE=1：实时查询 Prometheus（PromQL 模板）
  • 否则：历史 parquet 回放（批量评测用），从 active experiment 的 parquet 取序列
schema 对齐：parquet 列名请按你旧项目 tools_prom_replay 的实际列调整 _COLS。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from ...config import LIVE_MODE, PROM_URL, METRICS_DIR

# active experiment（评测时由 coordinator 设定，对应一个 parquet 文件）
_ACTIVE_PARQUET: Path | None = None

# 长表 parquet 中 metric_name 取值 ↔ agent 工具的 metric 入参
_PARQUET_METRIC = {
    "cpu": "cpu", "memory": "memory", "network": "net_rx",
    "net_drop": "net_rx_drop", "restart": "restart", "throttle": "cpu_throttle",
}


def set_active_experiment(parquet_path: str | None):
    global _ACTIVE_PARQUET
    _ACTIVE_PARQUET = Path(parquet_path) if parquet_path else None


def _summary(series) -> dict:
    vals = [float(v) for v in series if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not vals:
        return {"available": False}
    mn, mx, mean = min(vals), max(vals), sum(vals) / len(vals)
    peak_to_mean = (mx / mean) if mean > 1e-9 else None
    return {
        "available": True,
        "min": round(mn, 4), "max": round(mx, 4),
        "mean": round(mean, 4), "latest": round(vals[-1], 4),
        "peak_to_mean_ratio": round(peak_to_mean, 3) if peak_to_mean else None,
        "restart_jump": round(mx - mn, 4),   # restart 类指标的台阶
        "n_points": len(vals),
    }


def _from_parquet(service: str, metric: str) -> dict:
    if not _ACTIVE_PARQUET or not _ACTIVE_PARQUET.exists():
        return {"available": False, "reason": "无 active parquet（评测模式需先 set_active_experiment）"}
    try:
        import pandas as pd
        df = pd.read_parquet(_ACTIVE_PARQUET)
        if "metric_name" not in df.columns or "pod" not in df.columns or "value" not in df.columns:
            return {"available": False, "reason": "parquet 非长表（缺 metric_name/pod/value）"}
        mname = _PARQUET_METRIC.get(metric, metric)
        sub = df[(df["pod"].astype(str).str.startswith(service)) & (df["metric_name"] == mname)]
        if sub.empty:
            return {"available": False, "reason": f"该 parquet 无 {service} 的 {mname} 数据"}
        return _summary(sub.sort_values("timestamp")["value"].tolist()
                        if "timestamp" in sub.columns else sub["value"].tolist())
    except Exception as e:
        return {"available": False, "reason": f"parquet 读取失败: {e}"}


def _from_prometheus(service: str, metric: str, minutes: int) -> dict:
    promql = {
        "cpu": f'sum(rate(container_cpu_usage_seconds_total{{pod=~"{service}.*"}}[1m]))',
        "memory": f'sum(container_memory_working_set_bytes{{pod=~"{service}.*"}})',
        "network": f'sum(rate(container_network_receive_bytes_total{{pod=~"{service}.*"}}[1m]))',
        "net_drop": f'sum(rate(container_network_receive_packets_dropped_total{{pod=~"{service}.*"}}[1m]))',
        "restart": f'sum(kube_pod_container_status_restarts_total{{pod=~"{service}.*"}})',
        "throttle": f'sum(rate(container_cpu_cfs_throttled_periods_total{{pod=~"{service}.*"}}[1m]))',
    }.get(metric)
    if not promql:
        return {"available": False, "reason": f"未知 metric: {metric}"}
    try:
        import requests
        r = requests.get(f"{PROM_URL}/api/v1/query_range",
                         params={"query": promql, "step": "15s",
                                 "start": f"-{minutes}m", "end": "now"}, timeout=10)
        data = r.json().get("data", {}).get("result", [])
        series = [float(v) for res in data for _, v in res.get("values", [])]
        return _summary(series)
    except Exception as e:
        return {"available": False, "reason": f"Prometheus 查询失败: {e}"}


def get_service_metrics(service: str, metric: str, minutes: int = 5) -> str:
    """拉取某服务某指标的数值摘要证据（cpu/memory/network/net_drop/restart/throttle）。"""
    s = _from_prometheus(service, metric, minutes) if LIVE_MODE else _from_parquet(service, metric)
    return json.dumps({"service": service, "metric": metric, **s}, ensure_ascii=False)
