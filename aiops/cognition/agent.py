"""
认知中枢：拓扑感知 + 证据驱动的根因定位 Agent
================================================
LangGraph 流程：perceive → investigate(plan) → act → (loop) → synthesize

与旧 agent_core.py 的三处关键改造：
  ① 输出从"故障类型三分类"升级为"根因服务定位 + 可解释传播链"（支柱①）
  ② 提示词去掉硬编码阈值，类型判断来自 LLM 阅读指标证据（支柱③）
  ③ 删除旧版 finalize() 里的中文关键词反推 fault_type 兜底——
     解析失败就显式重问一次，仍失败则诚实返回 UNKNOWN/低置信度，不再"猜"。
"""
from __future__ import annotations

import json
import time
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import (AIMessage, BaseMessage, HumanMessage,
                                     SystemMessage, ToolMessage)
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from ..config import (LLM_URL, MODEL_NAME, LLM_TEMPERATURE, LLM_MAX_TOKENS,
                      MAX_TOOL_LOOPS)
from ..core.contracts import (AnomalySlice, Diagnosis, Evidence, FaultType,
                              PropagationPath)
from .prompts import SYSTEM_PROMPT, FORCE_FINAL
from .tools.graph_tools import analyze_topology, run_cypher
from .tools.metric_tools import get_service_metrics

# ── 工具注册 ──────────────────────────────────────────────────
TOOLS = {
    "analyze_topology": analyze_topology,
    "get_service_metrics": get_service_metrics,
    "run_cypher": run_cypher,
}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "analyze_topology",
        "description": "查嫌疑服务间 CALLS 调用关系，返回调用子图 + 根因候选（含因果方向理由）。这是结构化证据，不是最终结论。",
        "parameters": {"type": "object", "properties": {
            "anomalous_services": {"type": "array", "items": {"type": "string"},
                                   "description": "当前认为异常的服务名列表"},
            "hops": {"type": "integer", "default": 2},
        }, "required": ["anomalous_services"]}}},
    {"type": "function", "function": {
        "name": "get_service_metrics",
        "description": "拉取某服务某指标的数值摘要（min/max/mean/latest/峰均比/restart台阶）。返回数值由你自行判读，不要套固定阈值。",
        "parameters": {"type": "object", "properties": {
            "service": {"type": "string"},
            "metric": {"type": "string",
                       "enum": ["cpu", "memory", "network", "net_drop", "restart", "throttle"]},
            "minutes": {"type": "integer", "default": 5},
        }, "required": ["service", "metric"]}}},
    {"type": "function", "function": {
        "name": "run_cypher",
        "description": "只读 Cypher 自由查询拓扑（标准工具不够用时深挖）。",
        "parameters": {"type": "object", "properties": {"cypher": {"type": "string"}},
                       "required": ["cypher"]}}},
]


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    slice: dict
    tool_loop: int
    evidence: list[dict]
    similar_cases: list[dict]


def _make_llm(with_tools: bool = True):
    llm = ChatOpenAI(base_url=LLM_URL, api_key="dummy", model=MODEL_NAME,
                     temperature=LLM_TEMPERATURE, max_tokens=LLM_MAX_TOKENS)
    return llm.bind_tools(TOOL_SCHEMAS) if with_tools else llm


# ── 节点 ──────────────────────────────────────────────────────
def perceive(state: AgentState):
    s = state["slice"]
    cases = state.get("similar_cases", [])
    case_hint = ""
    if cases:
        top = cases[0]
        case_hint = (f"\n【相似历史案例（相似度 {top.get('similarity')}）】"
                     f"曾定位根因为 {top.get('diagnosis', {}).get('root_cause_service')}，"
                     f"类型 {top.get('diagnosis', {}).get('fault_type')}。请用当前证据复核，勿照搬。")
    human = f"""异常切片：
- 时间窗口: {s.get('t_start')} ~ {s.get('t_end')}（Unix 时间戳）
- 嫌疑服务（候选，非答案）: {', '.join(s.get('suspect_services', [])) or '（无，请先查拓扑）'}
- 异常分数(max): {s.get('max_score', 'N/A')}{case_hint}

请开始定位根因。第一步建议先 analyze_topology 看调用关系。"""
    return {"messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=human)],
            "tool_loop": 0, "evidence": []}


