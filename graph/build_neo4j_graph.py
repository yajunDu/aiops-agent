"""
构建 Neo4j 拓扑图谱（从 K8s 实时拉取 + 手工补 CALLS 调用链）
==============================================================
节点：Service / Pod / Host
关系：HOSTS(Service→Pod) / RUNS_ON(Pod→Host) / CALLS(Service→Service)

CALLS 是系统2 拓扑因果推理的关键（区分根因 vs 被传染下游），
TrainTicket 核心订单链路手工补 10 条。运行前需 Neo4j 在线 + kubectl 可用。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiops.config import NEO4J_URI, NEO4J_USER, NEO4J_PWD, MANAGED_NAMESPACE as NS

# TrainTicket 核心订单链路（caller → callee）
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


def _kubectl(args):
    r = subprocess.run(args, capture_output=True, text=True, timeout=15)
    return json.loads(r.stdout) if r.stdout.strip() else {"items": []}


def main():
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PWD))

    pods = _kubectl(["kubectl", "get", "pods", "-n", NS, "-o", "json"])["items"]
    svcs = _kubectl(["kubectl", "get", "svc", "-n", NS, "-o", "json"])["items"]
    nodes = _kubectl(["kubectl", "get", "nodes", "-o", "json"])["items"]
    print(f"📊 K8s: {len(pods)} pods / {len(svcs)} services / {len(nodes)} hosts")

    with driver.session() as s:
        s.run("MATCH (n) DETACH DELETE n")

        for n in nodes:
            s.run("CREATE (h:Host {name:$name, cpu:$cpu, memory:$mem})",
                  name=n["metadata"]["name"],
                  cpu=str(n["status"]["capacity"].get("cpu", "?")),
                  mem=str(n["status"]["capacity"].get("memory", "?")))

        for svc in svcs:
            name = svc["metadata"]["name"]
            if name.startswith("ts-"):
                s.run("CREATE (s:Service {name:$name, namespace:$ns})", name=name, ns=NS)

        for pod in pods:
            pname = pod["metadata"]["name"]
            app = pod["metadata"].get("labels", {}).get("app", "")
            host = pod["spec"].get("nodeName", "")
            s.run("CREATE (p:Pod {name:$name, namespace:$ns, app:$app, status:$st})",
                  name=pname, ns=NS, app=app, st=pod["status"].get("phase", "Unknown"))
            if host:
                s.run("MATCH (p:Pod {name:$p}),(h:Host {name:$h}) CREATE (p)-[:RUNS_ON]->(h)",
                      p=pname, h=host)
            if app:
                s.run("MATCH (s:Service {name:$s}),(p:Pod {name:$p}) CREATE (s)-[:HOSTS]->(p)",
                      s=app, p=pname)

        cc = 0
        for src, dst in CALLS:
            r = s.run("MATCH (a:Service {name:$s}),(b:Service {name:$d}) "
                      "CREATE (a)-[:CALLS]->(b) RETURN count(*) AS c", s=src, d=dst).single()
            cc += 1 if r and r["c"] else 0
        print(f"✅ 图谱构建完成：{len(CALLS)} 条调用链路（成功 {cc}）")

        for row in s.run("MATCH (n) RETURN labels(n)[0] AS l, count(*) AS c"):
            print(f"   {row['l']}: {row['c']}")


if __name__ == "__main__":
    main()
