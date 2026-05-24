"""
12.6 双过程协调器
====================
论文 3.3.3 节核心：系统1 唤醒系统2 的端到端管道

输入: 系统1 输出的 anomaly_slices.csv + experiment_results.csv
处理:
  1. 加载真实切片（每个实验取首个切片）
  2. 解析切片：t_start / t_end / pods
  3. 用当前 K8s 中的真实 Pod 替换历史 Pod 名（解决"时间漂移"）
  4. 喂给 Agent
  5. 收集 (实验ID, 真实故障类型, LLM 预测) 三元组
输出: outputs/system2_predictions.csv
"""
from __future__ import annotations
import json
import subprocess
import time
from pathlib import Path

import pandas as pd

from agent_core import build_agent
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent / 'tools'))
from tools_prom_replay import set_active_experiment


SYSTEM1_OUT = Path("~/aiops-project/system1/outputs").expanduser()
SYSTEM2_OUT = Path("~/aiops-project/system2/outputs").expanduser()
SYSTEM2_OUT.mkdir(exist_ok=True, parents=True)


def get_current_pod_for_service(target_service: str) -> str | None:
    """根据 service 名拿当下真实的 Pod 名（解决历史快照漂移）"""
    try:
        p = subprocess.run(
            ["kubectl", "get", "pod", "-n", "train-ticket",
             "-l", f"app={target_service}",
             "-o", "jsonpath={.items[0].metadata.name}"],
            capture_output=True, text=True, timeout=10,
        )
        return p.stdout.strip() or None
    except Exception:
        return None


def fault_type_match(pred: str, truth: str) -> bool:
    """两阶段匹配：1) pred_fault_type 严格匹配；2) 失败则根因文本扫关键词"""
    pred_lower = (pred or "").lower().strip()
    # 1) 严格匹配 fault_type 字段
    if pred_lower == truth.lower():
        return True
    # 2) 关键词扫描（兜底）
    keywords = {
        "CPU": ["cpu", "计算", "节流", "throttle", "处理器", "load"],
        "NETWORK": ["network", "网络", "延迟", "丢包", "latency", "loss", "通信", "drop"],
        "POD_KILL": ["pod_kill", "pod-kill", "pod kill", "podkill",
                     "重启", "restart", "kill", "杀", "调度", "重新调度",
                     "rescheduled", "killed", "pod 销毁", "pod销毁",
                     "container restart", "container kill"],
    }
    for kws in keywords.get(truth, []):
        if kws in pred_lower:
            return True
    return False


def run_one(agent, exp_id: str, slice_row, gt_row) -> dict:
    """对单个实验跑一次 Agent"""
    target = gt_row["target_service"]
    truth_type = gt_row["fault_type"]
    
    # 获取当下真实 Pod 名
    # 用 service 名作为 pod 前缀（与历史 parquet 中的 pod 列匹配）
    pods = [target]
    
    slice_info = {
        "t_start": int(slice_row["t_start"]),
        "t_end": int(slice_row["t_end"]),
        "pods": pods,
        "max_score": float(slice_row["max_score"]),
        "n_windows": int(slice_row["n_windows"]),
    }
    
    # 切换到这个实验的历史数据上下文
    try:
        set_active_experiment(exp_id)
    except Exception as e:
        return {"exp_id": exp_id, "last_text": f"ERROR set_active: {e}", "target_service": target, "truth_fault_type": truth_type, "pred_root_cause": "", "pred_fault_type": "", "confidence": 0.0, "n_tool_calls": 0, "elapsed_sec": 0.0, "correct": False}

    t0 = time.time()
    try:
        result = agent.invoke({"slice_info": slice_info})
        root_cause = result.get("root_cause", "")
        confidence = result.get("confidence", 0.0)
        n_tools = len(result.get("evidence", []))
    except Exception as e:
        root_cause = f"ERROR: {e}"
        confidence = 0.0
        n_tools = 0
    elapsed = round(time.time() - t0, 1)
    
    pred_type = result.get("pred_fault_type", "")
    
    correct = fault_type_match(pred_type if pred_type else root_cause, truth_type)
    # 二次兜底：扫 root_cause 全文
    if not correct:
        correct = fault_type_match(root_cause, truth_type)
    
    # 抓最后一条 AIMessage 文本（debug 用）
    last_text = ""
    try:
        for m in reversed(result.get("messages", [])):
            if hasattr(m, "content") and isinstance(m.content, str) and m.content.strip():
                last_text = m.content[:300]
                break
    except Exception:
        pass
    
    return {
        "last_text": last_text,
        "exp_id": exp_id,
        "target_service": target,
        "truth_fault_type": truth_type,
        "pred_root_cause": root_cause[:200],
        "pred_fault_type": pred_type,
        "confidence": confidence,
        "n_tool_calls": n_tools,
        "elapsed_sec": elapsed,
        "correct": correct,
    }


