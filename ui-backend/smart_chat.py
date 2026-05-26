"""
智能 chat 模块
负责: 意图分类 + 上下文采集 + Agent 触发 + 结果包装
"""
from __future__ import annotations
import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

# 添加 agent 模块路径
AGENT_PATH = Path("~/aiops-project/system2/agent").expanduser()
TOOLS_PATH = Path("~/aiops-project/system2/agent/tools").expanduser()
sys.path.insert(0, str(AGENT_PATH))
sys.path.insert(0, str(TOOLS_PATH))

VLLM_URL = "http://localhost:8000/v1"
NAMESPACE = "train-ticket"


# ============================================================
# 意图分类
# ============================================================
DIAGNOSE_KEYWORDS = ["诊断", "怎么了", "出什么问题", "排查", "为什么", "为啥", "什么原因", "根因", "故障原因"]
STATUS_KEYWORDS = ["集群状态", "有什么问题", "现在怎么样", "健康状况", "异常服务", "哪些异常",
                   "什么异常", "系统状态", "出问题", "故障", "异常", "整体情况"]

# 已知服务名（用于从用户输入提取）
KNOWN_SERVICES = [
    "ts-seat-service", "ts-order-service", "ts-gateway-service", "ts-travel-service",
    "ts-auth-service", "ts-user-service", "ts-station-service", "ts-train-service",
    "ts-route-service", "ts-price-service", "ts-config-service", "ts-contacts-service",
    "ts-basic-service", "ts-payment-service", "ts-cancel-service", "ts-rebook-service",
    "ts-admin-basic-info-service", "ts-admin-order-service", "ts-admin-user-service",
    "ts-execute-service", "ts-food-service", "ts-news-service", "ts-notification-service",
    "ts-preserve-service", "ts-security-service", "ts-travel2-service", "ts-verification-code-service",
]


def extract_service_name(text: str) -> str | None:
    """从用户消息中提取服务名"""
    text_lower = text.lower()
    for svc in KNOWN_SERVICES:
        if svc.lower() in text_lower:
            return svc
    # 简短形式: "seat-service" / "seat" 等
    for svc in KNOWN_SERVICES:
        short = svc.replace("ts-", "").replace("-service", "")
        if short in text_lower and len(short) >= 4:
            return svc
    return None


def classify_intent(message: str) -> dict:
    """
    分类用户意图（关键词优先）
    返回: {intent: "diagnose"/"status"/"general", target_service: str|None}
    """
    msg = message.lower()
    target_service = extract_service_name(message)
    
    # 1. 诊断意图: 提到具体服务 + 有诊断词
    has_diagnose = any(kw in msg for kw in DIAGNOSE_KEYWORDS)
    if target_service and has_diagnose:
        return {"intent": "diagnose", "target_service": target_service}
    
    # 2. 服务名 + 模糊问题（"ts-seat-service 怎么了"）
    if target_service and any(w in msg for w in ["怎么", "什么", "发生", "状态", "情况", "如何"]):
        return {"intent": "diagnose", "target_service": target_service}
    
    # 3. 系统级状态查询
    if any(kw in msg for kw in STATUS_KEYWORDS):
        return {"intent": "status", "target_service": None}
    
    # 4. 默认: 通用知识问题
    return {"intent": "general", "target_service": target_service}


