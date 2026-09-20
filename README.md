# ScienceWorld 三臂对比：手写 prompt / 注入 skill / 无 skill 对照

AgentBoard 上的 ScienceWorld 评测复现包。同一批 30 局标签、同一个模型与采样参数，
只改变注入到 system prompt 的 skill 内容，比较三种设置：

| 臂 | 设置 | 一句话说明 |
| --- | --- | --- |
| **arm1 prompt-v1** | 手写 skill prompt | 人工撰写的实验规则文档，**整份替换** system prompt（v1 快照） |
| **arm2 OLD 注入 skill** | SkillOpt 训练产物 | 训练得到的 skill 文档，经 `apply_skill.py` 追加到基础 prompt 的 `## Skill Knowledge` 段 |
| **arm3 CTRL** | 无 skill | 使用 AgentBoard 原始基础 prompt，不注入任何 skill |

- 模型：`deepseek-flash`（`https://api.deepseek.com`，OpenAI 兼容通道）
- 镜像：`zzh202121/agentboard:0117`（conda env `agentboard`，py4j ScienceWorld）
- 规模：ScienceWorld `test_smoke.jsonl` 30 局，`max_num_steps=30`，`seed=0`
- 采样：`temperature=0.7, top_p=1, max_tokens=3000, stop="\n"`

## 1. 结果（ScienceWorld，30 局）

| 臂 | success | progress | grounding | easy / hard success | 平均步数 | LLM 轮数 | 空回复（token 截断） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| arm1 prompt-v1 | **0.767** (23/30) | 0.951 | 0.340 | 1.00 / 0.667 | 14.4 | 474 | 43（9%） |
| arm2 OLD 注入 skill | 0.667 (20/30) | 0.920 | 0.290 | 0.889 / 0.571 | 16.1 | 539 | 57（11%） |
| arm3 CTRL（无 skill） | 0.600 (18/30) | 0.883 | 0.275 | 0.778 / 0.524 | 14.6 | 555 | 118（21%） |

原始指标文件见 `results/*_all_results.txt`（AgentBoard 官方 `all_results.txt` 逐字拷贝）。
逐局明细与完整轨迹见 `reports/`（渲染产物），其输入为 `runs/` 下的运行日志与 LLM 留痕。

## 2. 目录

```
upload/
├── README.md
├── configs/
│   ├── arm1_prompt_v1_sci_manual30.yaml     # arm1 运行配置（init_prompt_path -> 手写 prompt）
│   ├── arm2_old_skill_sci_skill30.yaml      # arm2 运行配置（-> scienceworld_base_skill.json）
│   └── arm3_ctrl_no_skill_3tasks.yaml       # arm3 运行配置（scienceworld 用基础 prompt）
├── prompts/
│   ├── scienceworld_base.json               # AgentBoard 原始基础 prompt（system_msg 108 字符）
│   ├── scienceworld_base_manual_v1.json     # arm1 用的手写 prompt v1（system_msg 4950 字符）
│   └── scienceworld_base_skill.json         # arm2 实际注入后的 prompt（system_msg 3664 字符）
├── skills/
│   └── sci_r3_best_skill.md                 # arm2 注入的 skill 原文（SkillOpt sci_r3 产物）
├── scripts/
│   ├── run_sci_manual30.sh                  # arm1 运行脚本（docker 起容器跑 eval_main.py）
│   ├── run_agentboard_skill_eval.sh         # arm2/arm3 通用运行脚本（环境变量选择臂）
│   ├── run_stage5_evals.sh                  # 四臂批量驱动（arm2 = 臂 1/4）
│   ├── apply_skill.py                       # skill md -> prompt JSON 的 system_msg 注入器
│   ├── make_skill_run_config.py             # 由基础配置派生「注入 skill / 无 skill」运行配置
│   ├── make_run_config.py                   # 按 .env.local 注入模型与采样参数
│   ├── render_3tasks_report.py              # 由 all_results + 留痕 + 运行日志渲染报告
│   └── report_sci_manual30.py               # 三臂/五口径对比汇总脚本
├── results/                                  # 官方指标（all_results.txt 逐字拷贝）
│   ├── arm1_sci_manual30_all_results.txt
│   ├── arm2_sci_skill30_all_results.txt
│   └── arm3_ctrl_skill_eval_30_all_results.txt
├── runs/                                     # 渲染输入
│   ├── arm1_sci_manual30_run.log             # 运行日志（--runlog），报告里"运行窗口"的来源
│   ├── arm1_sci_manual30_llm_trace.jsonl     # 每轮完整请求/回复留痕（--llm），474 轮
│   ├── arm2_sci_skill_run.log
│   ├── arm2_sci_skill_llm_trace.jsonl        # 539 轮
│   ├── arm3_skill30_run.log
│   └── arm3_skill30_llm_trace.jsonl          # 1125 轮（含 alfworld/babyai）
├── reports/                                  # 渲染产物（重渲染命令见第 3 节末）
│   ├── arm1_prompt_v1_sci_manual30_report.md # 6.5 MB，含折叠的逐局思维链
│   ├── arm2_old_skill_sci_skill30_report.md  # 5.9 MB
│   └── arm3_ctrl_no_skill_3tasks_report.md   # 8.8 MB（含 alfworld/babyai）
└── data/
    └── scienceworld_test_smoke.jsonl         # 本仓库实际使用的 30 局标签（见第 5 节）
```

