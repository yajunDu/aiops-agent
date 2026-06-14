"""Chaos Mesh 故障注入器"""
import subprocess
import random
import time
import yaml
import json


class ChaosInjector:
    def __init__(self):
        self.targets = [
            "ts-gateway-service",
            "ts-seat-service",
            "ts-preserve-service",
            "ts-basic-service",
            "ts-ui-dashboard",
            "ts-admin-order-service",
            "ts-admin-user-service",
            "ts-admin-basic-info-service",
        ]

    def _apply(self, manifest):
        """kubectl apply 一个 YAML"""
        p = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=yaml.dump(manifest),
            capture_output=True, text=True, timeout=30,
        )
        return p.returncode == 0, (p.stdout + p.stderr).strip()

    def _delete(self, kind, name, ns="chaos-mesh"):
        """删除 chaos object"""
        subprocess.run(
            ["kubectl", "delete", kind, name, "-n", ns, "--ignore-not-found"],
            capture_output=True, timeout=30,
        )

    def get_pod(self, target):
        """获取目标服务当前 Pod 名 + Host"""
        p = subprocess.run(
            ["kubectl", "get", "pod", "-n", "train-ticket",
             "-l", f"app={target}",
             "-o", "jsonpath={.items[0].metadata.name}|{.items[0].spec.nodeName}"],
            capture_output=True, text=True, timeout=30,
        )
        if "|" in p.stdout:
            pod, host = p.stdout.split("|", 1)
            return pod, host
        return None, None

    def inject_cpu(self, target, exp_id):
        """CPU 注入：随机 70-95% load，60s 持续"""
        load = random.randint(70, 95)
        m = {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "StressChaos",
            "metadata": {"name": exp_id, "namespace": "chaos-mesh"},
            "spec": {
                "mode": "one",
                "selector": {
                    "namespaces": ["train-ticket"],
                    "labelSelectors": {"app": target},
                },
                "stressors": {"cpu": {"workers": 2, "load": load}},
                "duration": "60s",
            },
        }
        ok, msg = self._apply(m)
        return ok, {"load_pct": load, "duration_sec": 60, "workers": 2}, msg

    def inject_network(self, target, exp_id):
        """网络注入：随机 100-500ms 延迟 + 1-10% 丢包"""
        latency = random.randint(100, 500)
        jitter = random.randint(20, 100)
        loss = random.randint(1, 10)
        m = {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "NetworkChaos",
            "metadata": {"name": exp_id, "namespace": "chaos-mesh"},
            "spec": {
                "action": "delay",
                "mode": "one",
                "selector": {
                    "namespaces": ["train-ticket"],
                    "labelSelectors": {"app": target},
                },
                "delay": {
                    "latency": f"{latency}ms",
                    "correlation": "100",
                    "jitter": f"{jitter}ms",
                },
                "loss": {"loss": str(loss)},
                "duration": "60s",
            },
        }
        ok, msg = self._apply(m)
        return ok, {"latency_ms": latency, "jitter_ms": jitter, "loss_pct": loss, "duration_sec": 60}, msg

    def inject_pod_kill(self, target, exp_id):
        """Pod Kill：直接杀死 Pod"""
        m = {
            "apiVersion": "chaos-mesh.org/v1alpha1",
            "kind": "PodChaos",
            "metadata": {"name": exp_id, "namespace": "chaos-mesh"},
            "spec": {
                "action": "pod-kill",
                "mode": "one",
                "selector": {
                    "namespaces": ["train-ticket"],
                    "labelSelectors": {"app": target},
                },
                "gracePeriod": 0,
            },
        }
        ok, msg = self._apply(m)
        return ok, {"grace_period_sec": 0}, msg

    def cleanup(self, fault_type, exp_id):
        kind_map = {
            "cpu": "stresschaos",
            "network": "networkchaos",
            "pod_kill": "podchaos",
        }
        self._delete(kind_map[fault_type], exp_id)


if __name__ == "__main__":
    c = ChaosInjector()
    pod, host = c.get_pod("ts-gateway-service")
    print(f"Gateway: pod={pod}, host={host}")
    print(f"Targets: {c.targets}")