# ============================================================
# 实时上下文采集
# ============================================================
def kubectl_run(args: list, timeout: int = 5) -> str:
    """安全执行 kubectl 命令"""
    try:
        result = subprocess.run(
            ["kubectl"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip()
    except Exception as e:
        return ""


def get_abnormal_pods() -> list[dict]:
    """返回异常 Pod 列表"""
    out = kubectl_run([
        "get", "pods", "-n", NAMESPACE,
        "-o", "jsonpath={range .items[*]}"
        "{.metadata.name}|{.status.phase}|"
        "{.status.containerStatuses[0].ready}|"
        "{.status.containerStatuses[0].restartCount}|"
        "{.metadata.creationTimestamp}\\n{end}"
    ])
    
    abnormal = []
    for line in out.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        name, phase, ready, restarts = parts[0], parts[1], parts[2], parts[3]
        created = parts[4] if len(parts) > 4 else ""
        
        if phase != "Running" or ready != "true":
            # 提取服务名
            svc = re.sub(r'-[a-f0-9]{8,}-[a-z0-9]+$', '', name)
            abnormal.append({
                "name": name,
                "service": svc,
                "phase": phase,
                "ready": ready,
                "restarts": restarts,
                "created": created,
            })
    return abnormal


def get_active_chaos() -> list[dict]:
    """返回活跃 Chaos 实验"""
    out = kubectl_run([
        "get", "podchaos", "-n", "chaos-mesh",
        "-o", "jsonpath={range .items[*]}"
        "{.metadata.name}|{.spec.action}|"
        "{.spec.selector.labelSelectors.app}\\n{end}"
    ])
    
    chaos = []
    for line in out.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            chaos.append({"name": parts[0], "action": parts[1], "target": parts[2]})
    return chaos


def get_warning_events(target: str | None = None) -> list[dict]:
    """返回最近的 Warning 事件"""
    args = ["get", "events", "-n", NAMESPACE,
            "--sort-by=.lastTimestamp", "--field-selector=type=Warning",
            "-o", "jsonpath={range .items[*]}"
            "{.reason}|{.involvedObject.name}|{.message}\\n{end}"]
    
    out = kubectl_run(args)
    events = []
    for line in out.split("\n")[-15:]:
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            ev = {"reason": parts[0], "object": parts[1], "message": parts[2][:120]}
            if target is None or target in parts[1]:
                events.append(ev)
    return events[-5:]


# ============================================================
# 调 Qwen
# ============================================================
def call_qwen(messages: list, max_tokens: int = 800, temperature: float = 0.3) -> str:
    try:
        r = requests.post(
            f"{VLLM_URL}/chat/completions",
            json={
                "model": "qwen2.5-7b",
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=45,
        )
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ LLM 调用失败: {e}"


# ============================================================
# 处理器: 系统状态查询
# ============================================================
def handle_status(message: str) -> dict:
    """处理"系统现在怎么样"类问题"""
    abnormal = get_abnormal_pods()
    chaos = get_active_chaos()
    events = get_warning_events()
    
    # 构造上下文给 Qwen
    ctx_lines = []
    if abnormal:
        ctx_lines.append(f"【异常 Pod ({len(abnormal)} 个)】")
        for p in abnormal[:5]:
            ctx_lines.append(f"  - {p['name']}: phase={p['phase']}, ready={p['ready']}, restarts={p['restarts']}")
    else:
        ctx_lines.append("【当前 Pod 状态】 全部 Running 1/1 Ready")
    
    if chaos:
        ctx_lines.append(f"\n【活跃 Chaos 实验 ({len(chaos)} 个)】")
        for c in chaos:
            ctx_lines.append(f"  - {c['name']}: action={c['action']}, target={c['target']}")
    
    if events:
        ctx_lines.append(f"\n【最近 Warning 事件】")
        for e in events:
            ctx_lines.append(f"  - {e['reason']} on {e['object']}: {e['message']}")
    
    ctx_str = "\n".join(ctx_lines)
    
    system_prompt = f"""你是 K8s 集群运维专家助手。请基于以下实时数据回答用户问题。

【TrainTicket 集群实时状态】
{ctx_str}

【回答要求】
- 必须引用上面具体的 Pod 名和事件
- 给出明确的判断（不只是建议）  
- 如果发现异常服务，最后引导用户："如需详细根因分析，请输入：诊断 ts-xxx-service"
- 简洁专业，不要套话
"""
    
    reply = call_qwen([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ])
    
    return {
        "reply": reply,
        "intent": "status",
        "context_injected": True,
        "abnormal_count": len(abnormal),
        "active_chaos": len(chaos),
    }


# ============================================================
# 处理器: 触发 Agent 真实诊断
# ============================================================
def get_current_pod_for_service(target_service: str) -> str | None:
    out = kubectl_run([
        "get", "pod", "-n", NAMESPACE,
        "-l", f"app={target_service}",
        "-o", "jsonpath={.items[0].metadata.name}"
    ], timeout=10)
    return out or None


def handle_diagnose(message: str, target_service: str) -> dict:
    """处理"诊断 ts-xxx-service"类问题 - 触发真 Agent"""
    
    # 1. 获取当前 Pod
    current_pod = get_current_pod_for_service(target_service)
    if not current_pod:
        return {
            "reply": f"❌ 找不到 {target_service} 的运行实例，可能服务名错误或 Pod 未启动。\n\n请检查服务名是否正确。",
            "intent": "diagnose",
            "error": "pod_not_found",
        }
    
    # 2. 构造 slice_info 喂给 Agent
    now = int(time.time())
    slice_info = {
        "t_start": now - 300,  # 最近 5 分钟
        "t_end": now,
        "pods": [current_pod],
        "max_score": 0.85,  # 用户主动请求诊断，给个高分
        "exp_id": f"manual_chat_{int(time.time())}",
    }
    
    # 3. 触发 Agent
    try:
        from agent_core import build_agent
        from tools_prom_replay import set_active_experiment
        
        # 用 live 模式而不是历史回放
        set_active_experiment(None)
        
        agent = build_agent()
        t0 = time.time()
        result = agent.invoke({"slice_info": slice_info})
        elapsed = round(time.time() - t0, 1)
        
        root_cause = result.get("root_cause", "未能给出明确根因")
        confidence = result.get("confidence", 0.0)
        evidence = result.get("evidence", [])
        pred_type = result.get("pred_fault_type", "UNKNOWN")
        
    except Exception as e:
        return {
            "reply": f"❌ Agent 推理失败: {str(e)[:200]}\n\n请检查 vLLM 和 Neo4j 服务是否正常运行。",
            "intent": "diagnose",
            "error": str(e),
        }
    
    # 4. 用 Qwen 把 Agent 结果包装成自然语言
    tool_calls_summary = []
    for i, ev in enumerate(evidence[:5], 1):
        tool_calls_summary.append(f"  {i}. {ev['tool']}({json.dumps(ev['args'], ensure_ascii=False)})")
    tool_str = "\n".join(tool_calls_summary) if tool_calls_summary else "  (无)"
    
    wrap_prompt = f"""你是运维 AI 助手。Agent 刚完成对 {target_service} 的根因诊断。
请把以下技术结果整理成专业、清晰的中文报告给用户看。

【Agent 推理结果】
- 故障类型: {pred_type}
- 置信度: {confidence}
- 推理耗时: {elapsed}s
- 工具调用 ({len(evidence)} 次):
{tool_str}
- 根因描述: {root_cause}

【输出格式要求】
用以下结构组织回答，使用 emoji 强调:
🎯 根因诊断报告: {target_service}
📊 故障类型: ...
✅ 置信度: ...
⏱️ 分析耗时: {elapsed}s

【诊断依据】
- 引用上面的工具调用证据
- 列出 2-3 条关键证据

【根因解释】
- 用 2-3 句话解释为什么是这个故障

【建议处置】
- 基于故障类型给具体操作步骤
- POD_KILL → 建议 SOP: restart_pod
- CPU → 建议 SOP: scale_deployment  
- NETWORK → 建议 SOP: network_policy_isolate

不要套话，简洁专业。
"""
    
    reply = call_qwen([
        {"role": "system", "content": "你是云原生运维专家，正在为用户解读 AI Agent 的诊断结果。"},
        {"role": "user", "content": wrap_prompt},
    ], max_tokens=1000)
    
    return {
        "reply": reply,
        "intent": "diagnose",
        "target_service": target_service,
        "agent_result": {
            "pred_fault_type": pred_type,
            "confidence": confidence,
            "elapsed": elapsed,
            "n_tools": len(evidence),
        },
        "context_injected": True,
    }


# ============================================================
# 处理器: 通用知识问答
# ============================================================
def handle_general(message: str, history: list) -> dict:
    """通用知识问答（论文/算法/概念等）"""
    
    # 加一点点上下文，让 Qwen 知道是在哪个项目
    system_prompt = """你是一名云原生 SRE 专家助手。
当前项目是【基于大模型的运维智能体】，使用 K8s + Prometheus + Neo4j + LLM Agent。
回答专业、简洁，避免套话。"""
    
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})
    
    reply = call_qwen(messages, max_tokens=600)
    
    return {
        "reply": reply,
        "intent": "general",
        "context_injected": False,
    }


# ============================================================
# 主入口
# ============================================================
def smart_chat(message: str, history: list = None) -> dict:
    """智能 chat 主入口 - 分意图处理"""
    history = history or []
    
    # 分类
    classified = classify_intent(message)
    intent = classified["intent"]
    target = classified["target_service"]
    
    print(f"[smart_chat] intent={intent}, target={target}, msg={message[:60]}", flush=True)
    
    # 分发
    if intent == "diagnose" and target:
        return handle_diagnose(message, target)
    elif intent == "status":
        return handle_status(message)
    else:
        return handle_general(message, history)


if __name__ == "__main__":
    # 测试
    test_cases = [
        "系统现在有什么问题？",
        "诊断 ts-seat-service",
        "ts-order-service 怎么了？",
        "什么是孤立森林算法？",
    ]
    for q in test_cases:
        print(f"\n{'='*60}")
        print(f"Q: {q}")
        r = smart_chat(q)
        print(f"Intent: {r.get('intent')}")
        print(f"Reply: {r.get('reply')[:200]}...")
