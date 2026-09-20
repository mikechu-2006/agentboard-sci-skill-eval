#!/bin/bash
# AgentBoard「注入 skill」评测（默认只 alfworld；可用环境变量跑三任务/自定义规模）
#
#   # 只 alfworld（默认，与之前一致）
#   bash local/scripts/run_agentboard_skill_eval.sh 30
#
#   # 三任务各前 30 局（babyai 实际 28，见 HOWTO）
#   TASKS="alfworld scienceworld babyai" RESULTS=results/skill_eval_30 TAG=skill30 \
#     EPISODES="alfworld=30,scienceworld=30,babyai=30" \
#     bash local/scripts/run_agentboard_skill_eval.sh 30
#
# 可用环境变量: TASKS / RESULTS / TAG / EPISODES / SKILL / SKILL_ENV / CONFIG / BASE_CONFIG
# 特点: 独立容器 + 独立结果目录 + 独立留痕，因此可与 SkillOpt 训练并行（注意共用 API 额度）。
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AB="$(dirname "$SCRIPT_DIR")"
ABD="$(cd "$AB/../AgentBoard" && pwd)"
IMG=zzh202121/agentboard:0117
CNAME=ab-agentboard-skill
ENVF=$AB/.env.local
MODELKEY=openrouter-cot

STEPS="${1:-30}"
TASKS="${TASKS:-alfworld}"
RESULTS="${RESULTS:-results/skill_eval}"
TAG="${TAG:-skill}"
EPISODES="${EPISODES:-}"
SKILL="${SKILL:-$AB/skills/alfworld_gpt5.5_skill_action_format.md}"
CONFIG="${CONFIG:-eval_configs/local_3tasks_skill_run.yaml}"
BASE_CONFIG="${BASE_CONFIG:-eval_configs/local_3tasks_run.yaml}"
TRACE="/logs/agentboard_${TAG}_llm_trace.jsonl"
RLOG="/logs/agentboard_${TAG}_run.log"

if [ ! -f "$ENVF" ]; then echo "[错误] 缺少 $ENVF"; exit 1; fi
set -a; . "$ENVF"; set +a
if [ -z "$BASE_URL" ]; then BASE_URL=$OPENAI_API_BASE; fi
if [ -z "$API_KEY" ]; then API_KEY=$OPENAI_API_KEY; fi
if [ -z "$MODEL" ] || [ -z "$API_KEY" ]; then echo "[错误] .env.local 缺 MODEL / API_KEY"; exit 1; fi

echo "模型:      $MODEL ($BASE_URL)"
echo "任务:      $TASKS"
echo "步数/局数: max_num_steps=$STEPS  episodes=${EPISODES:-（沿用现有配置）}"
echo "skill:     $SKILL"
echo "结果/留痕: $RESULTS / $TRACE"

# 1) 若指定 EPISODES，先重生成基础配置（含 scienceworld/babyai 子集与 num_exam）
if [ -n "$EPISODES" ]; then
  GEN="--model $MODEL --out $BASE_CONFIG --episodes $EPISODES --base-url $BASE_URL"
  if [ -n "$MAX_TOKENS" ]; then GEN="$GEN --max-tokens $MAX_TOKENS"; fi
  if [ -n "$TEMPERATURE" ]; then GEN="$GEN --temperature $TEMPERATURE"; fi
  if [ -n "$REASONING_EFFORT" ]; then GEN="$GEN --reasoning-effort $REASONING_EFFORT"; 
  elif [ -n "$REASONING" ]; then GEN="$GEN --reasoning $REASONING"; fi
  python3 "$AB/scripts/make_run_config.py" $GEN
fi

# 2) 注入 skill -> prompt JSON；3) 由基础配置派生运行配置（含 trace_path）
SKILL_ENV="${SKILL_ENV:-alfworld}"
case "$SKILL_ENV" in
  alfworld)     SRC=alfworld_base.json;         DST=alfworld_base_skill.json ;;
  scienceworld) SRC=scienceworld_base.json;     DST=scienceworld_base_skill.json ;;
  babyai)       SRC=babyai_vanilla_prompt.json; DST=babyai_vanilla_prompt_skill.json ;;
  *) echo "[错误] 未知 SKILL_ENV=$SKILL_ENV（可选 alfworld|scienceworld|babyai）"; exit 1 ;;
