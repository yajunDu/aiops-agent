"""批量故障注入 + Metrics 采集 - 论文实验数据集生成器"""
import os
import time
import json
import random
import logging
from datetime import datetime
from pathlib import Path

from prom_client import PromClient
from chaos_injector import ChaosInjector


# === 配置 ===
EXP_DIR = Path("~/aiops-project/experiments").expanduser()
GT_DIR = EXP_DIR / "ground-truth"
METRICS_DIR = EXP_DIR / "metrics"
LOG_DIR = EXP_DIR / "logs"
SUMMARY_CSV = EXP_DIR / "summary.csv"

N_PER_FAULT = 30          # 每类故障跑 30 次
BASELINE_SECS = 180       # 注入前采 3 分钟基线
POST_INJECT_SECS = 180    # 注入后采 3 分钟数据
RECOVERY_SECS = 45        # 实验间隔（等集群冷静）
FAULT_TYPES = ["cpu", "network", "pod_kill"]


def setup_logger():
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("batch")


def already_done(exp_id):
    """断点续跑：检查实验是否已完成"""
    gt_file = GT_DIR / f"{exp_id}.json"
    metrics_file = METRICS_DIR / f"{exp_id}.parquet"
    return gt_file.exists() and metrics_file.exists()


def run_one(log, prom, chaos, fault_type, target, idx):
    exp_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{fault_type.replace('_', '-')}-{target.replace('ts-', '').replace('-service', '')}"
    
    if already_done(exp_id):
        log.info(f"⏭️  跳过已完成: {exp_id}")
        return None

    log.info(f"━━━ [{idx}] 开始: {exp_id} ━━━")

    # 1. 记录注入前 Pod 信息
    pod_before, host = chaos.get_pod(target)
    if not pod_before:
        log.warning(f"⚠️  目标服务 {target} 没有 Pod，跳过")
        return None

    # 2. 注入故障
    t_inject_unix = int(time.time())
    t_inject_iso = datetime.now().isoformat()
    
    if fault_type == "cpu":
        ok, params, msg = chaos.inject_cpu(target, exp_id)
    elif fault_type == "network":
        ok, params, msg = chaos.inject_network(target, exp_id)
    elif fault_type == "pod_kill":
        ok, params, msg = chaos.inject_pod_kill(target, exp_id)
    else:
        log.error(f"未知故障类型: {fault_type}")
        return None

    if not ok:
        log.error(f"❌ 注入失败: {msg}")
        return None
    
    log.info(f"  ✅ 注入 {fault_type} -> {target}, params={params}")

    # 3. 等故障生效 + 让 Prometheus 采到指标
    log.info(f"  ⏳ 等 {POST_INJECT_SECS}s 让故障扩散并采集指标...")
    time.sleep(POST_INJECT_SECS)

    # 4. 采集指标（注入前 BASELINE_SECS + 注入后 POST_INJECT_SECS）
    end_ts = time.time()
    start_ts = t_inject_unix - BASELINE_SECS
    log.info(f"  📊 采集 metrics [{int(start_ts)} - {int(end_ts)}] = {(end_ts - start_ts):.0f}s")
    df = prom.collect_window(start_ts, end_ts)
    
    if df.empty:
        log.warning(f"  ⚠️  Prometheus 没数据")
    else:
        df["exp_id"] = exp_id
        df["t_inject_unix"] = t_inject_unix
        metrics_path = METRICS_DIR / f"{exp_id}.parquet"
        df.to_parquet(metrics_path, index=False)
        log.info(f"  💾 metrics 保存: {metrics_path.name} ({len(df)} 行)")

    # 5. 写 Ground Truth
    gt = {
        "experiment_id": exp_id,
        "fault_type": fault_type.upper(),
        "target_service": target,
        "target_namespace": "train-ticket",
        "root_pod": pod_before,
        "root_host": host,
        "t_inject_unix": t_inject_unix,
        "t_inject_iso": t_inject_iso,
        "params": params,
        "metrics_window_start": int(start_ts),
        "metrics_window_end": int(end_ts),
    }
    gt_path = GT_DIR / f"{exp_id}.json"
    gt_path.write_text(json.dumps(gt, indent=2))
    log.info(f"  💾 ground-truth: {gt_path.name}")

    # 6. 清理
    chaos.cleanup(fault_type, exp_id)
    log.info(f"  🧹 已清理 chaos object")

    # 7. 间隔
    log.info(f"  💤 休息 {RECOVERY_SECS}s 让集群恢复...")
    time.sleep(RECOVERY_SECS)

    return exp_id


def main():
    log = setup_logger()
    GT_DIR.mkdir(exist_ok=True)
    METRICS_DIR.mkdir(exist_ok=True)
    
    prom = PromClient()
    chaos = ChaosInjector()
    
    # 生成实验队列：每类故障跑 N_PER_FAULT 次，目标轮换
    queue = []
    for ft in FAULT_TYPES:
        for i in range(N_PER_FAULT):
            target = chaos.targets[i % len(chaos.targets)]
            queue.append((ft, target))
    random.shuffle(queue)  # 打乱顺序，避免同类聚集影响互相干扰
    
    total = len(queue)
    log.info(f"🚀 批量实验启动: 共 {total} 次")
    log.info(f"   配置: 每类 {N_PER_FAULT} 次, 注入后采 {POST_INJECT_SECS}s, 间隔 {RECOVERY_SECS}s")
    log.info(f"   预计耗时: ~{total * (POST_INJECT_SECS + RECOVERY_SECS) / 3600:.1f} 小时")
    log.info(f"   断点续跑: 已存在的实验会自动跳过")
    
    success_count = 0
    fail_count = 0
    for idx, (ft, target) in enumerate(queue, 1):
        try:
            r = run_one(log, prom, chaos, ft, target, f"{idx}/{total}")
            if r:
                success_count += 1
        except Exception as e:
            log.error(f"❌ 实验异常: {e}")
            fail_count += 1
            time.sleep(30)
    
    log.info(f"\n{'='*60}")
    log.info(f"🎉 全部完成: 成功 {success_count} / 失败 {fail_count} / 总计 {total}")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    main()
