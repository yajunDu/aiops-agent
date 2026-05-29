"""
智能 chat 模块（v3 - 纯数据驱动，无 chaos 标签，与生产环境一致）
负责: 意图分类 + 上下文采集 + Agent 触发 + 结果包装
"""
from __future__ import annotations
import sys as _s; from pathlib import Path as _P
_s.path.insert(0, str(_P(__file__).resolve().parents[1]))
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

# 添加 agent 模块路径
from aiops_paths import AGENT_PATH, TOOLS_PATH
sys.path.insert(0, str(AGENT_PATH))
sys.path.insert(0, str(TOOLS_PATH))

VLLM_URL = "http://localhost:8000/v1"
NAMESPACE = "train-ticket"

# chaos action → 论文故障类型术语
FAULT_TYPE_MAP = {
    "pod-kill": "POD_KILL",
    "pod-failure": "POD_KILL",
    "container-kill": "POD_KILL",
    "network-delay": "NETWORK",
    "network-loss": "NETWORK",
    "network-partition": "NETWORK",
    "network-duplicate": "NETWORK",
    "network-corrupt": "NETWORK",
    "cpu-stress": "CPU",
    "stress": "CPU",
    "memory-stress": "CPU",
}

# 故障类型 → 推荐 SOP
SOP_MAP = {
    "POD_KILL": "restart_pod",
    "CPU": "scale_deployment",
    "NETWORK": "network_policy_isolate",
}


# ============================================================
# 意图分类
# ============================================================
DIAGNOSE_KEYWORDS = ["诊断", "怎么了", "出什么问题", "排查", "为什么", "为啥", "什么原因", "根因", "故障原因"]
STATUS_KEYWORDS = ["集群状态", "有什么问题", "现在怎么样", "健康状况", "异常服务", "哪些异常",
                   "什么异常", "系统状态", "出问题", "故障", "异常", "整体情况"]

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
    text_lower = text.lower()
    for svc in KNOWN_SERVICES:
        if svc.lower() in text_lower:
            return svc
    for svc in KNOWN_SERVICES:
        short = svc.replace("ts-", "").replace("-service", "")
        if short in text_lower and len(short) >= 4:
            return svc
    return None


def classify_intent(message: str) -> dict:
    msg = message.lower()
    target_service = extract_service_name(message)

    has_diagnose = any(kw in msg for kw in DIAGNOSE_KEYWORDS)
    if target_service and has_diagnose:
        return {"intent": "diagnose", "target_service": target_service}
    if target_service and any(w in msg for w in ["怎么", "什么", "发生", "状态", "情况", "如何"]):
        return {"intent": "diagnose", "target_service": target_service}
    if any(kw in msg for kw in STATUS_KEYWORDS):
        return {"intent": "status", "target_service": None}
    return {"intent": "general", "target_service": target_service}