## 3. 复现

前置：把 `AgentBoard/`（上游 checkout，版本 `bb7255e`）与 `local/` 目录按原仓库布局放好，
并在 `local/.env.local` 里提供 `MODEL / BASE_URL / API_KEY / MAX_TOKENS / TEMPERATURE`
（脚本会把它们注入运行配置；密钥不入库）。

```bash
# arm1：手写 prompt
bash local/scripts/run_sci_manual30.sh

# arm2：注入 SkillOpt skill（scienceworld，30 局）
SKILL_ENV=scienceworld TASKS=scienceworld RESULTS=results/sci_skill30 TAG=sci_skill \
  CONFIG=eval_configs/local_3tasks_sci_skill_run.yaml EPISODES=scienceworld=30 \
  SKILL=local/runs/skillopt/sci_r3/best_skill.md \
  bash local/scripts/run_agentboard_skill_eval.sh 30

# arm3：无 skill 对照（三任务同跑，这里只取 scienceworld 那一份）
NO_SKILL=1 TASKS="alfworld scienceworld babyai" RESULTS=results/skill_eval_30 TAG=skill30 \
  EPISODES="alfworld=30,scienceworld=30,babyai=30" \
  bash local/scripts/run_agentboard_skill_eval.sh 30

# 渲染报告（可选）
python3 local/scripts/render_3tasks_report.py --results AgentBoard/results/sci_manual30 \
  --llm local/logs/agentboard_sci_manual30_llm_trace.jsonl \
  --runlog local/logs/agentboard_sci_manual30_run.log --tasks scienceworld \
  --config AgentBoard/eval_configs/local_sci_manual30.yaml --out report.md
```

脚本里的路径沿用原工作区布局（`local/scripts/...`、`AgentBoard/eval_configs/...`），
换目录时需相应调整；运行容器为 `--network host`，挂载 `AgentBoard/ -> /root/agentboard`、
`local/logs -> /logs`。

## 4. prompt 注入方式

- arm1：整份手写 prompt（`prompts/scienceworld_base_manual_v1.json`）直接作为 `init_prompt_path`，
  不经过注入脚本。
- arm2：`apply_skill.py` 把 `skills/sci_r3_best_skill.md` 追加到基础 prompt 末尾，包装文本固定为：

  ```
  ## Skill Knowledge
  Below is a skill document with learned strategies. Use these guidelines to inform your decisions:
  <skill 原文>
  ```

  生成物即 `prompts/scienceworld_base_skill.json`（已在留痕里逐字核对一致）。
- arm3：`init_prompt_path` 保持 `scienceworld_base.json`，即无 skill。

## 5. 注意事项

1. **三臂并非逐字同条件**：
   - 上游原版Science word经过编辑，差异仅 2 局：
     id=17 的子目标 `",You move to the living room"` 删除了开头的逗号；id=18 的 goal 末句笔误
     `water` 改为 `orange juice`。
     本包 `data/` 里放的是当前使用版本（`54dcc7c4`）。
2. **空回复（token 截断）是主要噪声源**：`max_tokens=3000` 被思维链占满时该轮无动作，
   但步数照样消耗（arm3 高达 21%）。比较三臂时需要同时看轮数/空回复列。
  
