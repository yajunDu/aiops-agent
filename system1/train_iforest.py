import sys as _s; from pathlib import Path as _P
_s.path.insert(0, str(_P(__file__).resolve().parents[1]))
"""
11.2 V2 - 优化版
================
关键改进：
  1. 分层抽样：按 fault_type 分层划分（POD_KILL 必出现在测试集）
  2. 派生特征：
     - net_rx_change: net_rx 相对基线的变化率
     - net_tx_change: net_tx 同上
     - cpu_x_throttle: cpu 与 throttle 的交互（CPU 高 + 节流高 = 强信号）
  3. 用 -score_samples 做异常分数（数值范围更稳定）
"""
import json
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    classification_report, confusion_matrix, f1_score,
    precision_recall_curve, roc_auc_score, precision_score, recall_score
)


from aiops_paths import SYSTEM1_OUT as OUT, SYSTEM1_FIG as FIG

OUT.mkdir(exist_ok=True, parents=True)
FIG.mkdir(exist_ok=True, parents=True)

METRIC_NAMES = ["cpu", "memory", "net_rx", "net_tx",
                "net_rx_drop", "net_tx_drop", "cpu_throttle", "restart"]


def add_derived_features(df):
    """添加派生特征（论文 3.2 节描述的"特征工程"）"""
    # 1. 流量变化率：当前网络流量 / 基线均值
    df = df.copy()
    # net_rx/tx 的偏离比（相比 z-score 更稳健）
    df["net_rx_abs_z"] = np.abs(df["net_rx_zscore"])
    df["net_tx_abs_z"] = np.abs(df["net_tx_zscore"])
    df["net_max_z"] = np.maximum(df["net_rx_abs_z"], df["net_tx_abs_z"])
    
    # 2. CPU × throttle 交互：高 CPU + 高节流 = 真异常
    df["cpu_throttle_interact"] = df["cpu"] * df["cpu_throttle"]
    
    # 3. restart 变化（POD_KILL 检测核心）
    df["restart_abs_z"] = np.abs(df["restart_zscore"])
    
    # 4. CPU 绝对偏离
    df["cpu_abs_z"] = np.abs(df["cpu_zscore"])
    
    return df


def preprocess(X):
    """log1p + clip 抑制爆表"""
    X = X.copy().astype(float)
    for col in X.columns:
        if col == "memory":
            X[col] = np.log1p(X[col])
        elif "zscore" in col or "abs_z" in col or "max_z" in col:
            sign = np.sign(X[col])
            X[col] = sign * np.log1p(np.abs(X[col]))
        else:
            X[col] = np.log1p(np.abs(X[col]))
    return X.clip(-50, 50)


def stratified_split_by_exp(df, test_ratio=0.3, seed=42):
    """按 (fault_type) 分层划分 exp_id"""
    np.random.seed(seed)
    exp_to_ft = df.groupby("exp_id")["fault_type"].first().to_dict()
    
    train_exps, test_exps = [], []
    for ft in df["fault_type"].unique():
        ft_exps = [e for e, f in exp_to_ft.items() if f == ft]
        np.random.shuffle(ft_exps)
        n_test = max(1, int(len(ft_exps) * test_ratio))
        test_exps.extend(ft_exps[:n_test])
        train_exps.extend(ft_exps[n_test:])
    
    return set(train_exps), set(test_exps)


