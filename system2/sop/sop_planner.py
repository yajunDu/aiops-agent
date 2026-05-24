"""
13.2 + 13.3 SOP Planner + 安全护栏
====================================
输入：Agent 的诊断结果（root_cause / fault_type / affected_service）
输出：可执行的 SOP plan（含命令 + 风险评级 + 护栏通过状态）

护栏规则（论文 3.4.2）：
  G1. 命名空间白名单（只允许 train-ticket）
  G2. Pod/Deployment 在图谱中真实存在
  G3. 高风险操作（cordon/network_policy）需 confidence >= 0.85
  G4. 同一 service 5 分钟内不可重复执行同一 SOP
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "agent" / "tools"))
from tools_neo4j import query_graph_topology

TEMPLATES_DIR = Path(__file__).parent / "templates"
MANAGED_NS = {"train-ticket"}
HIGH_RISK_CONFIDENCE_THRESHOLD = 0.85

# 同 service 同 SOP 的去重缓存（5 分钟窗口）
_RECENT_ACTIONS: dict[str, float] = {}
DEDUP_WINDOW_SEC = 300


def load_templates() -> list[dict]:
    """加载所有 SOP 模板"""
    out = []
    for f in sorted(TEMPLATES_DIR.glob("*.yaml")):
        with open(f) as fp:
            t = yaml.safe_load(fp)
        out.append(t)
    return out


def pick_template(fault_type: str, confidence: float, available: list[dict]) -> dict | None:
    """根据故障类型 + 置信度选模板（论文 3.4.1）
    
    策略：
      - 高置信度（>=0.85）：优先 low risk 模板（restart_pod）
      - 中置信度（0.5-0.85）：选 medium risk 模板（scale/rollback）
      - 低置信度：只用 low risk 模板，宁缺勿滥
    """
    candidates = [t for t in available if fault_type in t["fault_types"]]
    if not candidates:
        return None
    
    if confidence >= HIGH_RISK_CONFIDENCE_THRESHOLD:
        # 优先 low risk，没有再 medium
        order = {"low": 0, "medium": 1, "high": 2}
    else:
        # 中低置信度：禁用 high risk
        candidates = [c for c in candidates if c["risk_level"] != "high"]
        order = {"low": 0, "medium": 1}
    
    candidates.sort(key=lambda t: order.get(t["risk_level"], 99))
    return candidates[0] if candidates else None


def get_current_pod(service: str, namespace: str = "train-ticket") -> str | None:
    """通过 kubectl 拿当下真实 Pod 名"""
    try:
        p = subprocess.run(
            ["kubectl", "get", "pod", "-n", namespace,
             "-l", f"app={service}",
             "-o", "jsonpath={.items[0].metadata.name}"],
            capture_output=True, text=True, timeout=10,
        )
        return p.stdout.strip() or None
    except Exception:
        return None


def safety_check(template: dict, params: dict, confidence: float) -> dict:
    """4 道护栏（论文 3.4.2）
    返回 {passed: bool, checks: [{name, passed, reason}]}
    """
    checks = []
    
    # G1. 命名空间白名单
    ns = params.get("namespace", "")
    g1 = ns in MANAGED_NS
    checks.append({"name": "G1_managed_namespace",
                   "passed": g1, "reason": f"ns={ns} {'in' if g1 else 'NOT in'} {MANAGED_NS}"})
    
    # G2. Pod 在图谱中存在
    pod_name = params.get("pod_name") or params.get("deployment_name")
    if pod_name:
        # 用前缀匹配，因为 pod_name 可能带 hash 后缀
        cypher = f"MATCH (p:Pod) WHERE p.name STARTS WITH '{pod_name.split('-')[0]}' OR p.name = '{pod_name}' RETURN p.name LIMIT 1"
        result = json.loads(query_graph_topology(cypher))
        g2 = bool(result.get("rows"))
        checks.append({"name": "G2_target_in_graph",
                       "passed": g2,
                       "reason": f"图谱中{'找到' if g2 else '未找到'} {pod_name}"})
    else:
        checks.append({"name": "G2_target_in_graph",
                       "passed": True, "reason": "无 pod_name 参数，跳过"})
    
    # G3. 高风险操作需高置信度
    risk = template.get("risk_level", "medium")
    g3 = (risk != "high") or (confidence >= HIGH_RISK_CONFIDENCE_THRESHOLD)
    checks.append({"name": "G3_high_risk_confidence",
                   "passed": g3,
                   "reason": f"risk={risk} confidence={confidence:.2f} threshold={HIGH_RISK_CONFIDENCE_THRESHOLD}"})
    
    # G4. 去重（同 service 同 SOP 5 分钟内不可重复）
    dedup_key = f"{template['name']}:{params.get('namespace', '')}:{pod_name or ''}"
    now = time.time()
    last_ts = _RECENT_ACTIONS.get(dedup_key, 0)
    g4 = (now - last_ts) >= DEDUP_WINDOW_SEC
    checks.append({"name": "G4_dedup_window",
                   "passed": g4,
                   "reason": f"{'OK' if g4 else f'重复操作（上次 {int(now-last_ts)}s 前）'}"})
    
    all_passed = all(c["passed"] for c in checks)
    if all_passed:
        _RECENT_ACTIONS[dedup_key] = now
    
    return {"passed": all_passed, "checks": checks}


def plan_sop(diagnosis: dict, dry_run: bool = True) -> dict:
    """主入口：从 Agent 诊断到可执行 SOP plan
    
    diagnosis: {
        "root_cause": str,
        "fault_type": "CPU" / "NETWORK" / "POD_KILL",
        "confidence": float,
        "affected_service": "ts-xxx",
    }
    """
    fault_type = diagnosis.get("fault_type", "").upper()
    confidence = float(diagnosis.get("confidence", 0.5))
    service = diagnosis.get("affected_service", "")
    
    # 1. 选模板
    templates = load_templates()
    tmpl = pick_template(fault_type, confidence, templates)
    if not tmpl:
        return {"status": "no_template",
                "reason": f"无适配 {fault_type} 的模板（confidence={confidence}）"}
    
    # 2. 填参（按模板需求自动从 K8s 拿）
    params = {
        "namespace": "train-ticket",
        "deployment_name": service,
        "app_label": service,
    }
    if "pod_name" in tmpl["params"]["required"]:
        pod_name = get_current_pod(service)
        if not pod_name:
            return {"status": "param_missing",
                    "reason": f"无法获取 {service} 的当下 Pod 名"}
        params["pod_name"] = pod_name
    if "replicas" in tmpl["params"]["required"]:
        params["replicas"] = 2  # 横向扩容默认 +1
    if "pod_label_selector" in tmpl["params"]["required"]:
        params["pod_label_selector"] = service
    if "node_name" in tmpl["params"]["required"]:
        # cordon 操作需手动指定，这里默认值，实际不应自动 cordon
        params["node_name"] = "fresne"
    
    # 3. 渲染命令
    rendered_commands = []
    for cmd in tmpl["commands"]:
        try:
            rendered_commands.append(cmd.format(**params))
        except KeyError as e:
            return {"status": "render_failed",
                    "reason": f"模板参数缺失: {e}"}
    
    # 4. 护栏校验
    safety = safety_check(tmpl, params, confidence)
    
    return {
        "status": "ready" if safety["passed"] else "blocked",
        "template": tmpl["name"],
        "display_name": tmpl["display_name"],
        "risk_level": tmpl["risk_level"],
        "estimated_mttr_sec": tmpl["estimated_mttr_sec"],
        "params": params,
        "commands": rendered_commands,
        "safety": safety,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    # 自测 3 种故障的 SOP 计划
    cases = [
        {"root_cause": "ts-gateway CPU 飙升", "fault_type": "CPU",
         "confidence": 0.90, "affected_service": "ts-gateway-service"},
        {"root_cause": "ts-preserve 网络异常", "fault_type": "NETWORK",
         "confidence": 0.85, "affected_service": "ts-preserve-service"},
        {"root_cause": "ts-seat 被强杀", "fault_type": "POD_KILL",
         "confidence": 0.95, "affected_service": "ts-seat-service"},
    ]
    
    for i, diag in enumerate(cases, 1):
        print(f"\n{'='*70}")
        print(f"📋 Case {i}: {diag['fault_type']} / {diag['affected_service']}")
        print(f"{'='*70}")
        plan = plan_sop(diag)
        print(f"  Status:       {plan.get('status')}")
        print(f"  Template:     {plan.get('template')}")
        print(f"  Risk Level:   {plan.get('risk_level')}")
        print(f"  MTTR (est.):  {plan.get('estimated_mttr_sec')}s")
        print(f"  Commands:")
        for c in plan.get("commands", []):
            print(f"    $ {c}")
        print(f"  Safety:")
        for ck in plan.get("safety", {}).get("checks", []):
            mark = "✅" if ck["passed"] else "❌"
            print(f"    {mark} {ck['name']}: {ck['reason']}")