esac
echo "注入到:    $SKILL_ENV ($SRC -> $DST)"
if [ "${NO_SKILL:-0}" = "1" ]; then
  python3 "$AB/scripts/make_skill_run_config.py" --no-skill \
    --base "$ABD/$BASE_CONFIG" --out "$ABD/$CONFIG" --trace "$TRACE"
else
  python3 "$AB/scripts/apply_skill.py" --skill "$SKILL" \
    --prompt "$ABD/agentboard/prompts/VanillaAgent/$SRC" \
    --out "$ABD/agentboard/prompts/VanillaAgent/$DST"
  python3 "$AB/scripts/make_skill_run_config.py" --env "$SKILL_ENV" \
    --base "$ABD/$BASE_CONFIG" --out "$ABD/$CONFIG" --trace "$TRACE"
fi

echo "--- 生效的生成参数 ---"
grep -E "engine:|max_tokens:|temperature:|enabled:|num_exam:" "$ABD/$CONFIG" | head -8

# 4) 独立容器
docker rm -f "$CNAME" >/dev/null 2>&1 || true
docker run --rm -v "$ABD":/abd "$IMG" bash -lc "rm -rf /abd/$RESULTS"
docker run --rm -v "$AB/logs":/logs "$IMG" bash -lc "rm -f /logs/agentboard_${TAG}_* ; touch $TRACE"
docker run -d --name "$CNAME" --network host \
  -v "$ABD":/root/agentboard \
  -v "$AB/logs":/logs \
  -w /root/agentboard \
  -e PROJECT_PATH=/root/agentboard \
  -e PYTHONPATH=/root/agentboard/agentboard \
  -e OPENAI_API_KEY="$API_KEY" \
  -e OPENAI_API_BASE="$BASE_URL" \
  -e AB_LLM_TRACE="$TRACE" \
  "$IMG" bash -lc "source /root/miniconda3/etc/profile.d/conda.sh && conda activate agentboard && python -u agentboard/eval_main.py --cfg-path $CONFIG --tasks $TASKS --model $MODELKEY --max_num_steps $STEPS --log_path /root/agentboard/$RESULTS 2>&1 | tee $RLOG; echo EXIT=\$?; sleep infinity"

# 5) 注入自检
for i in $(seq 1 80); do
  sleep 5
  if [ -s "$AB/logs/agentboard_${TAG}_llm_trace.jsonl" ]; then break; fi
done
AB_EXPECT_NO_SKILL="${NO_SKILL:-0}" python3 - "$AB/logs/agentboard_${TAG}_llm_trace.jsonl" <<'PYEOF'
import json, os, sys
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
if not rows:
    print("[warn] trace 还没有内容（首局还在跑），跳过注入自检")
    sys.exit(0)
hit = False
for r in rows:
    for m in r.get("messages", []):
        if m.get("role") == "system" and "## Skill Knowledge" in (m.get("content") or ""):
            hit = True
no_skill = os.environ.get("AB_EXPECT_NO_SKILL", "0") == "1"
if no_skill:
    if hit:
        sys.exit("[错误] 对照臂竟然注入了 skill：%s" % sys.argv[1])
    print("[ok] 对照臂：确认未注入 skill（抽查 %d 轮）" % len(rows))
elif not hit:
    sys.exit("[错误] trace 里没有注入的 skill：%s" % sys.argv[1])
first = rows[0]
req = first["request"]
think = (req.get("thinking") or {}).get("type")
reason = (req.get("reasoning") or {}).get("enabled")
if think == "disabled" or reason is False:
    state = "disabled（显式关闭）"
elif think == "enabled" or reason is True:
    state = "enabled（显式开启）"
else:
    state = "默认（未指定思考字段，与先前测试一致）"
print("[ok] skill 已注入（抽查 %d 轮）；首轮请求: max_tokens=%s temperature=%s thinking=%s" % (
    len(rows), req.get("max_tokens"), req.get("temperature"), state))
PYEOF

echo "容器: $(docker ps --filter name=$CNAME --format '{{.Names}} | {{.Status}}')"
echo "看进度: tail -f $AB/logs/agentboard_${TAG}_run.log"
