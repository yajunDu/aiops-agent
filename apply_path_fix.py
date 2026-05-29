#!/usr/bin/env python3
"""
一键把项目里所有硬编码的 ~/aiops-project 路径改成读 aiops_paths 模块。
在仓库根目录运行: python apply_path_fix.py
幂等：可重复运行。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# (文件相对路径, 旧片段 -> 新片段) 的映射
REPLACEMENTS = {
    "ui-backend/server.py": [
        ('sys.path.insert(0, str(Path("~/aiops-project/system2/agent").expanduser()))',
         'from aiops_paths import AGENT_PATH, TOOLS_PATH, SYSTEM1_OUT, SYSTEM2_OUT, BASELINES\nsys.path.insert(0, str(AGENT_PATH))'),
        ('sys.path.insert(0, str(Path("~/aiops-project/system2/agent/tools").expanduser()))',
         'sys.path.insert(0, str(TOOLS_PATH))'),
        ('SYS1_OUT = Path("~/aiops-project/system1/outputs").expanduser()', 'SYS1_OUT = SYSTEM1_OUT'),
        ('SYS2_OUT = Path("~/aiops-project/system2/outputs").expanduser()', 'SYS2_OUT = SYSTEM2_OUT'),
        ('BASELINES = Path("~/aiops-project/system2/baselines").expanduser()', 'BASELINES = BASELINES'),
    ],
    "ui-backend/smart_chat.py": [
        ('AGENT_PATH = Path("~/aiops-project/system2/agent").expanduser()\nTOOLS_PATH = Path("~/aiops-project/system2/agent/tools").expanduser()',
         'from aiops_paths import AGENT_PATH, TOOLS_PATH'),
    ],
    "system2/agent/coordinator.py": [
        ('SYSTEM1_OUT = Path("~/aiops-project/system1/outputs").expanduser()', 'from aiops_paths import SYSTEM1_OUT, SYSTEM2_OUT'),
        ('SYSTEM2_OUT = Path("~/aiops-project/system2/outputs").expanduser()', ''),
    ],
    "system2/agent/tools/tools_prom_replay.py": [
        ('EXP_DIR = Path("~/aiops-project/experiments").expanduser()', 'from aiops_paths import EXP_DIR'),
    ],
    "system1/train_iforest.py": [
        ('OUT = Path("~/aiops-project/system1/outputs").expanduser()', 'from aiops_paths import SYSTEM1_OUT as OUT, SYSTEM1_FIG as FIG'),
        ('FIG = Path("~/aiops-project/system1/figures").expanduser()', ''),
    ],
    "system1/anomaly_slicer.py": [
        ('OUT = Path("~/aiops-project/system1/outputs").expanduser()', 'from aiops_paths import SYSTEM1_OUT as OUT'),
    ],
    "experiments/batch_runner.py": [
        ('EXP_DIR = Path("~/aiops-project/experiments").expanduser()', 'from aiops_paths import EXP_DIR'),
    ],
    "system2/baselines/naive_llm_rag.py": [
        ('EXP_DIR = Path("~/aiops-project/experiments").expanduser()', 'from aiops_paths import EXP_DIR, SYSTEM1_OUT'),
        ('Path("~/aiops-project/system1/outputs/experiment_results.csv").expanduser()', '(SYSTEM1_OUT / "experiment_results.csv")'),
    ],
    "system2/baselines/microrca.py": [
        ('EXP_DIR = Path("~/aiops-project/experiments").expanduser()', 'from aiops_paths import EXP_DIR, SYSTEM1_OUT'),
        ('Path("~/aiops-project/system1/outputs/experiment_results.csv").expanduser()', '(SYSTEM1_OUT / "experiment_results.csv")'),
    ],
    "system2/baselines/rule_based.py": [
        ('EXP_DIR = Path("~/aiops-project/experiments").expanduser()', 'from aiops_paths import EXP_DIR, SYSTEM1_OUT'),
        ('Path("~/aiops-project/system1/outputs/experiment_results.csv").expanduser()', '(SYSTEM1_OUT / "experiment_results.csv")'),
    ],
}

# 让子目录脚本能 import 到根目录的 aiops_paths
SYS_PATH_INJECT = (
    "import sys as _s; from pathlib import Path as _P\n"
    "_s.path.insert(0, str(_P(__file__).resolve().parents[{depth}]))\n"
)


def patch_file(rel, repls):
    f = ROOT / rel
    if not f.exists():
        print(f"  ⚠️  跳过（不存在）: {rel}")
        return
    txt = f.read_text(encoding="utf-8")
    orig = txt
    # 注入 sys.path（让子目录能找到根的 aiops_paths）
    depth = rel.count("/")
    inject = SYS_PATH_INJECT.format(depth=depth)
    if "aiops_paths" not in txt and depth > 0:
        # 在第一个 import 前插入
        m = re.search(r"^(from |import )", txt, re.M)
        if m:
            txt = txt[:m.start()] + inject + txt[m.start():]
    for old, new in repls:
        if old in txt:
            txt = txt.replace(old, new)
    if txt != orig:
        f.write_text(txt, encoding="utf-8")
        print(f"  ✅ 已改: {rel}")
    else:
        print(f"  ⏭️  无变化: {rel}")


if __name__ == "__main__":
    print(f"仓库根: {ROOT}\n开始替换硬编码路径...\n")
    for rel, repls in REPLACEMENTS.items():
        patch_file(rel, repls)
    print("\n完成。验证: grep -rn '~/aiops-project' --include='*.py' .")
