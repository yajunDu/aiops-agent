"""
执行层 · SOP 执行器（从旧 system2/sop 移植）
=============================================
接收 plan_sop 的 plan，三种模式：
  dry_run=True   只打印命令，不真执行（默认；回放/演示用）
  dry_run=False  真执行 kubectl
  interactive    执行前 y/N 确认
执行后自动跑 post_check 验证恢复，并记录 MTTR（执行→恢复）。
"""
from __future__ import annotations

import subprocess
import time

from .sop_planner import load_templates


def run_cmd(cmd: str, timeout: int = 120) -> dict:
    t0 = time.time()
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {"cmd": cmd, "returncode": p.returncode,
                "stdout": p.stdout.strip()[:500], "stderr": p.stderr.strip()[:500],
                "elapsed_sec": round(time.time() - t0, 2), "ok": p.returncode == 0}
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "returncode": -1, "stdout": "", "stderr": "TIMEOUT",
                "elapsed_sec": timeout, "ok": False}
    except Exception as e:
        return {"cmd": cmd, "returncode": -2, "stdout": "", "stderr": str(e),
                "elapsed_sec": round(time.time() - t0, 2), "ok": False}


def execute_plan(plan: dict, dry_run: bool = True, interactive: bool = False) -> dict:
    if plan.get("status") != "ready":
        return {"executed": False, "success": False, "mttr_sec": 0.0,
                "command_results": [], "post_check_results": [],
                "reason": f"plan 状态非 ready: {plan.get('status')}", "plan": plan}

    tmpl = next((t for t in load_templates() if t["name"] == plan["template"]), None)
    post_checks = tmpl.get("post_check", []) if tmpl else []
    params = plan["params"]

    if interactive and not dry_run:
        print(f"\n⚠️  即将执行 [{plan['risk_level']}] 风险 SOP: {plan['display_name']}")
        for c in plan["commands"]:
            print(f"   $ {c}")
        if input("\n确认执行？输入 'yes' 继续 > ").strip().lower() != "yes":
            return {"executed": False, "success": False, "mttr_sec": 0.0,
                    "command_results": [], "post_check_results": [], "reason": "用户取消"}

    report = {"executed": False, "dry_run": dry_run, "template": plan["template"],
              "t_start": time.time(), "command_results": [], "post_check_results": [],
              "mttr_sec": None, "success": False}

    for cmd in plan["commands"]:
        if dry_run:
            print(f"  [DRY-RUN] $ {cmd}")
            report["command_results"].append({"cmd": cmd, "dry_run": True, "ok": True})
        else:
            r = run_cmd(cmd)
            report["command_results"].append(r)
            if not r["ok"]:
                report["t_end"] = time.time()
                report["mttr_sec"] = round(report["t_end"] - report["t_start"], 1)
                return report
    report["executed"] = True

    if not dry_run and post_checks:
        for pc in post_checks:
            try:
                rendered = pc.format(**params)
            except KeyError:
                rendered = pc
            r = run_cmd(rendered, timeout=180)
            report["post_check_results"].append(r)
            if not r["ok"]:
                report["t_end"] = time.time()
                report["mttr_sec"] = round(report["t_end"] - report["t_start"], 1)
                return report

    report["t_end"] = time.time()
    report["mttr_sec"] = round(report["t_end"] - report["t_start"], 1)
    report["success"] = True
    return report