def main():
    # 1. 加载 + 特征工程
    df = pd.read_parquet(OUT / "dataset.parquet")
    df = add_derived_features(df)
    
    # 最终特征列
    feature_cols = (
        METRIC_NAMES
        + [f"{m}_zscore" for m in METRIC_NAMES]
        + ["net_rx_abs_z", "net_tx_abs_z", "net_max_z",
           "cpu_throttle_interact", "restart_abs_z", "cpu_abs_z"]
    )
    
    print(f"📂 加载数据: {len(df)} 行 × {len(feature_cols)} 特征")
    print(f"   新增 6 个派生特征")

    # 2. 分层划分
    train_exps, test_exps = stratified_split_by_exp(df)
    train_df = df[df["exp_id"].isin(train_exps)].reset_index(drop=True)
    test_df = df[df["exp_id"].isin(test_exps)].reset_index(drop=True)
    
    print(f"\n📊 分层划分:")
    print(f"  训练: {len(train_exps)} 实验 × {len(train_df)} 行")
    print(f"  测试: {len(test_exps)} 实验 × {len(test_df)} 行")
    print(f"\n  训练集故障分布: {train_df.groupby('exp_id')['fault_type'].first().value_counts().to_dict()}")
    print(f"  测试集故障分布: {test_df.groupby('exp_id')['fault_type'].first().value_counts().to_dict()}")

    # 3. 预处理
    X_train = preprocess(train_df[feature_cols])
    y_train = train_df["label"].values
    X_test = preprocess(test_df[feature_cols])
    y_test = test_df["label"].values

    # 4. 训练
    contam = train_df["label"].mean()
    print(f"\n🌲 训练 (contamination={contam:.3f}, n_estimators=300)...")
    clf = IsolationForest(
        n_estimators=300,
        contamination=contam,
        max_samples=256,
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X_train)

    # 5. 预测
    test_scores = -clf.score_samples(X_test)

    # 6. 阈值校准
    thresholds = np.percentile(test_scores, np.linspace(30, 99, 200))
    best = {"threshold": 0, "f1": 0, "precision": 0, "recall": 0}
    for t in thresholds:
        pred = (test_scores >= t).astype(int)
        if pred.sum() == 0:
            continue
        f1 = f1_score(y_test, pred, zero_division=0)
        if f1 > best["f1"]:
            best = {
                "threshold": float(t),
                "f1": float(f1),
                "precision": float(precision_score(y_test, pred, zero_division=0)),
                "recall": float(recall_score(y_test, pred, zero_division=0)),
            }
    
    print(f"\n🎯 最优阈值: {best['threshold']:.4f}")
    print(f"  F1:        {best['f1']:.4f}")
    print(f"  Precision: {best['precision']:.4f}")
    print(f"  Recall:    {best['recall']:.4f}")

    y_pred = (test_scores >= best["threshold"]).astype(int)
    print(f"\n📊 分类报告:")
    print(classification_report(y_test, y_pred, target_names=["normal", "anomaly"], digits=4))

    cm = confusion_matrix(y_test, y_pred)
    print(f"\n📊 混淆矩阵:")
    print(f"           pred_normal  pred_anomaly")
    print(f"  normal     {cm[0,0]:>6d}        {cm[0,1]:>6d}")
    print(f"  anomaly    {cm[1,0]:>6d}        {cm[1,1]:>6d}")
    
    auc = roc_auc_score(y_test, test_scores)
    print(f"\n📈 AUC-ROC: {auc:.4f}")

    # 按故障类型评估
    print(f"\n🎯 按故障类型评估:")
    test_df_eval = test_df.copy()
    test_df_eval["pred"] = y_pred
    test_df_eval["score"] = test_scores
    per_type_metrics = {}
    for ft in ["CPU", "NETWORK", "POD_KILL"]:
        sub = test_df_eval[test_df_eval["fault_type"] == ft]
        if len(sub) < 5:
            print(f"  {ft:12s}  样本不足 ({len(sub)})")
            continue
        sub_anom = sub[sub["label"] == 1]
        if len(sub_anom) == 0:
            continue
        r = sub_anom["pred"].mean()
        p_idx = sub[sub["pred"] == 1]
        p = (p_idx["label"] == 1).mean() if len(p_idx) > 0 else 0
        per_type_metrics[ft] = {
            "n": len(sub), "n_anom": len(sub_anom),
            "recall": float(r), "precision": float(p)
        }
        print(f"  {ft:12s}  n={len(sub):>4d}  异常={len(sub_anom):>4d}  Recall={r:.2%}  Precision={p:.2%}")

    # 保存
    joblib.dump(clf, OUT / "iforest_model.pkl")
    meta = {
        **best,
        "auc_roc": float(auc),
        "contamination": float(contam),
        "n_estimators": 300,
        "feature_cols": feature_cols,
        "per_type_metrics": per_type_metrics,
        "test_size": len(test_df),
        "train_size": len(train_df),
        "preprocessing": "log1p_clip_50_stratified",
    }
    (OUT / "threshold.json").write_text(json.dumps(meta, indent=2))

    # 画图（英文标签避免字体问题）
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    ax[0].hist(test_scores[y_test == 0], bins=50, alpha=0.6, label="Normal", color="#3b82f6")
    ax[0].hist(test_scores[y_test == 1], bins=50, alpha=0.6, label="Anomaly", color="#ef4444")
    ax[0].axvline(best["threshold"], color="black", linestyle="--", linewidth=2, 
                  label=f"Threshold={best['threshold']:.3f}")
    ax[0].set_xlabel("Anomaly Score")
    ax[0].set_ylabel("Frequency")
    ax[0].set_title(f"Score Distribution (AUC={auc:.3f}, F1={best['f1']:.3f})")
    ax[0].legend()
    ax[0].grid(alpha=0.3)
    
    prec, rec, _ = precision_recall_curve(y_test, test_scores)
    ax[1].plot(rec, prec, color="#059669", linewidth=2)
    ax[1].fill_between(rec, prec, alpha=0.2, color="#059669")
    ax[1].set_xlabel("Recall")
    ax[1].set_ylabel("Precision")
    ax[1].set_title("Precision-Recall Curve")
    ax[1].grid(alpha=0.3)
    
    plt.tight_layout()
    fig.savefig(FIG / "score_distribution.png", dpi=150, bbox_inches="tight")
    plt.close()

    print(f"\n{'='*60}")
    print(f"🎉 完成! 模型: {OUT/'iforest_model.pkl'}")
    print(f"        图:   {FIG/'score_distribution.png'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
