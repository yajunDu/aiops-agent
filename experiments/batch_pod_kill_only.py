"""只补跑 pod_kill 类型故障"""
import time
import logging
import random
from pathlib import Path

# 临时改 FAULT_TYPES，复用主脚本
import batch_runner
batch_runner.FAULT_TYPES = ["pod_kill"]
batch_runner.N_PER_FAULT = 30

if __name__ == "__main__":
    batch_runner.main()