# ============================================================
# 实时上下文采集
# ============================================================
def kubectl_run(args: list, timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            ["kubectl"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def get_abnormal_pods() -> list[dict]:
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
            svc = re.sub(r'-[a-f0-9]{8,}-[a-z0-9]+$', '', name)
            try:
                restart_n = int(restarts)
            except (ValueError, TypeError):
                restart_n = 0
            abnormal.append({
                "name": name,
                "service": svc,
                "phase": phase,
                "ready": ready,
                "restarts": restarts,
                "restart_n": restart_n,
                "created": created,
            })
    return abnormal


def get_active_chaos() -> list[dict]:
    """返回活跃 Chaos 实验（覆盖 podchaos + stresschaos + networkchaos）"""
    chaos = []
    for kind in ["podchaos", "stresschaos", "networkchaos"]:
        out = kubectl_run([
            "get", kind, "-n", "chaos-mesh",
            "-o", "jsonpath={range .items[*]}"
            "{.metadata.name}|{.spec.action}|"
            "{.spec.selector.labelSelectors.app}\\n{end}"
        ])
        for line in out.split("\n"):
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 3 and parts[2]:
                action = parts[1] if parts[1] else kind.replace("chaos", "")
                # stresschaos 没有 action 字段，用 kind 推断
                if kind == "stresschaos" and not parts[1]:
                    action = "cpu-stress"
                chaos.append({"name": parts[0], "action": action, "target": parts[2], "kind": kind})
    return chaos


def get_warning_events(target: str | None = None) -> list[dict]:
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


def _scan_cpu_anomalies() -> list:
    """扫描所有核心服务的 CPU，返回峰均比>3 的异常服务 [(service, ratio, max_cpu), ...]"""
    try:
        sys.path.insert(0, str(TOOLS_PATH))
        # 用 tools_prom 实时查
        import importlib
        if "tools_prom" in sys.modules:
            importlib.reload(sys.modules["tools_prom"])
        from tools_prom import get_pod_metrics
    except Exception:
        return []

    # 只扫核心服务（避免太慢）
    core = ["ts-seat-service", "ts-order-service", "ts-gateway-service",
            "ts-travel-service", "ts-train-service", "ts-route-service",
            "ts-user-service", "ts-station-service"]
    anomalies = []
    for svc in core:
        try:
            r = get_pod_metrics(svc, "cpu", 3)
            d = json.loads(r)
            if d.get("found") and d.get("peak_to_mean_ratio", 0) > 3 and d.get("max", 0) > 0.3:
                anomalies.append((svc, d["peak_to_mean_ratio"], d["max"]))
        except Exception:
            continue
    # 按峰值排序
    anomalies.sort(key=lambda x: x[2], reverse=True)
    return anomalies


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
# 处理器: 系统状态查询（★ 区分 chaos 影响 vs 背景噪声）
# ============================================================
def handle_status(message: str) -> dict:
    abnormal = get_abnormal_pods()
    events = get_warning_events()

    # ★ 纯数据驱动：用"重启次数 + CPU 指标"区分主要故障 vs 背景噪声
    #   不依赖任何 chaos 标签（真实系统不知道是实验还是真故障）
    #   重启次数巨大（>50）= 长期慢性病（噪声）；重启次数小或 CPU 异常 = 较新的主要问题
    primary_faults = []   # 主要故障（较新 / 指标异常）
    background_noise = []  # 长期 CrashLoop 的边缘服务

    for pod in abnormal:
        if pod["restart_n"] >= 50:
            background_noise.append(pod)
        else:
            primary_faults.append(pod)

    # 额外：检查所有 Pod 的 CPU 指标，发现 CPU 异常的也算主要故障
    cpu_anomalies = _scan_cpu_anomalies()  # 返回 [(service, peak_ratio, max_cpu), ...]

    # 构造上下文（纯指标，无 chaos）
    ctx_lines = []
    if cpu_anomalies:
        ctx_lines.append(f"【⚠️ CPU 指标异常的服务 ({len(cpu_anomalies)} 个) - 重点关注】")
        for svc, ratio, mx in cpu_anomalies[:5]:
            ctx_lines.append(f"  - {svc}: CPU 峰值 {mx:.2f} 核, 峰均比 {ratio:.1f} (存在显著峰值，疑似资源故障)")

    if primary_faults:
        ctx_lines.append(f"\n【🎯 状态异常 Pod ({len(primary_faults)} 个) - 较新出现，需重点报告】")
        for p in primary_faults[:5]:
            ctx_lines.append(f"  - {p['name']}: phase={p['phase']}, ready={p['ready']}, restarts={p['restarts']}")

    if background_noise:
        ctx_lines.append(f"\n【🔇 背景噪声 ({len(background_noise)} 个) - 长期处于 CrashLoop 的边缘服务，重启数百次，属已知慢性问题，仅一句话带过】")
        noise_names = ", ".join(p["service"] for p in background_noise[:6])
        ctx_lines.append(f"  {noise_names} 等")

    if not abnormal and not cpu_anomalies:
        ctx_lines.append("【当前集群状态】 核心服务全部 Running 1/1 Ready，指标正常")

    ctx_str = "\n".join(ctx_lines)

    # 引导用哪个服务做诊断（优先 CPU 异常的，其次状态异常的）
    primary_target = ""
    if cpu_anomalies:
        primary_target = cpu_anomalies[0][0]
    elif primary_faults:
        primary_target = primary_faults[0]["service"]

    guide = f"如需详细根因分析，请输入：诊断 {primary_target}" if primary_target else ""

    system_prompt = f"""你是 K8s 集群运维专家助手。请基于以下实时数据回答用户问题。

【TrainTicket 集群实时状态】
{ctx_str}

【★ 回答优先级规则】
1. 优先、重点报告【CPU 指标异常的服务】和【状态异常 Pod】（这是用户最关心的当前故障）
2. 【背景噪声】只用一句话带过（如"另有若干边缘服务长期 CrashLoop，属已知慢性问题"），绝不能当主问题
3. 明确区分"新出现的故障" vs "一直存在的慢性问题"
4. 绝对不要把重启数百次的背景噪声 Pod 当作主要问题报告

【回答要求】
- 引用具体的 Pod 名和故障类型
- 结尾引导用户深入诊断：{guide if guide else '（如无明确故障可不引导）'}
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
        "cpu_anomaly_count": len(cpu_anomalies),
        "primary_target": primary_target,
    }


# ============================================================
# 处理器: 触发 Agent 真实诊断（★ chaos 强证据 + 故障类型回填）
# ============================================================
def get_current_pod_for_service(target_service: str) -> str | None:
    out = kubectl_run([
        "get", "pod", "-n", NAMESPACE,
        "-l", f"app={target_service}",
        "-o", "jsonpath={.items[0].metadata.name}"
    ], timeout=10)
    return out or None


def handle_diagnose(message: str, target_service: str) -> dict:
    # 1. 获取当前 Pod
    current_pod = get_current_pod_for_service(target_service)
    if not current_pod:
        return {
            "reply": f"❌ 找不到 {target_service} 的运行实例，可能服务名错误或 Pod 未启动。",
            "intent": "diagnose",
            "error": "pod_not_found",
        }

    # 2. 构造 slice_info（纯数据驱动，不注入任何 chaos 标签）
    now = int(time.time())
    slice_info = {
        "t_start": now - 300,
        "t_end": now,
        "pods": [current_pod],
        "max_score": 0.85,
        "exp_id": f"manual_chat_{now}",
    }

    # 4. 触发 Agent（live 模式）
    os.environ["AIOPS_LIVE_MODE"] = "1"
    try:
        # 清模块缓存确保用 live 工具
        for m in ["agent_core", "tools_prom_replay", "tools_prom"]:
            if m in sys.modules:
                del sys.modules[m]
        from agent_core import build_agent

        agent = build_agent()
        t0 = time.time()
        result = agent.invoke({"slice_info": slice_info})
        elapsed = round(time.time() - t0, 1)

        root_cause = result.get("root_cause", "未能给出明确根因")
        confidence = result.get("confidence", 0.0)
        evidence = result.get("evidence", [])
        pred_type = result.get("pred_fault_type", "") or ""
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "reply": f"❌ Agent 推理失败: {str(e)[:200]}",
            "intent": "diagnose",
            "error": str(e),
        }

    # 5. ★ 故障类型回填（纯靠 Agent 数据 + 文本推断，不用 chaos 标签）
    #    优先级: Agent JSON 的 fault_type > 从 root_cause 文本推断
    final_fault_type = _normalize_fault_type(pred_type)
    if not final_fault_type:
        final_fault_type = _infer_fault_from_text(root_cause)
    if not final_fault_type:
        final_fault_type = "UNKNOWN"

    sop = SOP_MAP.get(final_fault_type, "人工介入排查")

    # 6. 工具调用摘要
    tool_calls_summary = []
    for i, ev in enumerate(evidence[:5], 1):
        tool_calls_summary.append(f"  {i}. {ev['tool']}({json.dumps(ev['args'], ensure_ascii=False)})")
        tool_calls_summary.append(f"     → {ev['result'][:200]}")
    tool_str = "\n".join(tool_calls_summary) if tool_calls_summary else "  (无)"

    wrap_prompt = f"""你是运维 AI 助手。Agent 刚完成对 {target_service} 的根因诊断。
请把以下技术结果整理成专业、清晰的中文报告。

【Agent 推理结果】
- 最终故障类型: {final_fault_type}
- 置信度: {confidence}
- 推理耗时: {elapsed}s
- 推荐 SOP: {sop}
- 工具调用 ({len(evidence)} 次)及返回:
{tool_str}
- Agent 根因描述: {root_cause}

【★ 输出格式（严格遵守，故障类型必须是 {final_fault_type}）】
🎯 根因诊断报告: {target_service}
📊 故障类型: {final_fault_type}
✅ 置信度: {int(confidence*100)}%
⏱️ 分析耗时: {elapsed}s

【诊断依据】
- 引用上面工具返回的具体数值（如 CPU 峰均比、restart 跳变、网络 drop）
- 列出 2-3 条关键证据

【根因解释】
- 用 2-3 句话解释为什么是 {final_fault_type} 故障

【建议处置】
- 推荐执行 SOP: {sop}
- 给 1-2 条具体操作建议

不要套话，不要质疑故障类型（已确定为 {final_fault_type}），简洁专业。
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
            "pred_fault_type": final_fault_type,  # ★ 用回填后的，不再是空/UNKNOWN
            "confidence": round(confidence, 2),
            "elapsed": elapsed,
            "n_tools": len(evidence),
            "recommended_sop": sop,
        },
        "context_injected": True,
    }


