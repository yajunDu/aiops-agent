import os
"""
重建 Neo4j 图谱：从 K8s 拉拓扑 → 写入 Neo4j
节点: Service / Pod / Host  
关系: HOSTS (Service-Pod) / RUNS_ON (Pod-Host) / CALLS (Service-Service)
"""
import json
import subprocess
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PWD = os.getenv("NEO4J_PWD", "aiops2026")
NS = "train-ticket"


def run_kubectl(args):
    r = subprocess.run(args, capture_output=True, text=True, timeout=15)
    return json.loads(r.stdout) if r.stdout.strip() else {"items": []}


def main():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PWD))

    # 1. 拉 Pod + Service
    pods = run_kubectl(["kubectl", "get", "pods", "-n", NS, "-o", "json"])["items"]
    svcs = run_kubectl(["kubectl", "get", "svc", "-n", NS, "-o", "json"])["items"]
    nodes = run_kubectl(["kubectl", "get", "nodes", "-o", "json"])["items"]

    print(f"📊 K8s 真实数据: {len(pods)} pods / {len(svcs)} services / {len(nodes)} hosts")

    with driver.session() as s:
        # 清空旧数据
        s.run("MATCH (n) DETACH DELETE n")
        print("🗑️  清空旧图谱")

        # 2. 建 Host 节点
        for n in nodes:
            host_name = n["metadata"]["name"]
            cpu = n["status"]["capacity"].get("cpu", "?")
            mem = n["status"]["capacity"].get("memory", "?")
            s.run("CREATE (h:Host {name: $name, cpu: $cpu, memory: $mem})",
                  name=host_name, cpu=str(cpu), mem=str(mem))
        print(f"✅ 写入 {len(nodes)} 个 Host")

        # 3. 建 Service 节点
        svc_count = 0
        for svc in svcs:
            name = svc["metadata"]["name"]
            if not name.startswith("ts-"):
                continue
            s.run("CREATE (s:Service {name: $name, namespace: $ns})",
                  name=name, ns=NS)
            svc_count += 1
        print(f"✅ 写入 {svc_count} 个 Service")

        # 4. 建 Pod 节点 + HOSTS 关系 + RUNS_ON 关系
        pod_count = 0
        runs_on_count = 0
        hosts_count = 0
        for pod in pods:
            pod_name = pod["metadata"]["name"]
            app_label = pod["metadata"].get("labels", {}).get("app", "")
            phase = pod["status"].get("phase", "Unknown")
            host = pod["spec"].get("nodeName", "")
            
            s.run("""
                CREATE (p:Pod {name: $name, namespace: $ns, app: $app, status: $status})
                """, name=pod_name, ns=NS, app=app_label, status=phase)
            pod_count += 1

            # RUNS_ON (Pod -> Host)
            if host:
                s.run("""
                    MATCH (p:Pod {name: $pname}), (h:Host {name: $hname})
                    CREATE (p)-[:RUNS_ON]->(h)
                """, pname=pod_name, hname=host)
                runs_on_count += 1

            # HOSTS (Service -> Pod)
            if app_label:
                result = s.run("""
                    MATCH (svc:Service {name: $sname}), (p:Pod {name: $pname})
                    CREATE (svc)-[:HOSTS]->(p)
                    RETURN count(*) AS c
                """, sname=app_label, pname=pod_name).single()
                if result and result["c"] > 0:
                    hosts_count += 1
        print(f"✅ 写入 {pod_count} 个 Pod")
        print(f"✅ 写入 {runs_on_count} 条 RUNS_ON")
        print(f"✅ 写入 {hosts_count} 条 HOSTS")

        # 5. 手工补 10 条 CALLS 关系（TrainTicket 核心订单链路）
        calls = [
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
        call_count = 0
        for src, dst in calls:
            result = s.run("""
                MATCH (a:Service {name: $s}), (b:Service {name: $d})
                CREATE (a)-[:CALLS]->(b)
                RETURN count(*) AS c
            """, s=src, d=dst).single()
            if result and result["c"] > 0:
                call_count += 1
        print(f"✅ 写入 {call_count} 条 CALLS")

        # 6. 最终统计
        r = s.run("MATCH (n) RETURN labels(n)[0] AS l, count(*) AS c")
        print("\n📊 最终图谱:")
        for row in r:
            print(f"   {row['l']}: {row['c']}")
        r = s.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c")
        for row in r:
            print(f"   :{row['t']}: {row['c']}")

    driver.close()


if __name__ == "__main__":
    main()
