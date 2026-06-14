"""
评测脚本（出项目文档的指标表）
================================
两层评测：
  系统1（离线，无需 LLM）：检测率 / 告警压缩率 ACR / MTTD
  候选质量（离线，无需 LLM）：注入目标在 Top-K 嫌疑中的命中率 Acc@1/@3/@5
                               ——这是系统2 定位的输入质量，诚实反映在线难度
  系统2（需 vLLM + Neo4j）：服务级根因定位 Acc@1 —— 在集群上用 --with-agent 跑

用法：
  python experiments/evaluate.py --metrics-dir experiments/metrics \\
         --gt-dir experiments/ground-truth
  （加 --with-agent 同时评估系统2，需要 vLLM + Neo4j 在线）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiops.perception.detector import detect_from_experiment_parquet
from aiops.core.contracts import AnomalySlice


def evaluate(metrics_dir: str, gt_dir: str, with_agent: bool = False) -> dict:
    md, gd = Path(metrics_dir), Path(gt_dir)
    rows = []
    for pq in sorted(md.glob("*.parquet")):
        gt_path = gd / f"{pq.stem}.json"
        if not gt_path.exists():
            continue
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        target = gt["target_service"]
        fault = gt["fault_type"]

        slices = detect_from_experiment_parquet(str(pq))
        detected = len(slices) > 0
        # 候选质量：取所有切片里目标的最好排名
        best_rank = 99
        for sl in slices:
            if target in sl.suspect_services:
                best_rank = min(best_rank, sl.suspect_services.index(target) + 1)

        row = {"exp": pq.stem, "fault_type": fault, "target": target,
               "detected": detected, "target_rank": best_rank,
               "acc@1": best_rank == 1, "acc@3": best_rank <= 3, "acc@5": best_rank <= 5}

        if with_agent and slices:
            from aiops.cognition.agent import diagnose
            from aiops.cognition.tools import metric_tools
            metric_tools.set_active_experiment(str(pq))   # 让 agent 的指标工具回放本实验
            dg = diagnose(slices[0])
            row["agent_root"] = dg.root_cause_service
            row["agent_acc@1"] = (dg.root_cause_service == target)
            row["agent_type_ok"] = (dg.fault_type.value == fault)
        rows.append(row)

    return _summarize(rows, with_agent)


def _summarize(rows: list[dict], with_agent: bool) -> dict:
    if not rows:
        return {"error": "无有效实验"}
    n = len(rows)

    def rate(key):
        return round(sum(1 for r in rows if r.get(key)) / n, 3)

    summary = {
        "n_experiments": n,
        "detection_rate": rate("detected"),
        "candidate_acc@1": rate("acc@1"),
        "candidate_acc@3": rate("acc@3"),
        "candidate_acc@5": rate("acc@5"),
        "by_fault_type": {},
    }
    for ft in sorted(set(r["fault_type"] for r in rows)):
        sub = [r for r in rows if r["fault_type"] == ft]
        m = len(sub)
        summary["by_fault_type"][ft] = {
            "n": m,
            "acc@1": round(sum(r["acc@1"] for r in sub) / m, 3),
            "acc@3": round(sum(r["acc@3"] for r in sub) / m, 3),
        }
    if with_agent:
        ag = [r for r in rows if "agent_acc@1" in r]
        if ag:
            summary["agent_service_acc@1"] = round(sum(r["agent_acc@1"] for r in ag) / len(ag), 3)
            summary["agent_type_acc"] = round(sum(r["agent_type_ok"] for r in ag) / len(ag), 3)
    summary["_rows"] = rows
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics-dir", default="experiments/metrics")
    ap.add_argument("--gt-dir", default="experiments/ground-truth")
    ap.add_argument("--with-agent", action="store_true")
    ap.add_argument("--out", default="experiments/eval_result.json")
    args = ap.parse_args()

    result = evaluate(args.metrics_dir, args.gt_dir, args.with_agent)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 60)
    print("📊 评测结果")
    print("=" * 60)
    for k, v in result.items():
        if k == "_rows":
            continue
        print(f"  {k}: {v}")
    print(f"\n💾 明细已存: {args.out}")


if __name__ == "__main__":
    main()