def _normalize_fault_type(s: str) -> str:
    """规范化 Agent 给的 fault_type"""
    s = (s or "").upper().strip()
    if not s or s == "UNKNOWN":
        return ""
    if "CPU" in s or "THROTTLE" in s:
        return "CPU"
    if "NET" in s or "网络" in s:
        return "NETWORK"
    if "POD" in s or "KILL" in s or "RESTART" in s:
        return "POD_KILL"
    return ""


def _infer_fault_from_text(text: str) -> str:
    """从根因描述文本推断故障类型（兜底）"""
    t = (text or "").lower()
    if any(k in t for k in ["cpu", "节流", "throttle", "计算", "处理器", "峰值", "load"]):
        return "CPU"
    if any(k in t for k in ["network", "网络", "延迟", "丢包", "latency", "loss", "drop", "通信"]):
        return "NETWORK"
    if any(k in t for k in ["重启", "restart", "kill", "杀", "调度", "pod_kill", "pod-kill"]):
        return "POD_KILL"
    return ""


# ============================================================
# 处理器: 通用知识问答
# ============================================================
def handle_general(message: str, history: list) -> dict:
    system_prompt = """你是一名云原生 SRE 专家助手。
当前项目是【基于大模型的运维智能体】，使用 K8s + Prometheus + Neo4j + LLM Agent。
回答专业、简洁，避免套话。"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    reply = call_qwen(messages, max_tokens=600)
    return {"reply": reply, "intent": "general", "context_injected": False}


# ============================================================
# 主入口
# ============================================================
def smart_chat(message: str, history: list = None) -> dict:
    history = history or []
    classified = classify_intent(message)
    intent = classified["intent"]
    target = classified["target_service"]
    print(f"[smart_chat] intent={intent}, target={target}, msg={message[:60]}", flush=True)

    if intent == "diagnose" and target:
        return handle_diagnose(message, target)
    elif intent == "status":
        return handle_status(message)
    else:
        return handle_general(message, history)


if __name__ == "__main__":
    for q in ["系统现在有什么问题？", "诊断 ts-seat-service", "什么是孤立森林算法？"]:
        print(f"\n{'='*60}\nQ: {q}")
        r = smart_chat(q)
        print(f"Intent: {r.get('intent')}")
        print(f"Reply: {r.get('reply')[:200]}...")
