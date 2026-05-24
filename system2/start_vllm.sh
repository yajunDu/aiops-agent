#!/bin/bash
cd ~/aiops-project/system2
source venv/bin/activate
pkill -9 -f "vllm.entrypoints" 2>/dev/null
sleep 3
nohup python -m vllm.entrypoints.openai.api_server \
  --model /home/dyj/models/Qwen/Qwen2.5-7B-Instruct-AWQ \
  --served-model-name qwen2.5-7b \
  --quantization awq_marlin --dtype float16 \
  --gpu-memory-utilization 0.85 --max-model-len 2048 \
  --max-num-seqs 4 --no-enable-prefix-caching --enforce-eager \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --host 0.0.0.0 --port 8000 \
  > ~/aiops-portforwards/vllm.log 2>&1 &
echo "vLLM PID: $!  等 30s 后测试 curl http://localhost:8000/v1/models"
