"""
UI 后端（最小 FastAPI）
========================
把精简 UI 接到闭环和 agent 上，只有三个接口：
  GET  /api/health
  POST /api/run-loop   跑一轮闭环（回放/在线），返回事件时间线 + 结果（喂大盘）
  POST /api/chat       调用工具的运维问答 agent
并把 ui/ 作为静态站点挂在根路径。

运行（在仓库根目录）：
  pip install fastapi "uvicorn[standard]"
  python ui_backend/server.py        # 然后浏览器打开 http://localhost:8088
真集群定位/问答需要 vLLM + Neo4j 在线；回放大盘的检测部分无需 LLM。
"""
from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="AIOps Console")


class LoopReq(BaseModel):
    parquet: str | None = None
    live: bool = False


class ChatReq(BaseModel):
    message: str


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/run-loop")
def run_loop(req: LoopReq):
    from aiops.orchestrator import run_closed_loop
    events: list[dict] = []

    def on_event(stage, msg):
        events.append({"stage": stage, "msg": msg})

    slices = None
    if req.parquet:
        from aiops.perception.detector import detect_from_experiment_parquet
        slices = detect_from_experiment_parquet(req.parquet)

    results = run_closed_loop(slices=slices, dry_run=not req.live, on_event=on_event)
    out = []
    for r in results:
        d = asdict(r)
        d.pop("timeline", None)   # 时间线已单独放在 events
        out.append(d)
    return {"events": events, "results": out}


@app.post("/api/chat")
def chat(req: ChatReq):
    return {"reply": _ask_agent(req.message)}


def _ask_agent(message: str) -> str:
    """复用 agent 的工具与 LLM，做一个简单的工具调用问答。"""
    from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
    from aiops.cognition.agent import TOOLS, _make_llm
    from aiops.config import MAX_TOOL_LOOPS

    sys_prompt = ("你是云原生运维助手。可调用工具查询服务调用拓扑（analyze_topology）、"
                  "服务指标（get_service_metrics）、图谱（run_cypher）。"
                  "简洁、用中文回答用户关于服务健康、根因、拓扑的问题；证据不足就如实说明。")
    msgs = [SystemMessage(content=sys_prompt), HumanMessage(content=message)]
    llm = _make_llm(with_tools=True)
    try:
        for _ in range(MAX_TOOL_LOOPS):
            ai = llm.invoke(msgs)
            msgs.append(ai)
            calls = getattr(ai, "tool_calls", None)
            if not calls:
                return ai.content or "（无法得出结论）"
            for c in calls:
                fn = TOOLS.get(c["name"])
                try:
                    res = fn(**c.get("args", {})) if fn else "{}"
                except Exception as e:
                    res = str(e)
                msgs.append(ToolMessage(content=res, tool_call_id=c["id"]))
        return getattr(msgs[-1], "content", "") or "（达到最大轮次仍未得出结论）"
    except Exception as e:
        return f"调用模型失败：{e}（请确认 vLLM 与 Neo4j 在线）"


# 静态前端挂在根路径
app.mount("/", StaticFiles(directory="ui", html=True), name="ui")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8088)
