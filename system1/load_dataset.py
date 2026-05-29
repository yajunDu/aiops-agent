import sys as _s; from pathlib import Path as _P
_s.path.insert(0, str(_P(__file__).resolve().parents[1]))
"""
11.1 数据集加载器 V2 - 修复版
==============================
关键改进：
  1. 只保留"被攻击的 Pod"和"少量对照 Pod"，避免无关 Pod 稀释
  2. 异常标签收紧：t_inject ~ t_inject+90s 才标 1（故障实际持续区间）
  3. 增加更多统计特征：mean / max / std
  4. 增加变化率特征：相比基线的偏离度
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd


from aiops_paths import EXP_DIR, SYSTEM1_OUT
OUT_DIR = SYSTEM1_OUT
OUT_DIR.mkdir(exist_ok=True, parents=True)

WINDOW_SECS = 15
ANOMALY_DURATION = 120  # 注入后多少秒内标为异常（注入 60s + 余波 60s）
METRIC_NAMES = [
    "cpu", "memory", "net_rx", "net_tx",
    "net_rx_drop", "net_tx_drop", "cpu_throttle", "restart"
]


def load_one(parquet_path, gt_path):
    df = pd.read_parquet(parquet_path)
    gt = json.loads(Path(gt_path).read_text())
    t_inject = gt["t_inject_unix"]
    fault_type = gt["fault_type"]
    target = gt["target_service"]
    exp_id = gt["experiment_id"]

    # 1. 时间窗口
    df["window"] = (df["timestamp"] // WINDOW_SECS * WINDOW_SECS).astype(int)
    df["pod_simple"] = df["pod"].fillna("unknown")

    # 2. 🔥 只保留被攻击的目标 Pod（target_service 的 Pod）
    target_mask = df["pod_simple"].str.startswith(target)
    df_target = df[target_mask].copy()
    
    if df_target.empty:
        return None
    
    # 3. 按 (pod, window, metric_name) 聚合
    agg = df_target.groupby(["pod_simple", "window", "metric_name"])["value"].mean().reset_index()
    
    # 4. pivot
    wide = agg.pivot_table(
        index=["pod_simple", "window"],
        columns="metric_name",
        values="value",
    ).reset_index()
    
    for m in METRIC_NAMES:
        if m not in wide.columns:
            wide[m] = 0.0
    wide[METRIC_NAMES] = wide[METRIC_NAMES].fillna(0.0)

    # 5. 🔥 精确标签：[t_inject, t_inject + 120s] 才标异常
    wide["label"] = (
        (wide["window"] >= t_inject) & 
        (wide["window"] < t_inject + ANOMALY_DURATION)
    ).astype(int)

    # 6. 🔥 计算每个 Pod 在"注入前 180s"的基线（均值/标准差）
    # 注入前的窗口 = 基线
    baseline = wide[wide["window"] < t_inject].groupby("pod_simple")[METRIC_NAMES].agg(['mean', 'std']).reset_index()
    baseline.columns = ['pod_simple'] + [f"{m}_{stat}_baseline" for m in METRIC_NAMES for stat in ['mean', 'std']]

    # 7. 把基线合并回来
    wide = wide.merge(baseline, on="pod_simple", how="left")
    
    # 8. 🔥 计算 z-score 特征：(当前值 - 基线均值) / 基线标准差
    for m in METRIC_NAMES:
        mean_col = f"{m}_mean_baseline"
        std_col = f"{m}_std_baseline"
        # std 为 0 时（指标完全平稳）用极小值避免除零
        wide[f"{m}_zscore"] = (wide[m] - wide[mean_col]) / (wide[std_col] + 1e-6)
        # 把 inf 和 nan 替换为 0
        wide[f"{m}_zscore"] = wide[f"{m}_zscore"].replace([np.inf, -np.inf], 0).fillna(0)
    
    # 9. 元数据
    wide["exp_id"] = exp_id
    wide["fault_type"] = fault_type
    wide["target_service"] = target
    wide["t_inject"] = t_inject
    
    # 10. 删除基线辅助列（保留原始指标 + z-score 特征）
    drop_cols = [c for c in wide.columns if c.endswith("_baseline")]
    wide = wide.drop(columns=drop_cols)
    
    return wide


def main():
    parquet_dir = EXP_DIR / "metrics"
    gt_dir = EXP_DIR / "ground-truth"

    files = sorted(parquet_dir.glob("*.parquet"))
    print(f"📂 找到 {len(files)} 个 parquet 文件")

    all_frames = []
    skipped = 0
    for pf in files:
        gt_path = gt_dir / f"{pf.stem}.json"
        if not gt_path.exists():
            skipped += 1
            continue
        try:
            frame = load_one(pf, gt_path)
            if frame is None or frame.empty:
                skipped += 1
                continue
            all_frames.append(frame)
        except Exception as e:
            print(f"⚠️  跳过 {pf.stem}: {e}")
            skipped += 1

    if not all_frames:
        print("❌ 没有有效数据")
        return

    full = pd.concat(all_frames, ignore_index=True)

    out_path = OUT_DIR / "dataset.parquet"
    full.to_parquet(out_path, index=False)

    # === 统计 ===
    print(f"\n{'='*60}")
    print(f"✅ 数据集已生成: {out_path}")
    print(f"{'='*60}")
    print(f"  总行数:     {len(full):,}")
    print(f"  唯一实验:   {full['exp_id'].nunique()}")
    print(f"  唯一 Pod:   {full['pod_simple'].nunique()}")
    print(f"  跳过文件:   {skipped}")
    print(f"\n📊 标签分布:")
    print(full["label"].value_counts().to_string())
    
    print(f"\n📊 原始特征对比（异常 vs 正常）:")
    for m in METRIC_NAMES:
        normal = full[full["label"] == 0][m].mean()
        anomaly = full[full["label"] == 1][m].mean()
        ratio = anomaly / (normal + 1e-9)
        print(f"  {m:15s}  正常={normal:>14.4f}  异常={anomaly:>14.4f}  比={ratio:>6.2f}x")
    
    print(f"\n🔥 Z-Score 特征对比（异常应该 >> 0）:")
    for m in METRIC_NAMES:
        z_col = f"{m}_zscore"
        if z_col not in full.columns:
            continue
        normal_z = full[full["label"] == 0][z_col].abs().mean()
        anomaly_z = full[full["label"] == 1][z_col].abs().mean()
        ratio = anomaly_z / (normal_z + 1e-9)
        print(f"  {z_col:30s}  正常|z|={normal_z:>8.3f}  异常|z|={anomaly_z:>8.3f}  比={ratio:>6.2f}x")
    
    # 故障类型上的特征区分度
    print(f"\n🎯 按故障类型看 z-score（应该看到对应指标暴增）:")
    for ft in ['CPU', 'NETWORK', 'POD_KILL']:
        sub = full[(full['fault_type'] == ft) & (full['label'] == 1)]
        if sub.empty:
            continue
        print(f"\n  === {ft} 故障的异常窗口（n={len(sub)}）===")
        for m in METRIC_NAMES:
            z = sub[f"{m}_zscore"].abs().mean()
            print(f"    |{m}_zscore| = {z:.3f}")
    
    summary = {
        "rows": len(full),
        "experiments": int(full["exp_id"].nunique()),
        "pods": int(full["pod_simple"].nunique()),
        "label_distribution": full["label"].value_counts().to_dict(),
        "fault_distribution": full["fault_type"].value_counts().to_dict(),
        "features": METRIC_NAMES + [f"{m}_zscore" for m in METRIC_NAMES],
        "window_secs": WINDOW_SECS,
        "anomaly_duration_secs": ANOMALY_DURATION,
    }
    (OUT_DIR / "feature_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n💾 摘要: {OUT_DIR / 'feature_summary.json'}")


if __name__ == "__main__":
    main()
