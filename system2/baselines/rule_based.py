"""
基线 1: Rule-Based（基于阈值规则的根因诊断）
================================================
设计：
  - 不调 LLM，不查图谱
  - 对每个实验，直接看 8 类指标的统计特征
  - 按"先 restart → 再 network → 再 cpu" 的优先级硬判
  - 这是论文里"传统规则方法"的对比基线
"""
from __future__ import annotations
import sys as _s; from pathlib import Path as _P
_s.path.insert(0, str(_P(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

import pandas as pd

from aiops_paths import EXP_DIR, SYSTEM1_OUT
METRICS_DIR = EXP_DIR / "metrics"
GT_DIR = EXP_DIR / "ground-truth"


def predict_one(exp_id: str, target_service: str) -> dict:
    """对单个实验跑规则诊断"""
    pq_path = METRICS_DIR / f"{exp_id}.parquet"
    if not pq_path.exists():
        return {"pred_fault_type": "UNKNOWN", "reason": "no parquet"}

    df = pd.read_parquet(pq_path)
    # 只看目标服务的指标
    target_df = df[df["pod"].astype(str).str.startswith(target_service)]
    if target_df.empty:
        return {"pred_fault_type": "UNKNOWN", "reason": f"no pod data for {target_service}"}

    def stat(metric_name):
        vals = target_df[target_df["metric_name"] == metric_name]["value"].astype(float)
        if vals.empty:
            return None
        return {"min": vals.min(), "max": vals.max(), "mean": vals.mean()}

    # 规则 1: restart 跳变 → POD_KILL
    restart = stat("restart")
    if restart and (restart["max"] - restart["min"]) >= 1:
        return {"pred_fault_type": "POD_KILL",
                "reason": f"restart_jump={restart['max'] - restart['min']:.0f}",
                "confidence": 0.95}

    # 规则 2: network 流量峰均比 > 3 或 net_drop > 0 → NETWORK
    net_rx = stat("net_rx")
    net_tx = stat("net_tx")
    net_drop_rx = stat("net_rx_drop")
    net_drop_tx = stat("net_tx_drop")
    
    net_drop_max = max(
        net_drop_rx["max"] if net_drop_rx else 0,
        net_drop_tx["max"] if net_drop_tx else 0,
    )
    if net_drop_max > 0:
        return {"pred_fault_type": "NETWORK",
                "reason": f"net_drop_max={net_drop_max:.4f}",
                "confidence": 0.9}
    
    net_peak = 0
    for s in [net_rx, net_tx]:
        if s and s["mean"] > 0:
            ratio = s["max"] / s["mean"]
            if ratio > net_peak:
                net_peak = ratio
    if net_peak > 3:
        return {"pred_fault_type": "NETWORK",
                "reason": f"net_peak_ratio={net_peak:.2f}",
                "confidence": 0.75}

    # 规则 3: cpu 峰均比 > 3 或 max > 0.3 → CPU
    cpu = stat("cpu")
    throttle = stat("cpu_throttle")
    if cpu:
        if cpu["max"] > 0.3:
            return {"pred_fault_type": "CPU",
                    "reason": f"cpu_max={cpu['max']:.3f}",
                    "confidence": 0.85}
        if cpu["mean"] > 0 and cpu["max"] / cpu["mean"] > 3:
            return {"pred_fault_type": "CPU",
                    "reason": f"cpu_peak_ratio={cpu['max']/cpu['mean']:.2f}",
                    "confidence": 0.7}
    if throttle and throttle["max"] > 1:
        return {"pred_fault_type": "CPU",
                "reason": f"throttle_max={throttle['max']:.2f}",
                "confidence": 0.7}

    return {"pred_fault_type": "UNKNOWN", "reason": "no rule matched", "confidence": 0.0}


def main():
    # 加载系统1 检测到的 57 个实验
    exp_df = pd.read_csv((SYSTEM1_OUT / "experiment_results.csv"))
    detected = exp_df[exp_df["detected"] == True]
    
    results = []
    for _, gt in detected.iterrows():
        exp_id = gt["exp_id"]
        target = gt["target_service"]
        truth = gt["fault_type"]
        
        pred = predict_one(exp_id, target)
        correct = pred["pred_fault_type"] == truth
        
        results.append({
            "exp_id": exp_id,
            "truth_fault_type": truth,
            "pred_fault_type": pred["pred_fault_type"],
            "reason": pred["reason"],
            "confidence": pred.get("confidence", 0.0),
            "correct": correct,
        })
    
    df = pd.DataFrame(results)
    out_path = Path(__file__).parent / "rule_based_predictions.csv"
    df.to_csv(out_path, index=False)
    
    print(f"📊 Rule-Based 基线结果（{len(df)} 个实验）")
    print(f"  整体 Acc@1: {df['correct'].mean():.1%}")
    print(f"\n按故障类型:")
    for ft, sub in df.groupby("truth_fault_type"):
        print(f"  {ft:12s} n={len(sub):3d}  Acc={sub['correct'].mean():.1%}")
    print(f"\n💾 {out_path}")


if __name__ == "__main__":
    main()
