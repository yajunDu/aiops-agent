#!/usr/bin/env python3
"""
通用性测试脚本 - 5 个 Pod × 不同故障类型
测试 smart_chat 的诊断能力（纯数据驱动，无 chaos 提示）

每个测试:
  1. 注入故障
  2. 等待生效
  3. 调 /api/chat 诊断
  4. 简要输出: 服务 / 故障类型 / 置信度 / 工具数 / 耗时
  5. 清理
"""
import json
import subprocess
import time
import requests

API = "http://localhost:9001/api/chat"

# 5 个测试用例: (服务名, 故障类型, chaos yaml)
TEST_CASES = [
    {
        "service": "ts-seat-service",
        "fault": "CPU 压力",
        "expect": "CPU",
        "yaml": """
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata: {name: test-cpu-seat, namespace: chaos-mesh}
spec:
  mode: one
  selector: {namespaces: [train-ticket], labelSelectors: {app: ts-seat-service}}
  stressors: {cpu: {workers: 4, load: 90}}
  duration: "3m"
""",
        "kind": "stresschaos", "name": "test-cpu-seat", "wait": 40,
    },
    {
        "service": "ts-order-service",
        "fault": "CPU 压力",
        "expect": "CPU",
        "yaml": """
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata: {name: test-cpu-order, namespace: chaos-mesh}
spec:
  mode: one
  selector: {namespaces: [train-ticket], labelSelectors: {app: ts-order-service}}
  stressors: {cpu: {workers: 4, load: 95}}
  duration: "3m"
""",
        "kind": "stresschaos", "name": "test-cpu-order", "wait": 40,
    },
    {
        "service": "ts-travel-service",
        "fault": "网络延迟",
        "expect": "NETWORK",
        "yaml": """
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata: {name: test-net-travel, namespace: chaos-mesh}
spec:
  action: delay
  mode: one
  selector: {namespaces: [train-ticket], labelSelectors: {app: ts-travel-service}}
  delay: {latency: "500ms", jitter: "100ms"}
  duration: "3m"
""",
        "kind": "networkchaos", "name": "test-net-travel", "wait": 40,
    },
    {
        "service": "ts-train-service",
        "fault": "网络丢包",
        "expect": "NETWORK",
        "yaml": """
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata: {name: test-loss-train, namespace: chaos-mesh}
spec:
  action: loss
  mode: one
  selector: {namespaces: [train-ticket], labelSelectors: {app: ts-train-service}}
  loss: {loss: "50"}
  duration: "3m"
""",
        "kind": "networkchaos", "name": "test-loss-train", "wait": 40,
    },
    {
        "service": "ts-route-service",
        "fault": "Pod 杀死",
        "expect": "POD_KILL",
        "yaml": """
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata: {name: test-kill-route, namespace: chaos-mesh}
spec:
  action: pod-kill
  mode: one
  selector: {namespaces: [train-ticket], labelSelectors: {app: ts-route-service}}
  gracePeriod: 0
""",
        "kind": "podchaos", "name": "test-kill-route", "wait": 15,
    },
]


def kubectl_apply(yaml_str):
    p = subprocess.run(["kubectl", "apply", "-f", "-"],
                       input=yaml_str, capture_output=True, text=True, timeout=30)
    return p.returncode == 0


def kubectl_delete(kind, name):
    """删除 chaos，networkchaos 卡 finalizer 时强制清理"""
    try:
        # 先清 finalizer（防止 networkchaos 卡住）
        subprocess.run(["kubectl", "patch", kind, name, "-n", "chaos-mesh",
                        "-p", '{"metadata":{"finalizers":[]}}', "--type=merge"],
                       capture_output=True, text=True, timeout=10)
    except Exception:
        pass
    try:
        subprocess.run(["kubectl", "delete", kind, name, "-n", "chaos-mesh",
                        "--wait=false", "--force", "--grace-period=0"],
                       capture_output=True, text=True, timeout=10)
    except Exception:
        pass


def diagnose(service):
    try:
        r = requests.post(API, json={"message": f"诊断 {service}", "history": []},
                          timeout=60)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def main():
    print("=" * 70)
    print("  通用性测试: 5 个 Pod × 不同故障类型")
    print("=" * 70)

    # 先清理所有旧 chaos（含 finalizer 强制清理）
    for kind in ["podchaos", "stresschaos", "networkchaos"]:
        # 清每个资源的 finalizer
        try:
            names = subprocess.run(["kubectl", "get", kind, "-n", "chaos-mesh",
                                    "-o", "jsonpath={.items[*].metadata.name}"],
                                   capture_output=True, text=True, timeout=10).stdout.split()
            for nm in names:
                subprocess.run(["kubectl", "patch", kind, nm, "-n", "chaos-mesh",
                                "-p", '{"metadata":{"finalizers":[]}}', "--type=merge"],
                               capture_output=True, text=True, timeout=8)
        except Exception:
            pass
        try:
            subprocess.run(["kubectl", "delete", kind, "--all", "-n", "chaos-mesh",
                            "--wait=false", "--force", "--grace-period=0"],
                           capture_output=True, text=True, timeout=15)
        except Exception:
            pass
    print("已清理旧 chaos，等 5 秒...\n")
    time.sleep(5)

    results = []
    for i, tc in enumerate(TEST_CASES, 1):
        svc = tc["service"]
        print(f"\n[{i}/5] {svc} - {tc['fault']} (期望 {tc['expect']})")
        print("-" * 50)

        # 1. 注入
        if not kubectl_apply(tc["yaml"]):
            print(f"  ❌ 注入失败")
            results.append((svc, tc["fault"], tc["expect"], "注入失败", "-", "-", "-"))
            continue
        print(f"  ✅ 已注入，等 {tc['wait']} 秒...")
        time.sleep(tc["wait"])

        # 2. 诊断
        d = diagnose(svc)
        if "error" in d:
            print(f"  ❌ 诊断失败: {d['error'][:80]}")
            results.append((svc, tc["fault"], tc["expect"], "诊断失败", "-", "-", "-"))
        else:
            a = d.get("agent_result", {})
            ft = a.get("pred_fault_type", "?")
            conf = a.get("confidence", "?")
            ntools = a.get("n_tools", "?")
            elapsed = a.get("elapsed", "?")
            match = "✅" if ft == tc["expect"] else "🟡"
            print(f"  {match} 故障类型: {ft} | 置信度: {conf} | 工具: {ntools}次 | 耗时: {elapsed}s")
            results.append((svc, tc["fault"], tc["expect"], ft, conf, ntools, elapsed))

        # 3. 清理
        kubectl_delete(tc["kind"], tc["name"])
        print(f"  已清理")
        time.sleep(8)  # 等 Pod 恢复一点

    # 汇总
    print("\n" + "=" * 70)
    print("  测试汇总")
    print("=" * 70)
    print(f"{'服务':<22}{'故障':<10}{'期望':<10}{'识别':<10}{'置信':<8}{'工具':<6}{'耗时':<6}")
    print("-" * 70)
    correct = 0
    for svc, fault, expect, got, conf, ntools, elapsed in results:
        match = "✅" if got == expect else "🟡"
        if got == expect:
            correct += 1
        print(f"{svc:<22}{fault:<10}{expect:<10}{str(got):<10}{str(conf):<8}{str(ntools):<6}{str(elapsed):<6} {match}")
    print("-" * 70)
    print(f"识别准确: {correct}/{len(results)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
