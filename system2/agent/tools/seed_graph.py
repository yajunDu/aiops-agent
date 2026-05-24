import os
"""
12.3-A 拓扑图建图脚本（一次性）
================================
从 kubectl 拉真实 K8s 拓扑，灌入 Neo4j：
  - Host:     节点
  - Pod:      容器实例
  - Service:  K8s Service
  - 关系:
      (Pod)-[:RUNS_ON]->(Host)
      (Service)-[:HOSTS]->(Pod)         # Service 选中 Pod
      (Service)-[:CALLS]->(Service)     # 调用关系（从已知微服务链路）
"""
import json
import subprocess
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PWD = os.getenv("NEO4J_PWD", "aiops2026")
NS = "train-ticket"

# TrainTicket 主要调用链（论文 4.1.1 简化版）
SERVICE_CALLS = [
    ("ts-gateway-service", "ts-preserve-service"),
    ("ts-gateway-service", "ts-basic-service"),
    ("ts-gateway-service", "ts-ui-dashboard"),
    ("ts-preserve-service", "ts-seat-service"),
    ("ts-preserve-service", "ts-order-service"),
    ("ts-preserve-service", "ts-travel-service"),
    ("ts-seat-service", "ts-travel-service"),
    ("ts-admin-order-service", "ts-order-service"),
    ("ts-admin-user-service", "ts-user-service"),
    ("ts-admin-basic-info-service", "ts-basic-service"),
]


def kc(args):
    """kubectl 命令包装"""
    p = subprocess.run(["kubectl"] + args, capture_output=True, text=True, timeout=30)
    return p.stdout


def get_topology():
    """从 K8s 拉真实拓扑"""
    pods_json = json.loads(kc(["get", "pods", "-n", NS, "-o", "json"]))
    svcs_json = json.loads(kc(["get", "svc", "-n", NS, "-o", "json"]))

    pods = []
    for p in pods_json["items"]:
        pods.append({
            "name": p["metadata"]["name"],
            "namespace": p["metadata"]["namespace"],
            "host": p["spec"].get("nodeName", "unknown"),
            "app": p["metadata"].get("labels", {}).get("app", ""),
            "status": p["status"].get("phase", "Unknown"),
            "ip": p["status"].get("podIP", ""),
        })

    services = []
    for s in svcs_json["items"]:
        services.append({
            "name": s["metadata"]["name"],
            "namespace": s["metadata"]["namespace"],
            "selector": s["spec"].get("selector", {}),
            "cluster_ip": s["spec"].get("clusterIP", ""),
        })

    hosts = sorted({p["host"] for p in pods if p["host"] != "unknown"})
    return pods, services, hosts


def seed(driver, pods, services, hosts):
    with driver.session() as s:
        # 清空旧数据
        s.run("MATCH (n) DETACH DELETE n")

        # Host
        for h in hosts:
            s.run("MERGE (:Host {name: $n})", n=h)

        # Pod
        for p in pods:
            s.run("""
                MERGE (po:Pod {name: $name})
                SET po.namespace=$ns, po.app=$app, po.status=$st, po.ip=$ip
            """, name=p["name"], ns=p["namespace"], app=p["app"],
                st=p["status"], ip=p["ip"])
            # Pod -> Host
            if p["host"] != "unknown":
                s.run("""
                    MATCH (po:Pod {name: $pn}), (h:Host {name: $hn})
                    MERGE (po)-[:RUNS_ON]->(h)
                """, pn=p["name"], hn=p["host"])

        # Service
        for svc in services:
            s.run("""
                MERGE (sv:Service {name: $name})
                SET sv.namespace=$ns, sv.cluster_ip=$ip
            """, name=svc["name"], ns=svc["namespace"], ip=svc["cluster_ip"])
            # Service -> Pod（按 selector 的 app 标签）
            app_sel = svc["selector"].get("app")
            if app_sel:
                s.run("""
                    MATCH (sv:Service {name: $svn}), (po:Pod {app: $app})
                    MERGE (sv)-[:HOSTS]->(po)
                """, svn=svc["name"], app=app_sel)

        # Service -> Service 调用关系
        for caller, callee in SERVICE_CALLS:
            s.run("""
                MATCH (a:Service {name: $c}), (b:Service {name: $e})
                MERGE (a)-[:CALLS]->(b)
            """, c=caller, e=callee)


def stats(driver):
    with driver.session() as s:
        r = s.run("""
            MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt
            ORDER BY cnt DESC
        """)
        print("\n📊 节点统计:")
        for rec in r:
            print(f"  {rec['label']:12s} : {rec['cnt']}")
        r = s.run("""
            MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt
            ORDER BY cnt DESC
        """)
        print("\n📊 关系统计:")
        for rec in r:
            print(f"  {rec['rel']:12s} : {rec['cnt']}")


if __name__ == "__main__":
    print("📥 从 K8s 拉拓扑...")
    pods, services, hosts = get_topology()
    print(f"  Pod: {len(pods)}  Service: {len(services)}  Host: {len(hosts)}")

    print(f"\n🔗 连接 Neo4j {NEO4J_URI} ...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PWD))
    
    print("🌱 灌图...")
    seed(driver, pods, services, hosts)
    stats(driver)
    driver.close()
    print("\n✅ 图谱构建完成")
