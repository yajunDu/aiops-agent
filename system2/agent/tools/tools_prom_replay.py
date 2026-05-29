import sys as _s; from pathlib import Path as _P
_s.path.insert(0, str(_P(__file__).resolve().parents[3]))
"""12.4-B 历史回放版指标工具（带 restart 台阶检测）"""
import json
from pathlib import Path
import pandas as pd

from aiops_paths import EXP_DIR
METRICS_DIR = EXP_DIR / "metrics"
GT_DIR = EXP_DIR / "ground-truth"

_CURRENT_EXP = {"exp_id": None, "df": None, "gt": None}


def set_active_experiment(exp_id: str):
    pq = METRICS_DIR / f"{exp_id}.parquet"
    gt = GT_DIR / f"{exp_id}.json"
    if not pq.exists() or not gt.exists():
        raise FileNotFoundError(f"实验 {exp_id} 数据缺失")
    _CURRENT_EXP["exp_id"] = exp_id
    _CURRENT_EXP["df"] = pd.read_parquet(pq)
    _CURRENT_EXP["gt"] = json.loads(gt.read_text())


def get_pod_metrics(pod: str, metric: str, minutes: int = 5) -> str:
    if _CURRENT_EXP["df"] is None:
        return json.dumps({"error": "未设置当前实验"})

    df = _CURRENT_EXP["df"]
    metric_alias = {
        "cpu": "cpu", "memory": "memory",
        "network": ["net_rx", "net_tx"],
        "net_drop": ["net_rx_drop", "net_tx_drop"],
        "restart": "restart", "throttle": "cpu_throttle",
    }
    target_metrics = metric_alias.get(metric)
    if not target_metrics:
        return json.dumps({"error": f"unknown metric: {metric}",
                           "available": list(metric_alias.keys())})
    if isinstance(target_metrics, str):
        target_metrics = [target_metrics]

    pod_mask = df["pod"].astype(str).str.startswith(pod) if "pod" in df.columns else pd.Series([False]*len(df))
    metric_mask = df["metric_name"].isin(target_metrics)
    sub = df[pod_mask & metric_mask]
    if sub.empty:
        return json.dumps({"pod": pod, "metric": metric, "found": False,
                           "hint": f"未找到 pod '{pod}' 的 {metric} 数据"})

    vals = sub["value"].astype(float).tolist()
    summary = {
        "pod": pod, "metric": metric, "found": True,
        "n_samples": len(vals),
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
        "mean": round(sum(vals) / len(vals), 4),
        "latest": round(vals[-1], 4),
    }
    if summary["max"] > 0 and summary["mean"] > 0:
        ratio = summary["max"] / max(summary["mean"], 1e-9)
        summary["peak_to_mean_ratio"] = round(ratio, 2)
        if ratio > 3:
            summary["hint"] = "存在显著峰值（峰均比 > 3）"

    # ★ POD_KILL 金标准：restart 计数跳变
    if metric == "restart":
        delta = max(vals) - min(vals)
        summary["restart_jump"] = round(delta, 1)
        if delta >= 1:
            summary["hint"] = f"⚠️ 重启计数跳变 delta={delta:.0f} - 强烈指向 POD_KILL 故障"

    return json.dumps(summary, ensure_ascii=False)


if __name__ == "__main__":
    set_active_experiment("20260519-211139-pod-kill-preserve")
    r = json.loads(get_pod_metrics("ts-preserve-service", "restart", 5))
    print(json.dumps(r, indent=2, ensure_ascii=False))
