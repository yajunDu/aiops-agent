"""
执行层 · SOP Planner + 4 道安全护栏（从旧 system2/sop 移植）
==============================================================
输入：系统2 的 Diagnosis（root_cause_service / fault_type / confidence）
输出：可执行 SOP plan（命令 + 风险评级 + 护栏状态）

护栏（论文 3.4.2）：
  G1 命名空间白名单（只允许 train-ticket）
  G2 目标在知识图谱中真实存在（dry-run 时跳过在线校验）
  G3 高风险操作需 confidence ≥ 0.85
  G4 同 service 同 SOP 5 分钟去重

remediate(diagnosis) 是给 orchestrator 的统一入口：规划 +（可选）执行。
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import yaml

from ..core.contracts import Diagnosis
from ..config import MANAGED_NAMESPACE, HIGH_RISK_CONFIDENCE

TEMPLATES_DIR = Path(__file__).parent / "templates"
MANAGED_NS = {MANAGED_NAMESPACE}
DEDUP_WINDOW_SEC = 300
_RECENT_ACTIONS: dict[str, float] = {}


def load_templates() -> list[dict]:
    out = []
    for f in sorted(TEMPLATES_DIR.glob("*.yaml")):
        out.append(yaml.safe_load(f.read_text(encoding="utf-8")))
    return out


def pick_template(fault_type: str, confidence: float, available: list[dict]) -> dict | None:
    """按故障类型 + 置信度选模板（高置信优先 low risk；中低置信禁用 high risk）。"""
    cands = [t for t in available if fault_type in t["fault_types"]]
    if not cands:
        return None
    if confidence >= HIGH_RISK_CONFIDENCE:
        order = {"low": 0, "medium": 1, "high": 2}
    else:
        cands = [c for c in cands if c["risk_level"] != "high"]
        order = {"low": 0, "medium": 1}
    cands.sort(key=lambda t: order.get(t["risk_level"], 99))
    return cands[0] if cands else None


def get_current_pod(service: str, namespace: str = MANAGED_NAMESPACE) -> str | None:
    try:
        p = subprocess.run(
            ["kubectl", "get", "pod", "-n", namespace, "-l", f"app={service}",
             "-o", "jsonpath={.items[0].metadata.name}"],
            capture_output=True, text=True, timeout=10)
        return p.stdout.strip() or None
    except Exception:
        return None


def _g2_target_in_graph(pod_or_dep: str, dry_run: bool) -> dict:
    if dry_run:
        return {"name": "G2_target_in_graph", "passed": True, "reason": "dry-run 跳过在线图谱校验"}
    try:
        from ..cognition.tools.graph_tools import run_cypher
        prefix = pod_or_dep.split("-")[0]
        cy = (f"MATCH (n) WHERE (n:Pod OR n:Service) AND "
              f"(n.name STARTS WITH '{prefix}' OR n.name = '{pod_or_dep}') RETURN n.name LIMIT 1")
        rows = json.loads(run_cypher(cy)).get("rows", [])
        ok = bool(rows)
        return {"name": "G2_target_in_graph", "passed": ok,
                "reason": f"图谱中{'找到' if ok else '未找到'} {pod_or_dep}"}
    except Exception as e:
        return {"name": "G2_target_in_graph", "passed": False, "reason": f"图谱校验失败: {e}"}


def safety_check(template: dict, params: dict, confidence: float, dry_run: bool) -> dict:
    checks = []
    ns = params.get("namespace", "")
    g1 = ns in MANAGED_NS
    checks.append({"name": "G1_managed_namespace", "passed": g1,
                   "reason": f"ns={ns} {'in' if g1 else 'NOT in'} {sorted(MANAGED_NS)}"})

    target = params.get("pod_name") or params.get("deployment_name")
    checks.append(_g2_target_in_graph(target, dry_run) if target else
                  {"name": "G2_target_in_graph", "passed": True, "reason": "无目标参数，跳过"})

    risk = template.get("risk_level", "medium")
    g3 = (risk != "high") or (confidence >= HIGH_RISK_CONFIDENCE)
    checks.append({"name": "G3_high_risk_confidence", "passed": g3,
                   "reason": f"risk={risk} conf={confidence:.2f} thr={HIGH_RISK_CONFIDENCE}"})

    dedup_key = f"{template['name']}:{params.get('namespace','')}:{target or ''}"
    now = time.time()
    g4 = (now - _RECENT_ACTIONS.get(dedup_key, 0)) >= DEDUP_WINDOW_SEC
    checks.append({"name": "G4_dedup_window", "passed": g4,
                   "reason": "OK" if g4 else "5 分钟内重复操作"})

    passed = all(c["passed"] for c in checks)
    if passed:
        _RECENT_ACTIONS[dedup_key] = now
    return {"passed": passed, "checks": checks}


def plan_sop(fault_type: str, confidence: float, service: str, dry_run: bool = True) -> dict:
    fault_type = (fault_type or "").upper()
    templates = load_templates()
    tmpl = pick_template(fault_type, confidence, templates)
    if not tmpl:
        return {"status": "no_template", "reason": f"无适配 {fault_type} 的模板"}

    params = {"namespace": MANAGED_NAMESPACE, "deployment_name": service, "app_label": service}
    req = tmpl["params"]["required"]
    if "pod_name" in req:
        params["pod_name"] = get_current_pod(service) or f"{service}-0"  # 离线回退占位
    if "replicas" in req:
        params["replicas"] = 2
    if "pod_label_selector" in req:
        params["pod_label_selector"] = service
    if "node_name" in req:
        params["node_name"] = "fresne"

    rendered = []
    for cmd in tmpl["commands"]:
        try:
            rendered.append(cmd.format(**params))
        except KeyError as e:
            return {"status": "render_failed", "reason": f"模板参数缺失: {e}"}

    safety = safety_check(tmpl, params, confidence, dry_run)
    return {
        "status": "ready" if safety["passed"] else "blocked",
        "template": tmpl["name"], "display_name": tmpl["display_name"],
        "risk_level": tmpl["risk_level"], "estimated_mttr_sec": tmpl["estimated_mttr_sec"],
        "params": params, "commands": rendered, "safety": safety, "dry_run": dry_run,
    }


def remediate(diagnosis: Diagnosis, dry_run: bool = True, execute: bool = False) -> dict:
    """orchestrator 入口：根据诊断规划 SOP，按需执行。"""
    plan = plan_sop(diagnosis.fault_type.value, diagnosis.confidence,
                    diagnosis.root_cause_service, dry_run=dry_run)
    result = dict(plan)
    result["executed"] = False
    result["mttr_sec"] = None
    if execute and plan.get("status") == "ready":
        from .sop_executor import execute_plan        # 局部导入避免循环依赖
        report = execute_plan(plan, dry_run=dry_run)
        result["executed"] = report.get("executed", False)
        result["mttr_sec"] = report.get("mttr_sec")
        result["execution"] = report
    return result