def investigate(state: AgentState):
    return {"messages": [_make_llm(with_tools=True).invoke(state["messages"])]}


def act(state: AgentState):
    last = state["messages"][-1]
    tms, ev = [], list(state.get("evidence", []))
    for c in getattr(last, "tool_calls", []) or []:
        name, args = c["name"], c.get("args", {})
        fn = TOOLS.get(name)
        try:
            result = fn(**args) if fn else json.dumps({"error": f"unknown tool {name}"})
        except Exception as e:
            result = json.dumps({"error": str(e)}, ensure_ascii=False)
        tms.append(ToolMessage(content=result, tool_call_id=c["id"]))
        ev.append({"tool": name, "args": args, "result": result[:500]})
    return {"messages": tms, "tool_loop": state["tool_loop"] + 1, "evidence": ev}


def route(state: AgentState) -> Literal["act", "synthesize"]:
    last = state["messages"][-1]
    if (isinstance(last, AIMessage) and getattr(last, "tool_calls", None)
            and state["tool_loop"] < MAX_TOOL_LOOPS):
        return "act"
    return "synthesize"


def _extract_json(text: str) -> dict | None:
    l, r = text.find("{"), text.rfind("}")
    if l < 0 or r <= l:
        return None
    try:
        return json.loads(text[l:r + 1])
    except json.JSONDecodeError:
        return None


def synthesize(state: AgentState):
    """强制产出结构化定位结果。解析失败显式重问一次；仍失败则诚实 UNKNOWN（无关键词兜底）。"""
    last = state["messages"][-1]
    text = last.content if isinstance(last, AIMessage) and not getattr(last, "tool_calls", None) else ""
    parsed = _extract_json(text) if text else None
    if parsed is None:
        forced = _make_llm(with_tools=False).invoke(state["messages"] + [HumanMessage(content=FORCE_FINAL)])
        text = forced.content if isinstance(forced.content, str) else str(forced.content)
        parsed = _extract_json(text)
    return {"_final": parsed or {}, "_final_text": text}


# ── 编译 + 对外接口 ────────────────────────────────────────────
def build_agent():
    g = StateGraph(AgentState)
    g.add_node("perceive", perceive)
    g.add_node("investigate", investigate)
    g.add_node("act", act)
    g.add_node("synthesize", synthesize)
    g.set_entry_point("perceive")
    g.add_edge("perceive", "investigate")
    g.add_conditional_edges("investigate", route, {"act": "act", "synthesize": "synthesize"})
    g.add_edge("act", "investigate")
    g.add_edge("synthesize", END)
    return g.compile()


def diagnose(slice_obj: AnomalySlice, similar_cases: list[dict] | None = None) -> Diagnosis:
    """主入口：异常切片 → 根因定位诊断。"""
    slice_obj.ensure_services()
    agent = build_agent()
    t0 = time.time()
    final = agent.invoke({"slice": slice_obj.__dict__,
                          "similar_cases": similar_cases or []})
    latency = time.time() - t0

    p = final.get("_final", {}) or {}
    evidence = [Evidence(tool=e["tool"], args=e["args"], observation=e["result"])
                for e in final.get("evidence", [])]

    prop = None
    hops = p.get("propagation_path") or []
    if isinstance(hops, list) and hops:
        prop = PropagationPath(hops=hops, rationale=p.get("rationale", ""))

    return Diagnosis(
        slice_id=slice_obj.slice_id,
        root_cause_service=p.get("root_cause_service", "UNKNOWN"),
        fault_type=FaultType.parse(p.get("fault_type", "UNKNOWN")),
        confidence=float(p.get("confidence", 0.0) or 0.0),
        propagation_path=prop,
        affected_services=p.get("affected_services", []) or [],
        evidence_chain=evidence,
        summary=p.get("summary", "") or (final.get("_final_text", "")[:120]),
        n_tool_calls=final.get("tool_loop", 0),
        latency_sec=round(latency, 2),
        matched_case_id=(similar_cases[0].get("case_id") if similar_cases else None),
        model_name=MODEL_NAME,
    )
