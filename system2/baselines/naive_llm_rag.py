"""
基线 3: Naive LLM + RAG
========================
设计：
  - 用 vLLM 跑 Qwen2.5-7B（和本文同模型，控制变量）
  - 把所有 8 类指标的统计摘要 + 拓扑信息一次性塞进 prompt（"RAG"语义）
  - 不调工具，不迭代，单次问答出根因
  
对比本文的差异：
  - 本文：双过程 + tool calling + Cypher 推理（多轮）
  - 本基线：所有数据一次性丢给 LLM（单轮）
  
预期：CPU 高，NETWORK 中等（LLM 一次性看不清），POD_KILL 一般
"""
from __future__ import annotations
import sys as _s; from pathlib import Path as _P
_s.path.insert(0, str(_P(__file__).resolve().parents[2]))
import json
import sys
from pathlib import Path

import pandas as pd
from openai import OpenAI

from aiops_paths import EXP_DIR, SYSTEM1_OUT
METRICS_DIR = EXP_DIR / "metrics"

VLLM_URL = "http://localhost:8000/v1"
MODEL = "qwen2.5-7b"

# 与本文一致的诊断提示（但所有信息一次性给）
SYSTEM_PROMPT = """你是云原生 SRE 根因诊断专家。系统1 检测到异常切片，请根据给定的全部指标数据，直接给出根因诊断。

【诊断要点】
- cpu / throttle 异常高 → CPU 故障
- network 流量异常 / net_drop 上升 → NETWORK 故障
- restart 计数跳变 → POD_KILL 故障

【输出】严格 JSON：
{"root_cause": "简洁中文", "confidence": 0.0-1.0, "fault_type": "CPU或NETWORK或POD_KILL", "affected_service": "ts-xxx"}"""


def get_all_metrics_summary(exp_id: str, target_service: str) -> str:
    """聚合该实验中目标 service 的所有指标摘要"""
    pq = METRICS_DIR / f"{exp_id}.parquet"
    if not pq.exists():
        return "无数据"
    df = pd.read_parquet(pq)
    target_df = df[df["pod"].astype(str).str.startswith(target_service)]
    if target_df.empty:
        return f"未找到 {target_service} 的数据"
    
    lines = [f"# 异常切片信息\n- 目标服务: {target_service}\n\n# 指标摘要"]
    for metric in ["cpu", "memory", "net_rx", "net_tx",
                   "net_rx_drop", "net_tx_drop", "cpu_throttle", "restart"]:
        vals = target_df[target_df["metric_name"] == metric]["value"].astype(float)
        if vals.empty:
            continue
        line = (f"- {metric}: min={vals.min():.4f}, max={vals.max():.4f}, "
                f"mean={vals.mean():.4f}, latest={vals.iloc[-1]:.4f}")
        if metric == "restart":
            delta = vals.max() - vals.min()
            line += f"  [restart_jump={delta:.0f}]"
        elif vals.mean() > 0:
            ratio = vals.max() / vals.mean()
            if ratio > 3:
                line += f"  [峰均比={ratio:.2f} ⚠️ 异常峰值]"
        lines.append(line)
    return "\n".join(lines)


def predict_one(client: OpenAI, exp_id: str, target_service: str) -> dict:
    summary = get_all_metrics_summary(exp_id, target_service)
    
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{summary}\n\n请直接输出 JSON 诊断。"},
            ],
            temperature=0.1,
            max_tokens=300,
        )
        text = resp.choices[0].message.content or ""
        # 解析 JSON
        l, r = text.find("{"), text.rfind("}")
        if l >= 0 and r > l:
            parsed = json.loads(text[l:r+1])
            return {
                "pred_fault_type": str(parsed.get("fault_type", "UNKNOWN")).upper(),
                "root_cause": parsed.get("root_cause", ""),
                "confidence": float(parsed.get("confidence", 0.5)),
            }
    except Exception as e:
        return {"pred_fault_type": "ERROR", "root_cause": str(e)[:100], "confidence": 0.0}
    
    return {"pred_fault_type": "UNKNOWN", "root_cause": text[:100], "confidence": 0.0}


def main():
    client = OpenAI(base_url=VLLM_URL, api_key="dummy")
    
    exp_df = pd.read_csv((SYSTEM1_OUT / "experiment_results.csv"))
    detected = exp_df[exp_df["detected"] == True]
    
    results = []
    import time
    for i, (_, gt) in enumerate(detected.iterrows(), 1):
        t0 = time.time()
        pred = predict_one(client, gt["exp_id"], gt["target_service"])
        elapsed = round(time.time() - t0, 1)
        truth = gt["fault_type"]
        correct = pred["pred_fault_type"] == truth
        results.append({
            "exp_id": gt["exp_id"],
            "truth_fault_type": truth,
            "pred_fault_type": pred["pred_fault_type"],
            "root_cause": pred["root_cause"][:80],
            "confidence": pred["confidence"],
            "elapsed_sec": elapsed,
            "correct": correct,
        })
        mark = "✅" if correct else "❌"
        print(f"  [{i}/{len(detected)}] {gt['exp_id'][:35]:35s} truth={truth:8s} pred={pred['pred_fault_type']:10s} {mark} ({elapsed}s)")
    
    df = pd.DataFrame(results)
    out = Path(__file__).parent / "naive_llm_predictions.csv"
    df.to_csv(out, index=False)
    
    print(f"\n📊 Naive LLM + RAG 基线（{len(df)} 个实验）")
    print(f"  整体 Acc@1:     {df['correct'].mean():.1%}")
    print(f"  平均耗时:        {df['elapsed_sec'].mean():.1f}s")
    print(f"  平均置信度:      {df['confidence'].mean():.2f}")
    for ft, sub in df.groupby("truth_fault_type"):
        print(f"  {ft:12s} n={len(sub):3d}  Acc={sub['correct'].mean():.1%}")


if __name__ == "__main__":
    main()
