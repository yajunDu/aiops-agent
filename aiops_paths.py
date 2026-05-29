"""
统一路径解析 - 解决硬编码 ~/aiops-project 问题
优先级: 环境变量 AIOPS_ROOT > 自动推断（本文件所在仓库根）> ~/aiops-project
"""
import os
from pathlib import Path


def _detect_root() -> Path:
    # 1. 环境变量优先
    env = os.getenv("AIOPS_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    # 2. 自动推断：本文件通常在仓库根，向上找含 system1/system2 的目录
    here = Path(__file__).resolve().parent
    for p in [here] + list(here.parents):
        if (p / "system1").is_dir() and (p / "system2").is_dir():
            return p
    # 3. 兜底
    return Path("~/aiops-project").expanduser()


AIOPS_ROOT = _detect_root()

SYSTEM1_OUT = AIOPS_ROOT / "system1" / "outputs"
SYSTEM1_FIG = AIOPS_ROOT / "system1" / "figures"
SYSTEM2_OUT = AIOPS_ROOT / "system2" / "outputs"
AGENT_PATH = AIOPS_ROOT / "system2" / "agent"
TOOLS_PATH = AIOPS_ROOT / "system2" / "agent" / "tools"
BASELINES = AIOPS_ROOT / "system2" / "baselines"
EXP_DIR = AIOPS_ROOT / "experiments"

if __name__ == "__main__":
    print(f"AIOPS_ROOT = {AIOPS_ROOT}")
    for k, v in [("SYSTEM1_OUT", SYSTEM1_OUT), ("AGENT_PATH", AGENT_PATH),
                 ("EXP_DIR", EXP_DIR), ("BASELINES", BASELINES)]:
        print(f"  {k} = {v}")
