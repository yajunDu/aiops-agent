#!/bin/bash
# 启动 vLLM 推理引擎
# 用法: VLLM_MODEL_PATH=/your/model/path ./start_vllm.sh
set -e

MODEL_PATH="${VLLM_MODEL_PATH:-/path/to/Qwen2.5-7B-Instruct-AWQ}"
LOG_DIR="${AIOPS_LOG_DIR:-$HOME/aiops-portforwards}"
mkdir -p "$LOG_DIR"

if [ ! -d "$MODEL_PATH" ]; then
  echo "❌ 模型路径不存在: $MODEL_PATH"
  echo "   请设置 VLLM_MODEL_PATH 环境变量指向 Qwen2.5-7B-AWQ 权重目录"
  echo "   下载: https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-AWQ"
  exit 1
fi

pkill -9 -f "vllm.entrypoints" 2>/dev/null || true
sleep 3

nohup python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL_PATH" \
  --served-model-name qwen2.5-7b \
  --quantization awq_marlin --dtype float16 \
  --gpu-memory-utilization 0.85 --max-model-len 2048 \
  --max-num-seqs 4 --no-enable-prefix-caching --enforce-eager \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --host 0.0.0.0 --port 8000 \
  > "$LOG_DIR/vllm.log" 2>&1 &

echo "vLLM PID: $!  等 30-45s 后测试: curl http://localhost:8000/v1/models"
