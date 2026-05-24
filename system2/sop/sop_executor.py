"""
13.4 SOP 执行器
=================
- 接收 sop_planner 输出的 plan
- 三种模式：
    dry_run=True       : 只打印命令，不真执行（默认）
    dry_run=False      : 真执行 kubectl
    interactive=True   : 执行前 y/N 确认
- post_check 自动跑（验证恢复）
- 记录 MTTR（执行→pod ready 的时长）
"""
from __future__ import annotations
import json
import subprocess
import time
from pathlib import Path
import yaml

from sop_planner import plan_sop, load_templates


def run_cmd(cmd: str, timeout: int = 120) -> dict:
    """执行 shell 命令，返回 returncode + stdout + stderr"""
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return {
            "cmd": cmd,
            "returncode": p.returncode,
            "stdout": p.stdout.strip()[:500],
            "stderr": p.stderr.strip()[:500],
            "elapsed_sec": round(time.time() - t0, 2),
            "ok": p.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "returncode": -1, "stdout": "", "stderr": "TIMEOUT",
                "elapsed_sec": timeout, "ok": False}
    except Exception as e:
        return {"cmd": cmd, "returncode": -2, "stdout": "", "stderr": str(e),
                "elapsed_sec": round(time.time() - t0, 2), "ok": False}


def execute_plan(plan: dict, dry_run: bool = True, interactive: bool = False) -> dict:
    """执行 SOP plan。返回完整执行报告（含 MTTR）"""
    if plan.get("status") != "ready":
        return {"executed": False, "success": False, "mttr_sec": 0.0,
                "command_results": [], "post_check_results": [],
                "reason": f"plan 状态非 ready: {plan.get('status')}",
                "plan": plan}
    
    # 加载模板拿 post_check
    tmpl_name = plan["template"]
    templates = load_templates()
    tmpl = next((t for t in templates if t["name"] == tmpl_name), None)
    post_checks = tmpl.get("post_check", []) if tmpl else []
    params = plan["params"]
    
    # 交互式确认
    if interactive and not dry_run:
        print(f"\n⚠️  即将执行 [{plan['risk_level']}] 风险 SOP: {plan['display_name']}")
        for c in plan["commands"]:
            print(f"   $ {c}")
        confirm = input("\n确认执行？输入 'yes' 继续 > ")
        if confirm.strip().lower() != "yes":
            return {"executed": False, "success": False, "mttr_sec": 0.0,
                    "command_results": [], "post_check_results": [],
                    "reason": "用户取消"}
    
    report = {
        "executed": False,
        "dry_run": dry_run,
        "template": tmpl_name,
        "t_start": time.time(),
        "command_results": [],
        "post_check_results": [],
        "mttr_sec": None,
        "success": False,
    }
    
    # 1. 执行命令
    for cmd in plan["commands"]:
        if dry_run:
            print(f"  [DRY-RUN] $ {cmd}")
            report["command_results"].append({
                "cmd": cmd, "dry_run": True, "ok": True,
            })
        else:
            print(f"  [EXEC] $ {cmd}")
            r = run_cmd(cmd)
            report["command_results"].append(r)
            print(f"     → rc={r['returncode']} elapsed={r['elapsed_sec']}s")
            if not r["ok"]:
                print(f"     ❌ stderr: {r['stderr'][:200]}")
                report["t_end"] = time.time()
                report["mttr_sec"] = round(report["t_end"] - report["t_start"], 1)
                return report
    
    report["executed"] = True
    
    # 2. post_check（验证恢复）
    if not dry_run and post_checks:
        print(f"  [POST-CHECK] 验证恢复...")
        for pc in post_checks:
            try:
                rendered = pc.format(**params)
            except KeyError:
                rendered = pc
            r = run_cmd(rendered, timeout=180)
            report["post_check_results"].append(r)
            print(f"     $ {rendered}")
            print(f"     → rc={r['returncode']} elapsed={r['elapsed_sec']}s")
            if not r["ok"]:
                print(f"     ❌ {r['stderr'][:200]}")
                report["t_end"] = time.time()
                report["mttr_sec"] = round(report["t_end"] - report["t_start"], 1)
                return report
    
    report["t_end"] = time.time()
    report["mttr_sec"] = round(report["t_end"] - report["t_start"], 1)
    report["success"] = True
    return report


if __name__ == "__main__":
    print("=" * 70)
    print("🧪 测试 1: dry-run 模式（不会真执行 kubectl）")
    print("=" * 70)
    diag = {"root_cause": "ts-seat CPU 飙升", "fault_type": "CPU",
            "confidence": 0.92, "affected_service": "ts-seat-service"}
    plan = plan_sop(diag)
    print(f"  Plan status: {plan.get('status')}")
    print(f"  Template:    {plan.get('template')}")
    print()
    report = execute_plan(plan, dry_run=True)
    print(f"\n  Result: executed={report['executed']} success={report['success']}")
    print(f"  MTTR:   {report['mttr_sec']}s")
    
    print()
    print("=" * 70)
    print("🚀 测试 2: 真执行 restart_pod（会真杀一个 Pod）")
    print("=" * 70)
    print("说明：将真实执行 'kubectl delete pod' 重启 ts-seat-service")
    print("      这是 demo TrainTicket 环境，安全可重建")
    confirm = input("\n按 ENTER 继续，输入 'skip' 跳过 > ")
    
    if confirm.strip().lower() != "skip":
        diag2 = {"root_cause": "demo: 重启 seat", "fault_type": "POD_KILL",
                 "confidence": 0.95, "affected_service": "ts-seat-service"}
        plan2 = plan_sop(diag2)
        print(f"\n  Plan: {plan2.get('template')}")
        print()
        report2 = execute_plan(plan2, dry_run=False)
        print(f"\n{'='*50}")
        print(f"📊 执行报告")
        print(f"{'='*50}")
        print(f"  执行:   {report2['executed']}")
        print(f"  成功:   {report2['success']}")
        print(f"  MTTR:   {report2['mttr_sec']} 秒")
        print(f"  命令数: {len(report2['command_results'])}")
        print(f"  验证数: {len(report2['post_check_results'])}")
    else:
        print("已跳过真执行测试。")
