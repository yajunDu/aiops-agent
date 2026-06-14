"""
系统1 · 在线检测（感知层）—— 从旧 system1 忠实移植
======================================================
管线（与训练完全一致，保证复用已训模型 iforest_model.pkl）：
  原始8指标 → 15s 窗口聚合 → 每Pod z-score → 6 派生特征 →
  log1p+clip 预处理 → IsolationForest -score_samples → 阈值 → 切片合并

唯一的「在线适配」：z-score 的基线。
  离线训练用「注入前窗口」当基线；在线没有注入时刻，改用
  「观测期前导窗口」（默认前 baseline_secs 秒）当基线，对其后的窗口做检测。
  这是从「带标签离线评测」到「无标签在线检测」的必要且合理的改动。

接口：
  • detect_anomalies(window)            ← 实时（Prometheus）
  • detect_from_long(long_df, ...)      ← 核心：任意长表指标 → 切片
  • detect_from_experiment_parquet(p)   ← 回放/录 demo（驱动闭环用）
  • load_slices_from_csv(path)          ← 直接读系统1 已产出的切片
"""
from __future__ import annotations

import os
import json
import csv
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.contracts import AnomalySlice
from ..config import LIVE_MODE, PROM_URL, MANAGED_NAMESPACE, MONITORED_SERVICES

WINDOW_SECS = 15
MIN_SLICE_GAP = 30          # 切片内允许的窗口间隔（秒），与旧 anomaly_slicer 一致
DEFAULT_BASELINE_SECS = 180  # 在线基线：观测期前导窗口时长
# 判别性特征：注入必然让目标 Pod 在对应指标上巨幅偏离 → 用它排序嫌疑（比通用离群分更准）
DISC_COLS = ["cpu_zscore", "cpu_throttle_zscore", "restart_zscore",
             "net_max_z", "net_rx_drop_zscore", "net_tx_drop_zscore"]
METRIC_NAMES = ["cpu", "memory", "net_rx", "net_tx",
                "net_rx_drop", "net_tx_drop", "cpu_throttle", "restart"]
DERIVED = ["net_rx_abs_z", "net_tx_abs_z", "net_max_z",
           "cpu_throttle_interact", "restart_abs_z", "cpu_abs_z"]

# 已训模型 + 阈值所在目录（把旧 system1/outputs 放这里，或用环境变量指定）
MODEL_DIR = Path(os.getenv("AIOPS_SYSTEM1_DIR", "system1/outputs"))

# 采集 PromQL（与旧 experiments/prom_client.py 完全一致，保证在线/离线同源）
_PROMQL = {
    "cpu": 'rate(container_cpu_usage_seconds_total{{namespace="{ns}",container!=""}}[1m])',
    "memory": 'container_memory_usage_bytes{{namespace="{ns}",container!=""}}',
    "net_rx": 'rate(container_network_receive_bytes_total{{namespace="{ns}"}}[1m])',
    "net_tx": 'rate(container_network_transmit_bytes_total{{namespace="{ns}"}}[1m])',
    "net_rx_drop": 'rate(container_network_receive_packets_dropped_total{{namespace="{ns}"}}[1m])',
    "net_tx_drop": 'rate(container_network_transmit_packets_dropped_total{{namespace="{ns}"}}[1m])',
    "cpu_throttle": 'rate(container_cpu_cfs_throttled_periods_total{{namespace="{ns}",container!=""}}[1m])',
    "restart": 'kube_pod_container_status_restarts_total{{namespace="{ns}"}}',
}

_MODEL = None
_META = None


def _load_model():
    global _MODEL, _META
    if _MODEL is None:
        import joblib
        _MODEL = joblib.load(MODEL_DIR / "iforest_model.pkl")
        _META = json.loads((MODEL_DIR / "threshold.json").read_text())
    return _MODEL, _META


