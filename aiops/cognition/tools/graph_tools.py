"""
拓扑证据工具（支柱① 的核心）
================================
这些工具【不替 LLM 下结论】，只把图谱事实整理成结构化证据交给它：
谁调用谁、哪些服务异常、某个服务的下游依赖是否健康、以及"根因候选"。
最终的根因判断 + 传播链由 Agent 结合指标证据做出。

因果方向约定：(A)-[:CALLS]->(B) 表示 A 调用 B（A 上游，B 下游）。
下游 B 故障 → 上游 A 观测到超时/报错，异常沿调用链向上游传播。
=> 一个自身异常、但它依赖的下游都健康的服务，更可能是根因；
   一个仅因调用了异常下游才跟着异常的服务，是被传染的受害者。
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Iterable

from ...config import NEO4J_URI, NEO4J_USER, NEO4J_PWD

_driver = None


def _get_driver():
    global _driver
    if _driver is None:
        from neo4j import GraphDatabase  # 延迟导入，便于无图库时也能 import 本模块
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PWD))
    return _driver


def _run(cypher: str, **params) -> list[dict]:
    drv = _get_driver()
    with drv.session() as s:
        return [r.data() for r in s.run(cypher, **params)]


# ──────────────────────────────────────────────────────────────
# 纯函数：因果方向推理（无需图库，可单测，可写进论文方法章）
# ──────────────────────────────────────────────────────────────
def find_root_candidates(anomalous: Iterable[str],
                         calls_edges: list[tuple[str, str]]) -> list[dict]:
    """在 CALLS 图上区分根因候选与下游受害者。返回【证据】，非最终答案。"""
    anomalous = set(anomalous)
    out = []
    for s in sorted(anomalous):
        downstream = {b for (a, b) in calls_edges if a == s}
        sick_downstream = sorted(downstream & anomalous)
        is_root = len(sick_downstream) == 0
        out.append({
            "service": s,
            "is_root_candidate": is_root,
            "sick_downstream": sick_downstream,
            "reason": ("无异常下游依赖，故障可能源于自身"
                       if is_root else
                       f"调用了异常下游 {sick_downstream}，更可能是被传染的受害者"),
        })
    out.sort(key=lambda c: (not c["is_root_candidate"], c["service"]))
    return out


def build_propagation_path(root: str,
                           anomalous: Iterable[str],
                           calls_edges: list[tuple[str, str]]) -> dict:
    """从根因沿调用链向上游（被影响方向）走出一条最长异常传播链。"""
    anomalous = set(anomalous)
    callers = defaultdict(list)            # callee -> [caller...]
    for a, b in calls_edges:
        callers[b].append(a)

    # BFS 找从 root 出发、只经过异常节点的最长上游链
    best = [root]
    q = deque([[root]])
    while q:
        path = q.popleft()
        tail = path[-1]
        extended = False
        for up in callers.get(tail, []):
            if up in anomalous and up not in path:
                q.append(path + [up])
                extended = True
        if not extended and len(path) > len(best):
            best = path

    hops = list(reversed(best))            # 症状(上游) → ... → 根因(下游)，再翻成 根因→症状
    hops = best                            # 保持 根因在前
    edges = []
    for i in range(len(hops) - 1):
        # hops[i] 是下游，hops[i+1] 是上游调用方
        edges.append((hops[i + 1], hops[i]))
    return {"hops": hops, "edges": edges}


# ──────────────────────────────────────────────────────────────
# 工具：交给 LLM tool-calling 使用（返回 JSON 字符串）
# ──────────────────────────────────────────────────────────────
def _all_calls_edges() -> list[tuple[str, str]]:
    rows = _run("MATCH (a:Service)-[:CALLS]->(b:Service) RETURN a.name AS a, b.name AS b")
    return [(r["a"], r["b"]) for r in rows]


def _neighborhood(suspects: set[str], edges: list[tuple[str, str]], hops: int = 2) -> set[str]:
    adj = defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    seen = set(suspects)
    frontier = set(suspects)
    for _ in range(hops):
        nxt = set()
        for n in frontier:
            nxt |= adj.get(n, set())
        nxt -= seen
        seen |= nxt
        frontier = nxt
    return seen


def analyze_topology(anomalous_services: list[str], hops: int = 2) -> str:
    """【主力工具】给定 Agent 当前认为异常的服务集，返回：
    调用子图 + 根因候选（含理由）+ 初步传播链。是结构化证据，不是结论。
    """
    try:
        anomalous = [s for s in (anomalous_services or []) if s]
        all_edges = _all_calls_edges()
        scope = _neighborhood(set(anomalous), all_edges, hops=hops)
        sub_edges = [(a, b) for (a, b) in all_edges if a in scope and b in scope]
        candidates = find_root_candidates(anomalous, sub_edges)
        prop = {}
        roots = [c["service"] for c in candidates if c["is_root_candidate"]]
        if roots:
            prop = build_propagation_path(roots[0], anomalous, sub_edges)
        return json.dumps({
            "nodes": sorted(scope),
            "calls_edges": [list(e) for e in sub_edges],
            "root_candidates": candidates,
            "tentative_propagation": prop,
            "note": "candidates 与 propagation 仅为拓扑层面的提示，请结合指标证据最终判断",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"图谱查询失败: {e}",
                           "hint": "确认 Neo4j 可达且已用 build_neo4j_graph 构建拓扑"},
                          ensure_ascii=False)


def run_cypher(cypher: str) -> str:
    """只读 Cypher 自由查询（供 Agent 在标准工具不够用时深挖拓扑）。"""
    low = cypher.lower()
    if any(k in low for k in ("create", "delete", "merge", "set ", "remove", "drop")):
        return json.dumps({"error": "仅允许只读查询"}, ensure_ascii=False)
    try:
        rows = _run(cypher)
        return json.dumps({"rows": rows[:50]}, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
