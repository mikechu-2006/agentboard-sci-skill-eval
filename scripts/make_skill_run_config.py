#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由控制组运行配置派生出「注入 skill」的运行配置：只改指定任务的 init_prompt_path。

用法:
  python3 local/scripts/make_skill_run_config.py --env alfworld \
      --base AgentBoard/eval_configs/local_3tasks_run.yaml \
      --out  AgentBoard/eval_configs/local_3tasks_skill_run.yaml

  # 指定任务（可多次 --env 以同时注入多个任务）
  python3 local/scripts/make_skill_run_config.py --env scienceworld --base ... --out ...
"""
import argparse
import os
import re
import sys

PREFIX = "$" + "{PROJECT_PATH}/agentboard/prompts/VanillaAgent/"
BASE_PROMPTS = {
    "alfworld": "alfworld_base.json",
    "scienceworld": "scienceworld_base.json",
    "babyai": "babyai_vanilla_prompt.json",
}
SKILL_PROMPTS = {
    "alfworld": "alfworld_base_skill.json",
    "scienceworld": "scienceworld_base_skill.json",
    "babyai": "babyai_vanilla_prompt_skill.json",
}


def inject(txt, env, prompt_path):
    old = PREFIX + BASE_PROMPTS[env]
    pat = re.compile(r"(init_prompt_path:\s*)" + re.escape(old) + r"(\s*\n)")
    txt, n = pat.subn(lambda m: m.group(1) + prompt_path + m.group(2), txt, count=1)
    if n != 1:
        sys.exit("未能在配置里定位 %s 的 init_prompt_path（%s）" % (env, old))
    base_name = BASE_PROMPTS[env]
    if txt.count(base_name.replace(".json", "")) != 1:
        sys.exit("%s 的 prompt 路径在配置里出现多次，可能误改了其他任务" % env)
    return txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--env", action="append", default=[], help="要注入的任务（可重复；默认 alfworld）")
    ap.add_argument("--no-skill", action="store_true",
                    help="对照臂：不注入任何 skill，只改 trace_path")
    ap.add_argument("--trace", default="/logs/agentboard_skill_llm_trace.jsonl")
    a = ap.parse_args()

    envs = a.env or ["alfworld"]
    for env in envs:
        if env not in BASE_PROMPTS:
            sys.exit("未知 env=%s（可选 %s）" % (env, "|".join(BASE_PROMPTS)))

    txt = open(a.base, encoding="utf-8").read()
    if a.no_skill:
        print("  [no-skill] 对照臂：不注入 skill，仅改 trace_path")
    else:
        for env in envs:
            prompt_path = PREFIX + SKILL_PROMPTS[env]
            txt = inject(txt, env, prompt_path)
            print("  %-13s init_prompt_path -> %s" % (env, SKILL_PROMPTS[env]))

    txt, n2 = re.subn(r"(trace_path:\s*)\S+", lambda m: m.group(1) + a.trace, txt, count=1)
    if n2 != 1:
        sys.exit("未能定位 trace_path")
    print("  trace_path -> %s" % a.trace)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(txt)
    print("已生成: %s" % a.out)


if __name__ == "__main__":
    main()