# ── 特征工程（与 load_dataset / train_iforest 逐行对齐）──────────
def _window_pivot(long_df: pd.DataFrame) -> pd.DataFrame:
    df = long_df.copy()
    df["window"] = (df["timestamp"] // WINDOW_SECS * WINDOW_SECS).astype(int)
    df["pod_simple"] = df["pod"].fillna("unknown")
    agg = df.groupby(["pod_simple", "window", "metric_name"])["value"].mean().reset_index()
    wide = agg.pivot_table(index=["pod_simple", "window"],
                           columns="metric_name", values="value").reset_index()
    for m in METRIC_NAMES:
        if m not in wide.columns:
            wide[m] = 0.0
    wide[METRIC_NAMES] = wide[METRIC_NAMES].fillna(0.0)
    return wide


def _add_zscore(wide: pd.DataFrame, baseline_mask: pd.Series) -> pd.DataFrame:
    """每 Pod 用基线窗口的 mean/std 计算 z-score（与离线一致，仅基线来源改为前导窗口）。"""
    base = wide[baseline_mask]
    stats = base.groupby("pod_simple")[METRIC_NAMES].agg(["mean", "std"])
    for m in METRIC_NAMES:
        bmean = wide["pod_simple"].map(stats[(m, "mean")])
        bstd = wide["pod_simple"].map(stats[(m, "std")])
        z = (wide[m] - bmean) / (bstd + 1e-6)
        wide[f"{m}_zscore"] = z.replace([np.inf, -np.inf], 0).fillna(0)
    return wide


def _add_derived(wide: pd.DataFrame) -> pd.DataFrame:
    wide["net_rx_abs_z"] = np.abs(wide["net_rx_zscore"])
    wide["net_tx_abs_z"] = np.abs(wide["net_tx_zscore"])
    wide["net_max_z"] = np.maximum(wide["net_rx_abs_z"], wide["net_tx_abs_z"])
    wide["cpu_throttle_interact"] = wide["cpu"] * wide["cpu_throttle"]
    wide["restart_abs_z"] = np.abs(wide["restart_zscore"])
    wide["cpu_abs_z"] = np.abs(wide["cpu_zscore"])
    return wide


def _preprocess(X: pd.DataFrame) -> pd.DataFrame:
    X = X.copy().astype(float)
    for col in X.columns:
        if col == "memory":
            X[col] = np.log1p(X[col])
        elif "zscore" in col or "abs_z" in col or "max_z" in col:
            X[col] = np.sign(X[col]) * np.log1p(np.abs(X[col]))
        else:
            X[col] = np.log1p(np.abs(X[col]))
    return X.clip(-50, 50)


def _merge_into_slices(anom: pd.DataFrame) -> list[dict]:
    """连续异常窗口合并成切片（复刻旧 anomaly_slicer.merge_into_slices）。"""
    if anom.empty:
        return []
    a = anom.sort_values("window").reset_index(drop=True)
    slices = []
    cs = ce = int(a.iloc[0]["window"])
    pods = {a.iloc[0]["pod_simple"]}
    smax = float(a.iloc[0]["score"])
    for i in range(1, len(a)):
        r = a.iloc[i]
        if r["window"] - ce <= MIN_SLICE_GAP + WINDOW_SECS:
            ce = int(r["window"]); pods.add(r["pod_simple"]); smax = max(smax, float(r["score"]))
        else:
            slices.append({"t_start": cs, "t_end": ce + WINDOW_SECS,
                           "pods": sorted(pods), "max_score": smax})
            cs = ce = int(r["window"]); pods = {r["pod_simple"]}; smax = float(r["score"])
    slices.append({"t_start": cs, "t_end": ce + WINDOW_SECS,
                   "pods": sorted(pods), "max_score": smax})
    for sl in slices:
        sl["n_windows"] = int(((a["window"] >= sl["t_start"]) & (a["window"] < sl["t_end"])).sum())
    return slices


# ── 核心：长表 → 异常切片 ──────────────────────────────────────
DEFAULT_TOP_K = 5  # 在线适配：每个切片只保留分数最高的 K 个 Pod 作为嫌疑候选


def detect_from_long(long_df: pd.DataFrame,
                     baseline_secs: int = DEFAULT_BASELINE_SECS,
                     threshold: float | None = None,
                     top_k_suspects: int = DEFAULT_TOP_K,
                     monitored_services: set | None = None) -> list[AnomalySlice]:
    if long_df is None or long_df.empty:
        return []
    clf, meta = _load_model()
    feature_cols = meta["feature_cols"]
    thr = meta["threshold"] if threshold is None else threshold
    scope = MONITORED_SERVICES if monitored_services is None else monitored_services

    wide = _window_pivot(long_df)
    if wide.empty:
        return []

    # 在线定位关键适配①：限定到核心监控服务，排除嘈杂边缘服务
    if scope:
        svc = wide["pod_simple"].apply(AnomalySlice.service_of_pod)
        wide = wide[svc.isin(scope)].reset_index(drop=True)
        if wide.empty:
            return []

    w0, w1 = wide["window"].min(), wide["window"].max()
    span = w1 - w0
    base_cut = w0 + min(baseline_secs, max(WINDOW_SECS, span // 2))
    baseline_mask = wide["window"] < base_cut

    wide = _add_zscore(wide, baseline_mask)
    wide = _add_derived(wide)
    for c in feature_cols:
        if c not in wide.columns:
            wide[c] = 0.0
    wide["score"] = -clf.score_samples(_preprocess(wide[feature_cols]))

    # 异常事件由孤立森林判定（其强项）；判别分仅用于嫌疑排序
    anom = wide[(wide["score"] >= thr) & (wide["window"] >= base_cut)].copy()
    out = []
    for sl in _merge_into_slices(anom):
        in_slice = anom[(anom["window"] >= sl["t_start"]) & (anom["window"] < sl["t_end"])].copy()
        # 在线定位关键适配②：按判别性 z-score 峰值排序嫌疑，留 Top-K
        in_slice["_disc"] = in_slice[DISC_COLS].abs().max(axis=1)
        ranked = in_slice.groupby("pod_simple")["_disc"].max().sort_values(ascending=False)
        top_pods = list(ranked.head(top_k_suspects).index)
        out.append(AnomalySlice(
            slice_id=f"slice-{sl['t_start']}",
            t_start=sl["t_start"], t_end=sl["t_end"],
            suspect_pods=top_pods, max_score=sl["max_score"],
            n_windows=sl["n_windows"],
        ).ensure_services())
    return out


# ── 实时（Prometheus）─────────────────────────────────────────
def _collect_window(start: float, end: float, ns: str) -> pd.DataFrame:
    import requests
    frames = []
    for name, q in _PROMQL.items():
        try:
            r = requests.get(f"{PROM_URL}/api/v1/query_range",
                             params={"query": q.format(ns=ns), "start": start,
                                     "end": end, "step": "15s"}, timeout=30)
            for s in r.json().get("data", {}).get("result", []):
                pod = s.get("metric", {}).get("pod")
                for ts, v in s.get("values", []):
                    frames.append({"pod": pod, "timestamp": float(ts),
                                   "value": float(v), "metric_name": name})
        except Exception:
            continue
    return pd.DataFrame(frames)


def detect_anomalies(window=None, lookback_secs: int = 480,
                     namespace: str = MANAGED_NAMESPACE) -> list[AnomalySlice]:
    """实时检测：拉最近 lookback 窗口的遥测，前导段做基线，其后检测。"""
    import time
    if not LIVE_MODE:
        raise RuntimeError("LIVE_MODE=0：实时检测未启用。评测/演示请用 "
                           "detect_from_experiment_parquet 或 load_slices_from_csv")
    end = window[1] if window else time.time()
    start = window[0] if window else end - lookback_secs
    return detect_from_long(_collect_window(start, end, namespace))


# ── 回放 / 录 demo（无在线集群也能驱动闭环）────────────────────
def detect_from_experiment_parquet(parquet_path: str,
                                   baseline_secs: int = DEFAULT_BASELINE_SECS) -> list[AnomalySlice]:
    return detect_from_long(pd.read_parquet(parquet_path), baseline_secs=baseline_secs)


def load_slices_from_csv(path: str) -> list[AnomalySlice]:
    """直接读系统1 已产出的 anomaly_slices.csv（slice_id,t_start,t_end,pods,max_score,n_windows）。"""
    out = []
    p = Path(path)
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pods = [x for x in (row.get("pods", "") or "").replace(";", ",").split(",") if x]
            out.append(AnomalySlice(
                slice_id=row.get("slice_id") or f"slice-{row.get('t_start')}",
                t_start=int(float(row.get("t_start", 0))),
                t_end=int(float(row.get("t_end", 0))),
                suspect_pods=pods,
                max_score=float(row.get("max_score", 0) or 0),
                n_windows=int(float(row.get("n_windows", 0) or 0)),
            ).ensure_services())
    return out
