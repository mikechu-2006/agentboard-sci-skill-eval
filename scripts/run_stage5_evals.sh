#!/bin/bash
# 阶段 5：注入评测 4 个臂（scienceworld 有/无 skill、babyai 有/无 skill）
#   - 同一批次（sci 30 局 / baby 28 局）、同一模型、默认思考强度
#   - 每臂独立 RESULTS / TAG / TRACE / CONFIG，跑完自动渲染 .md
#   - 幂等：若该臂的 all_results.txt 已存在则跳过运行，只补渲染
set -e
cd /home/mikechu/Documents/Projects/2q
AB=$PWD/local
CNAME=ab-agentboard-skill

# ⚠️ 必须用 -x python：容器 PID 1 是 "bash -lc '... eval_main.py ...; sleep infinity'"，
#    它的 cmdline 里含 eval_main，用 pgrep -f 会永远匹配到自己。
wait_eval () {
  for i in $(seq 1 480); do
    if ! docker exec $CNAME pgrep -x python >/dev/null 2>&1; then
      echo "[arm 完成] $(date +%H:%M:%S)"; return 0
    fi
    sleep 30
  done
  echo "[warn] 等待超时（4 小时）"; return 1
}

render () {   # $1=results $2=trace $3=runlog $4=task $5=config $6=out
  python3 local/scripts/render_3tasks_report.py \
    --results "$1" --llm "$2" --runlog "$3" --tasks "$4" --config "$5" --out "$6" \
    && echo "[render ok] $6" || echo "[warn] 渲染失败: $1"
}

run_arm () {  # $1=名称 $2=results目录 $3=trace $4=runlog $5=task $6=config $7=out $8=环境变量串
  echo "===== $1 ====="
  if [ -s "$2/all_results.txt" ]; then   # -s：必须非空（abort 过的臂会留下 0 字节文件）
    echo "[skip] $2 已有结果，直接渲染"
  else
    env $8 bash local/scripts/run_agentboard_skill_eval.sh 30
    wait_eval
  fi
  render "$2" "$3" "$4" "$5" "$6" "$7"
}

run_arm "臂 1/4：scienceworld + skill" AgentBoard/results/sci_skill30 \
  "$AB/logs/agentboard_sci_skill_llm_trace.jsonl" "$AB/logs/agentboard_sci_skill_run.log" scienceworld \
  AgentBoard/eval_configs/local_3tasks_sci_skill_run.yaml "$AB/logs/agentboard_sci_skill_report.md" \
  "SKILL_ENV=scienceworld TASKS=scienceworld RESULTS=results/sci_skill30 TAG=sci_skill CONFIG=eval_configs/local_3tasks_sci_skill_run.yaml EPISODES=scienceworld=30 SKILL=$AB/runs/skillopt/sci_r3/best_skill.md"

run_arm "臂 2/4：scienceworld 对照（无 skill）" AgentBoard/results/sci_ctrl30 \
  "$AB/logs/agentboard_sci_ctrl_llm_trace.jsonl" "$AB/logs/agentboard_sci_ctrl_run.log" scienceworld \
  AgentBoard/eval_configs/local_3tasks_sci_ctrl_run.yaml "$AB/logs/agentboard_sci_ctrl_report.md" \
  "NO_SKILL=1 TASKS=scienceworld RESULTS=results/sci_ctrl30 TAG=sci_ctrl CONFIG=eval_configs/local_3tasks_sci_ctrl_run.yaml EPISODES=scienceworld=30"

run_arm "臂 3/4：babyai + skill" AgentBoard/results/baby_skill28 \
  "$AB/logs/agentboard_baby_skill_llm_trace.jsonl" "$AB/logs/agentboard_baby_skill_run.log" babyai \
  AgentBoard/eval_configs/local_3tasks_baby_skill_run.yaml "$AB/logs/agentboard_baby_skill_report.md" \
  "SKILL_ENV=babyai TASKS=babyai RESULTS=results/baby_skill28 TAG=baby_skill CONFIG=eval_configs/local_3tasks_baby_skill_run.yaml EPISODES=babyai=28 SKILL=$AB/runs/skillopt/babyai_r3/best_skill.md"

run_arm "臂 4/4：babyai 对照（无 skill）" AgentBoard/results/baby_ctrl28 \
  "$AB/logs/agentboard_baby_ctrl_llm_trace.jsonl" "$AB/logs/agentboard_baby_ctrl_run.log" babyai \
  AgentBoard/eval_configs/local_3tasks_baby_ctrl_run.yaml "$AB/logs/agentboard_baby_ctrl_report.md" \
  "NO_SKILL=1 TASKS=babyai RESULTS=results/baby_ctrl28 TAG=baby_ctrl CONFIG=eval_configs/local_3tasks_baby_ctrl_run.yaml EPISODES=babyai=28"

echo "===== 全部完成 $(date +%H:%M:%S) ====="
for t in sci_skill30 sci_ctrl30 baby_skill28 baby_ctrl28; do
  printf "%-14s " "$t"; head -1 AgentBoard/results/$t/all_results.txt 2>/dev/null
done
