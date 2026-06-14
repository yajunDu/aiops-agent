#!/usr/bin/env python3
"""
回放驱动的闭环演示入口（录视频 / 现场 demo 用）
================================================
不碰真集群也能跑完整条链：检测 → 根因定位 → SOP 自愈(dry-run) → 时间线。
真集群演示去掉 --dry-run 即可真执行 + 真验证。

用法：
  python run_demo.py --parquet experiments/metrics/<exp>.parquet
  python run_demo.py --parquet <...> --live        # 真执行（需集群+vLLM+Neo4j）
"""
from __future__ import annotations

import argparse

from aiops.perception.detector import detect_from_experiment_parquet
from aiops.orchestrator import run_closed_loop


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True, help="实验指标 parquet（回放驱动）")
    ap.add_argument("--live", action="store_true", help="真执行 kubectl + 真验证恢复")
    args = ap.parse_args()

    def on_event(stage, msg):
        icon = {"detect": "🔍", "diagnose": "🧠", "remediate": "🔧", "verify": "✅"}.get(stage, "·")
        print(f"  {icon} [{stage}] {msg}")

    print("=" * 64)
    print("🚀 闭环演示：检测 → 根因定位 → 自愈 → 恢复确认")
    print("=" * 64)

    slices = detect_from_experiment_parquet(args.parquet)
    results = run_closed_loop(slices=slices, dry_run=not args.live, on_event=on_event)

    print("\n" + "=" * 64)
    print("📋 结果汇总")
    print("=" * 64)
    for r in results:
        d = r.diagnosis
        print(f"\n切片 {r.slice_id}")
        print(f"  根因服务: {d.get('root_cause_service')}  类型: {d.get('fault_type')}  "
              f"置信度: {d.get('confidence')}")
        pp = d.get("propagation_path")
        if pp:
            print(f"  传播链: {' → '.join(pp.get('hops', []))}")
        if r.remediation:
            print(f"  自愈: {r.remediation.get('display_name')} "
                  f"[{r.remediation.get('risk_level')}] status={r.remediation.get('status')}")
        print(f"  恢复: {r.recovered}  MTTR: {r.mttr_sec}s")


if __name__ == "__main__":
    main()
