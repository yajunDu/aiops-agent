"""集中配置（初赛版）。全部可用环境变量覆盖。"""
from __future__ import annotations
import os

# ── LLM（本地 vLLM，OpenAI 兼容）──────────────────────────────
LLM_URL = os.getenv("AIOPS_LLM_URL", "http://localhost:8000/v1")
MODEL_NAME = os.getenv("AIOPS_MODEL", "qwen2.5-7b")
LLM_TEMPERATURE = float(os.getenv("AIOPS_LLM_TEMP", "0.1"))
LLM_MAX_TOKENS = int(os.getenv("AIOPS_LLM_MAX_TOKENS", "768"))

# ── 知识图谱 Neo4j ────────────────────────────────────────────
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PWD = os.getenv("NEO4J_PWD", "")

# ── 指标来源 ──────────────────────────────────────────────────
LIVE_MODE = os.getenv("AIOPS_LIVE_MODE", "0") == "1"   # 1=实时Prom，0=parquet回放
PROM_URL = os.getenv("AIOPS_PROM_URL", "http://localhost:9090")
METRICS_DIR = os.getenv("AIOPS_METRICS_DIR", "experiments/metrics")

# ── Agent / 执行 ──────────────────────────────────────────────
MAX_TOOL_LOOPS = int(os.getenv("AIOPS_MAX_TOOL_LOOPS", "6"))
MANAGED_NAMESPACE = os.getenv("AIOPS_NAMESPACE", "train-ticket")
HIGH_RISK_CONFIDENCE = float(os.getenv("AIOPS_HIGH_RISK_CONF", "0.85"))
RECOVERY_TIMEOUT_SEC = int(os.getenv("AIOPS_RECOVERY_TIMEOUT", "180"))  # JVM 冷启动现实

# ── 感知范围（在线定位关键适配）──────────────────────────────
# 只监控核心业务服务，排除预期就不稳定的边缘/批处理服务（降噪，提升定位质量）
MONITORED_SERVICES = set(filter(None, os.getenv(
    "AIOPS_MONITORED_SERVICES",
    "ts-gateway-service,ts-seat-service,ts-preserve-service,ts-basic-service,"
    "ts-ui-dashboard,ts-admin-order-service,ts-admin-user-service,ts-admin-basic-info-service"
).split(",")))
