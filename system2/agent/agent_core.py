"""
12.2 + 12.3 + 12.4 集成版
==========================
Agent 真正调用 Neo4j + Prometheus
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Annotated, Literal, TypedDict

# 让 agent 能 import tools/
sys.path.insert(0, str(Path(__file__).parent / "tools"))
from tools_neo4j import query_graph_topology  # noqa
from tools_prom_replay import get_pod_metrics, set_active_experiment  # noqa

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages


VLLM_URL = "http://localhost:8000/v1"
MODEL_NAME = "qwen2.5-7b"
MAX_TOOL_LOOPS = 5


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    slice_info: dict
    tool_loop: int
    root_cause: str | None
    confidence: float | None
    evidence: list[dict]


def make_llm():
    return ChatOpenAI(
        base_url=VLLM_URL, api_key="dummy", model=MODEL_NAME,
        temperature=0.1, max_tokens=512,
    )


TOOLS = {
    "query_graph_topology": query_graph_topology,
    "get_pod_metrics": get_pod_metrics,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_graph_topology",
            "description": "在 Neo4j 上执行 Cypher 查询。节点类型: Pod, Service, Host。关系: RUNS_ON (Pod->Host), HOSTS (Service->Pod), CALLS (Service->Service)。只允许只读查询。",
            "parameters": {
                "type": "object",
                "properties": {"cypher": {"type": "string"}},
                "required": ["cypher"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pod_metrics",
            "description": "从 Prometheus 拉 Pod 指标摘要（min/max/mean/latest）",
            "parameters": {
                "type": "object",
                "properties": {
                    "pod": {"type": "string", "description": "Pod 名前缀（如 ts-gateway-service）"},
                    "metric": {"type": "string",
                               "enum": ["cpu", "memory", "network", "net_drop", "restart", "throttle"]},
                    "minutes": {"type": "integer", "default": 5}
                },
                "required": ["pod", "metric"],
            },
        },
    },
]

SYSTEM_PROMPT = """你是云原生 SRE 根因诊断专家。系统1 检测到异常切片，你（系统2）必须通过工具收集证据后给出根因。

【强制规则】
1. **第一步：必须调用 get_pod_metrics 工具**，不要凭空回答。
2. 至少查 3 个指标：cpu / network / restart。
3. 不允许在没调工具的情况下直接输出 JSON。

【工具】
- query_graph_topology(cypher): 查 Neo4j 拓扑（可选）
- get_pod_metrics(pod, metric, minutes): 查指标 (cpu/memory/network/net_drop/restart/throttle)

【诊断要点】
- cpu / throttle 的 peak_to_mean_ratio > 3 → CPU 故障
- network 的 peak_to_mean_ratio > 3 或 net_drop > 0 → NETWORK 故障  
- restart 的 max > min（重启次数跳变）→ POD_KILL 故障

【图谱】节点: Pod, Service, Host
关系: (Pod)-[:RUNS_ON]->(Host), (Service)-[:HOSTS]->(Pod), (Service)-[:CALLS]->(Service)

【最终输出】收集足够证据后，输出严格 JSON：
{"root_cause": "简洁中文", "confidence": 0.0-1.0, "fault_type": "CPU或NETWORK或POD_KILL", "affected_service": "ts-xxx"}
"""


def perceive(state):
    info = state["slice_info"]
    msg = f"""异常切片信息：
- 时间窗口: {info.get('t_start')} ~ {info.get('t_end')} (Unix 时间戳)
- 涉及 Pod: {', '.join(info.get('pods', []))}
- 异常分数 (max): {info.get('max_score', 'N/A')}

开始诊断。"""
    return {
        "messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=msg)],
        "tool_loop": 0, "evidence": [],
    }


def plan(state):
    llm = make_llm().bind_tools(TOOL_SCHEMAS)
    return {"messages": [llm.invoke(state["messages"])]}


def act(state):
    last = state["messages"][-1]
    tms, ev = [], list(state.get("evidence", []))
    for c in last.tool_calls:
        name, args = c["name"], c["args"]
        if name in TOOLS:
            try:
                result = TOOLS[name](**args)
            except Exception as e:
                result = json.dumps({"error": str(e)})
        else:
            result = json.dumps({"error": f"unknown: {name}"})
        tms.append(ToolMessage(content=result, tool_call_id=c["id"]))
        ev.append({"tool": name, "args": args, "result": result[:400]})
    return {"messages": tms, "tool_loop": state["tool_loop"] + 1, "evidence": ev}


def finalize(state):
    """从历史消息中找 JSON。如果最后一条是 ToolMessage，强制 LLM 再生成一次最终答案"""
    last = state["messages"][-1]

    # 如果最后一条不是 AIMessage（即工具循环耗尽但 LLM 没给最终答案），强制再问一次
    if not isinstance(last, AIMessage) or getattr(last, "tool_calls", None):
        force_msg = HumanMessage(content="证据收集完毕。请基于以上证据给出最终 JSON 答案（严格格式），不要再调工具。")
        llm = make_llm()  # 不绑工具，强制纯文本输出
        final_msg = llm.invoke(state["messages"] + [force_msg])
        text = final_msg.content if isinstance(final_msg.content, str) else str(final_msg.content)
    else:
        text = last.content if isinstance(last.content, str) else str(last.content)

    # 解析 JSON
    try:
        l, r = text.find("{"), text.rfind("}")
        if l >= 0 and r > l:
            p = json.loads(text[l:r+1])
            return {
                "root_cause": p.get("root_cause", "未明确"),
                "confidence": float(p.get("confidence", 0.5)),
                "pred_fault_type": str(p.get("fault_type", "")).upper(),
            }
    except Exception:
        pass
    return {"root_cause": text[:200], "confidence": 0.3}


def route(state) -> Literal["act", "finalize"]:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None) and state["tool_loop"] < MAX_TOOL_LOOPS:
        return "act"
    return "finalize"


def build_agent():
    g = StateGraph(AgentState)
    g.add_node("perceive", perceive)
    g.add_node("plan", plan)
    g.add_node("act", act)
    g.add_node("finalize", finalize)
    g.set_entry_point("perceive")
    g.add_edge("perceive", "plan")
    g.add_conditional_edges("plan", route, {"act": "act", "finalize": "finalize"})
    g.add_edge("act", "plan")
    g.add_edge("finalize", END)
    return g.compile()


if __name__ == "__main__":
    # 用真实历史实验数据作为测试切片（CPU 注入）
    test_slice = {
        "t_start": 1779186683,
        "t_end": 1779187051,
        "pods": ["ts-gateway-service-645fbbbdc5-d5q2s"],
        "max_score": 0.85,
        "n_windows": 6,
    }
    print("🚀 启动 Agent（真工具集成版）...\n")
    agent = build_agent()
    result = agent.invoke({"slice_info": test_slice})

    print(f"\n{'='*70}")
    print(f"📊 推理结果")
    print(f"{'='*70}")
    print(f"  根因:   {result.get('root_cause')}")
    print(f"  置信度: {result.get('confidence')}")
    print(f"  工具轮次: {result.get('tool_loop')}")
    print(f"\n  证据链:")
    for i, ev in enumerate(result.get("evidence", []), 1):
        print(f"  ━━━ Step {i}: {ev['tool']}")
        args_str = json.dumps(ev['args'], ensure_ascii=False)
        print(f"      args: {args_str[:120]}")
        print(f"      → {ev['result'][:180]}")