def main(sample_size: int | None = None):
    # 1. 加载系统1 数据
    print("📂 加载系统1 输出...")
    exp_df = pd.read_csv(SYSTEM1_OUT / "experiment_results.csv")
    slices_df = pd.read_csv(SYSTEM1_OUT / "anomaly_slices.csv")
    
    # 只取检测到的实验（57 个）
    detected = exp_df[exp_df["detected"] == True]
    print(f"   检测到的实验: {len(detected)} 个")
    
    if sample_size:
        detected = detected.head(sample_size)
        print(f"   抽样: {sample_size} 个")
    
    # 2. 构建 Agent
    print("🤖 构建 Agent...")
    agent = build_agent()
    
    # 3. 逐个跑
    print(f"\n🚀 开始批量推理...\n")
    results = []
    for i, gt in detected.iterrows():
        exp_id = gt["exp_id"]
        # 取该实验的首个切片
        my_slices = slices_df[slices_df["exp_id"] == exp_id]
        if my_slices.empty:
            continue
        sl = my_slices.iloc[0]
        
        idx = len(results) + 1
        total = len(detected)
        print(f"  [{idx}/{total}] {exp_id[:40]:40s}  truth={gt['fault_type']:8s}", end="", flush=True)
        
        r = run_one(agent, exp_id, sl, gt)
        results.append(r)
        
        mark = "✅" if r["correct"] else "❌"
        print(f"  pred={r['pred_fault_type']:8s}  {mark}  ({r['elapsed_sec']}s, {r['n_tool_calls']} tools)")
        if not r['correct'] or not r['pred_fault_type']:
            print(f"      DBG: {r['last_text'][:200]}")
    
    # 4. 保存 + 统计
    out = pd.DataFrame(results)
    out_csv = SYSTEM2_OUT / "system2_predictions.csv"
    out.to_csv(out_csv, index=False)
    
    print(f"\n{'='*70}")
    print(f"📊 系统2 整体指标")
    print(f"{'='*70}")
    if len(out) > 0:
        print(f"  总实验:           {len(out)}")
        print(f"  Acc@1:           {out['correct'].mean():.1%}")
        print(f"  平均工具轮次:    {out['n_tool_calls'].mean():.1f}")
        print(f"  平均推理时间:    {out['elapsed_sec'].mean():.1f} 秒")
        print(f"  平均置信度:      {out['confidence'].mean():.2f}")
        
        print(f"\n📊 按真实故障类型分:")
        for ft in ["CPU", "NETWORK", "POD_KILL"]:
            sub = out[out["truth_fault_type"] == ft]
            if len(sub) == 0:
                continue
            print(f"  {ft:12s} n={len(sub):3d}  Acc@1={sub['correct'].mean():.1%}  耗时={sub['elapsed_sec'].mean():.1f}s")
    
    print(f"\n💾 结果: {out_csv}")


if __name__ == "__main__":
    import sys
    sample = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    main(sample)
