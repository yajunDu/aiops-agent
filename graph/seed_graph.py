"""
离线静态拓扑种子（无需 K8s 集群）
==================================
只建 Service 节点 + CALLS 调用链，让 Neo4j 具备 system2 拓扑因果推理所需的拓扑。
回放重评测（evaluate.py --with-agent）时，集群可以不开，只需 Neo4j + vLLM。

用法（仓库根目录）：python graph/seed_graph.py
若集群在线、想要完整图谱（含 Pod/Host），改用 build_neo4j_graph.py。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiops.config import NEO4J_URI, NEO4J_USER, NEO4J_PWD, MANAGED_NAMESPACE, MONITORED_SERVICES

# TrainTicket 核心订单链路（caller → callee），与 build_neo4j_graph 一致
CALLS = [
    ("ts-gateway-service", "ts-ui-dashboard"),
    ("ts-gateway-service", "ts-basic-service"),
    ("ts-gateway-service", "ts-preserve-service"),
    ("ts-preserve-service", "ts-order-service"),
    ("ts-preserve-service", "ts-seat-service"),
    ("ts-preserve-service", "ts-travel-service"),
    ("ts-order-service", "ts-station-service"),
    ("ts-order-service", "ts-train-service"),
    ("ts-admin-order-service", "ts-order-service"),
    ("ts-admin-user-service", "ts-user-service"),
]


def main():
    from neo4j import GraphDatabase
    services = set(MONITORED_SERVICES) | {s for e in CALLS for s in e}
    drv = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PWD))
    with drv.session() as s:
        for svc in sorted(services):
            s.run("MERGE (n:Service {name:$n}) SET n.namespace=$ns", n=svc, ns=MANAGED_NAMESPACE)
        edges = 0
        for a, b in CALLS:
            s.run("MATCH (a:Service {name:$a}),(b:Service {name:$b}) MERGE (a)-[:CALLS]->(b)",
                  a=a, b=b)
            edges += 1
        n = s.run("MATCH (n:Service) RETURN count(n) AS c").single()["c"]
    print(f"✅ 离线图谱种子完成：{n} 个 Service 节点，{edges} 条 CALLS 调用链")
    print("   （回放重评测够用；若需完整 Pod/Host 拓扑请在集群在线时跑 build_neo4j_graph.py）")


if __name__ == "__main__":
    main()
