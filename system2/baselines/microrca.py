"""
基线 2: MicroRCA（简化版）
============================
论文 [Wu et al. 2020 ICSOC] 核心思想：
  1. 从 Service 调用图构建带权图
  2. 异常 service 的指标偏离度作为节点权重
  3. 跑 Personalized PageRank，rank 最高的 service 是根因
  4. 根据该 service 的 dominant metric 判断 fault_type

简化点（保留 PageRank 核心，砍掉因果图自动学习部分）：
  - 调用图：用我们 Neo4j 里的 CALLS 关系
  - 节点权重：用每个 service 指标的 max/mean
  - 根因：rank 最高的 service
  - fault_type：看该 service 哪个指标偏离最大
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import networkx as nx
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "agent" / "tools"))
from tools_neo4j import query_graph_topology

EXP_DIR = Path("~/aiops-project/experiments").expanduser()
METRICS_DIR = EXP_DIR / "metrics"


def build_service_graph():
    """从 Neo4j 拉 Service 调用图"""
    result = json.loads(query_graph_topology(
        "MATCH (a:Service)-[:CALLS]->(b:Service) RETURN a.name AS src, b.name AS dst"
    ))
    G = nx.DiGraph()
    for row in result.get("rows", []):
        G.add_edge(row["src"], row["dst"])
    # 拉所有 Service 作为节点（包括孤立的）
    result = json.loads(query_graph_topology("MATCH (s:Service) RETURN s.name AS name"))
    for row in result.get("rows", []):
        G.add_node(row["name"])
    return G


def compute_anomaly_scores(exp_id: str, allowed_services: set = None) -> dict:
    """对每个 service，计算其异常分数（综合 CPU/network/restart 偏离度）"""
    pq_path = METRICS_DIR / f"{exp_id}.parquet"
    if not pq_path.exists():
        return {}
    df = pd.read_parquet(pq_path)
    
    scores = {}
    metric_signals = {}
    
    for pod_name, sub in df.groupby("pod"):
        if not isinstance(pod_name, str) or not pod_name.startswith("ts-"):
            continue
        # 把 pod 名转回 service 名（去尾部 hash）
        parts = pod_name.rsplit("-", 2)
        service = parts[0] if len(parts) >= 3 else pod_name
        if allowed_services is not None and service not in allowed_services:
            continue
        
        # 综合分数：多指标偏离度
        score = 0.0
        signals = {}
        for metric in ["cpu", "net_rx", "net_tx", "restart"]:
            vals = sub[sub["metric_name"] == metric]["value"].astype(float)
            if vals.empty or vals.mean() == 0:
                continue
            ratio = vals.max() / max(vals.mean(), 1e-9)
            signals[metric] = ratio
            if metric == "restart":
                # restart 跳变是最强信号
                delta = vals.max() - vals.min()
                if delta >= 1:
                    score += 10 * delta
            else:
                if ratio > 1.5:
                    score += ratio - 1
        
        if service in scores:
            scores[service] = max(scores[service], score)
        else:
            scores[service] = score
            metric_signals[service] = signals
    
    return scores, metric_signals


def predict_one(exp_id: str, G: nx.DiGraph, target_service: str) -> dict:
    # 限定 target_service 和其上下游邻居
    neighbors = set([target_service])
    if target_service in G:
        neighbors |= set(G.predecessors(target_service))
        neighbors |= set(G.successors(target_service))
    scores, signals = compute_anomaly_scores(exp_id, allowed_services=neighbors)
    if not scores:
        return {"pred_service": "", "pred_fault_type": "UNKNOWN", "reason": "no scores"}
    
    # Personalized PageRank：以异常 service 作为种子
    personalization = {n: 0.0 for n in G.nodes()}
    total = sum(scores.values())
    if total == 0:
        return {"pred_service": "", "pred_fault_type": "UNKNOWN", "reason": "all zero"}
    for s, sc in scores.items():
        if s in G:
            personalization[s] = sc / total
    
    try:
        pr = nx.pagerank(G, alpha=0.85, personalization=personalization,
                         max_iter=100, tol=1e-4)
    except Exception:
        # G 可能有孤立节点或不连通，退化用 score 直接选
        pr = scores
    
    # 找 rank 最高的 service
    candidates = {s: r for s, r in pr.items() if scores.get(s, 0) > 0}
    if not candidates:
        return {"pred_service": "", "pred_fault_type": "UNKNOWN",
                "reason": "no anomalous service"}
    
    top = max(candidates.items(), key=lambda x: x[1])[0]
    sig = signals.get(top, {})
    
    # 根据该 service 的 dominant signal 判 fault_type
    pred_type = "UNKNOWN"
    if "restart" in sig or any("restart" in str(k) for k in sig):
        # 重启信号最强（compute_anomaly_scores 里加了 10*delta）
        # 但简化：如果原 scores[top] 很高且包含 restart，判 POD_KILL
        # 这里再算一次 restart
        pq = pd.read_parquet(METRICS_DIR / f"{exp_id}.parquet")
        restart_data = pq[(pq["pod"].astype(str).str.startswith(top)) & 
                          (pq["metric_name"] == "restart")]["value"].astype(float)
        if not restart_data.empty and (restart_data.max() - restart_data.min()) >= 1:
            return {"pred_service": top, "pred_fault_type": "POD_KILL",
                    "reason": f"restart_jump on {top}",
                    "confidence": 0.9}
    
    # 比较 CPU vs network 信号
    cpu_sig = sig.get("cpu", 1.0)
    net_sig = max(sig.get("net_rx", 1.0), sig.get("net_tx", 1.0))
    if cpu_sig > net_sig:
        pred_type = "CPU"
    elif net_sig > 2:
        pred_type = "NETWORK"
    else:
        pred_type = "CPU"  # 兜底
    
    return {"pred_service": top, "pred_fault_type": pred_type,
            "reason": f"top_service={top} cpu_sig={cpu_sig:.2f} net_sig={net_sig:.2f}",
            "confidence": 0.7}


def main():
    print("🕸️  构建 Service 调用图...")
    G = build_service_graph()
    print(f"   节点: {G.number_of_nodes()}  边: {G.number_of_edges()}")
    
    exp_df = pd.read_csv(Path("~/aiops-project/system1/outputs/experiment_results.csv").expanduser())
    detected = exp_df[exp_df["detected"] == True]
    
    results = []
    for _, gt in detected.iterrows():
        exp_id = gt["exp_id"]
        truth = gt["fault_type"]
        pred = predict_one(exp_id, G, gt['target_service'])
        results.append({
            "exp_id": exp_id,
            "truth_fault_type": truth,
            "pred_fault_type": pred["pred_fault_type"],
            "pred_service": pred.get("pred_service", ""),
            "reason": pred["reason"][:80],
            "correct": pred["pred_fault_type"] == truth,
        })
    
    df = pd.DataFrame(results)
    out = Path(__file__).parent / "microrca_predictions.csv"
    df.to_csv(out, index=False)
    
    print(f"\n📊 MicroRCA 基线结果（{len(df)} 个实验）")
    print(f"  整体 Acc@1: {df['correct'].mean():.1%}")
    for ft, sub in df.groupby("truth_fault_type"):
        print(f"  {ft:12s} n={len(sub):3d}  Acc={sub['correct'].mean():.1%}")
    print(f"\n💾 {out}")


if __name__ == "__main__":
    main()
