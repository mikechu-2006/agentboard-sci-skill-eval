#!/bin/bash
# 全量测试：ScienceWorld 30 局（test_smoke.jsonl），使用手改版 prompt（scienceworld_base_skill.manual.json）
#   bash local/scripts/run_sci_manual30.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AB="$(dirname "$SCRIPT_DIR")"
ABD="$(cd "$AB/../AgentBoard" && pwd)"
IMG=zzh202121/agentboard:0117
CNAME=ab-sci-manual30
ENVF=$AB/.env.local
RLOG=/logs/agentboard_sci_manual30_run.log
TRACE=/logs/agentboard_sci_manual30_llm_trace.jsonl
CONFIG=eval_configs/local_sci_manual30.yaml
TAG=sci_manual30

set -a; . "$ENVF"; set +a
if [ -z "$BASE_URL" ]; then BASE_URL=$OPENAI_API_BASE; fi
if [ -z "$API_KEY" ]; then API_KEY=$OPENAI_API_KEY; fi
: "${MODEL:?请先在 local/.env.local 设置 MODEL}"
: "${API_KEY:?请先在 local/.env.local 设置 API_KEY}"

echo "[1/3] 清理旧结果与留痕"
docker rm -f "$CNAME" >/dev/null 2>&1 || true
docker run --rm -v "$ABD":/abd "$IMG" bash -lc "rm -rf /abd/results/$TAG"
docker run --rm -v "$AB/logs":/logs "$IMG" bash -lc "rm -f $TRACE $RLOG; touch $TRACE"

echo "[2/3] 启动容器（30 局 x 30 步；模型 $MODEL）"
docker run -d --name "$CNAME" --network host \
  -v "$ABD":/root/agentboard \
  -v "$AB/logs":/logs \
  -w /root/agentboard \
  -e PROJECT_PATH=/root/agentboard \
  -e PYTHONPATH=/root/agentboard/agentboard \
  -e OPENAI_API_KEY="$API_KEY" \
  -e OPENAI_API_BASE="$BASE_URL" \
  -e AB_LLM_TRACE="$TRACE" \
  "$IMG" bash -lc "source /root/miniconda3/etc/profile.d/conda.sh && conda activate agentboard && python -u agentboard/eval_main.py --cfg-path $CONFIG --tasks scienceworld --model openrouter-cot --max_num_steps 30 --log_path /root/agentboard/results/$TAG 2>&1 | tee $RLOG; sleep infinity" >/dev/null

echo "[3/3] 已启动容器 $CNAME；日志 local/logs/${RLOG#/logs/}"
