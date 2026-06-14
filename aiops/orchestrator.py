"""
闭环编排器 —— 初赛 demo 的脊柱
================================
    detect ──► diagnose ──► remediate ──► verify

两种驱动：
  • 回放驱动（演示/录视频）：传入 slices（来自 detector.detect_from_experiment_parquet
    或 load_slices_from_csv），dry_run=True，不碰真集群也能跑完整条链。
  • 在线驱动（真集群）：slices=None → 自动调 detect_anomalies；dry_run=False 真执行 + 真验证。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .core.contracts import AnomalySlice, Diagnosis
from .config import MANAGED_NAMESPACE, RECOVERY_TIMEOUT_SEC


@dataclass
class LoopResult:
    slice_id: str
    diagnosis: dict
    remediation: Optional[dict] = None
    recovered: Optional[bool] = None
    mttr_sec: Optional[float] = None
    timeline: list[dict] = field(default_factory=list)


def run_closed_loop(slices: list[AnomalySlice] | None = None,
                    window=None, dry_run: bool = True,
                    auto_remediate: bool = True, verify: bool = True,
                    on_event=None) -> list[LoopResult]:
    """跑一轮闭环。

    Args:
        slices: 回放驱动时直接传入异常切片；None 则在线检测。
        dry_run: True=不真执行 kubectl（演示）；False=真执行（在线）。
        auto_remediate: 诊断确定时是否规划/执行 SOP 自愈。
        verify: 自愈后是否确认业务恢复。
        on_event: 回调 fn(stage, msg)，给 UI 实时推送时间线。
    """
    timeline: list[dict] = []

    def log(stage: str, msg: str):
        timeline.append({"t": time.time(), "stage": stage, "msg": msg})
        if on_event:
            on_event(stage, msg)

    from .cognition.agent import diagnose
    from .remediation.sop_planner import remediate

    # 1) 感知
    if slices is None:
        from .perception.detector import detect_anomalies
        log("detect", "系统1 扫描遥测，输出异常切片…")
        slices = detect_anomalies(window)
    else:
        log("detect", f"回放驱动：载入 {len(slices)} 个异常切片")
    log("detect", f"共 {len(slices)} 个异常切片")

    results: list[LoopResult] = []
    for sl in slices:
        sl.ensure_services()

        # 2) 认知：拓扑根因定位
        log("diagnose", f"切片 {sl.slice_id}：拓扑根因定位中（候选 {sl.suspect_services}）…")
        dg: Diagnosis = diagnose(sl)
        log("diagnose", f"根因={dg.root_cause_service} 类型={dg.fault_type.value} "
                        f"置信度={dg.confidence:.2f}")

        # 3) 执行：SOP 自愈（4 道护栏）
        rem = None
        if auto_remediate and dg.root_cause_service not in ("", "UNKNOWN") \
                and dg.fault_type.value != "UNKNOWN":
            log("remediate", f"规划 SOP（{dg.root_cause_service}/{dg.fault_type.value}）…")
            rem = remediate(dg, dry_run=dry_run, execute=not dry_run)
            log("remediate", f"状态={rem.get('status')} 模板={rem.get('template')} "
                             f"{'(dry-run)' if dry_run else '已执行'}")
        else:
            log("remediate", "诊断不确定，跳过自动处置（转人工）")

        # 4) 验证：业务恢复确认
        recovered, mttr = None, rem.get("mttr_sec") if rem else None
        if verify and rem and rem.get("executed") and not dry_run:
            log("verify", "等待业务恢复并确认…")
            recovered, mttr2 = _verify_recovery(dg.root_cause_service)
            mttr = mttr2 if mttr2 is not None else mttr
            log("verify", f"恢复={recovered} MTTR={mttr}s")

        results.append(LoopResult(
            slice_id=sl.slice_id, diagnosis=dg.to_dict(),
            remediation=rem, recovered=recovered, mttr_sec=mttr,
            timeline=list(timeline),
        ))
    return results


def _verify_recovery(service: str, namespace: str = MANAGED_NAMESPACE,
                     timeout: int = RECOVERY_TIMEOUT_SEC):
    """kubectl 等待 Pod Ready 确认恢复并返回 MTTR。

    TrainTicket 为 Spring Boot，冷启动 60–120s，超时窗默认 180s。
    """
    import subprocess
    t0 = time.time()
    try:
        p = subprocess.run(
            ["kubectl", "wait", "--for=condition=Ready", "pod",
             "-l", f"app={service}", "-n", namespace, f"--timeout={timeout}s"],
            capture_output=True, text=True, timeout=timeout + 10)
        return p.returncode == 0, round(time.time() - t0, 1)
    except Exception:
        return None, round(time.time() - t0, 1)
