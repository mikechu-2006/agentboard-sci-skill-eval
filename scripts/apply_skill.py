#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 skill 文档注入 AgentBoard 的 prompt JSON（纯数据改动，不改任何 .py）。

注入位置 = prompt JSON 的 system_msg，且包装文本与训练侧
(local/skillopt_ext/envs/alfworld_bridge/rollout.py: skill_system_message) 完全一致——
这样"训练时看到的 skill"和"评测时注入的 skill"是同一份、同一个位置。

用法:
  python3 local/scripts/apply_skill.py \
      --skill local/skills/alfworld_gpt5.5_skill_action_format.md \
      --prompt AgentBoard/agentboard/prompts/VanillaAgent/alfworld_base.json \
      --out    AgentBoard/agentboard/prompts/VanillaAgent/alfworld_base_skill.json
"""
import argparse
import json
import os
import sys

WRAPPER = ("\n\n## Skill Knowledge\n"
           "Below is a skill document with learned strategies. "
           "Use these guidelines to inform your decisions:\n\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    for p in (a.skill, a.prompt):
        if not os.path.exists(p):
            sys.exit("找不到文件: %s" % p)

    skill = open(a.skill, encoding="utf-8").read().strip()
    data = json.load(open(a.prompt, encoding="utf-8"))
    base = (data.get("system_msg") or "You are a helpful assistant.").rstrip()
    data["system_msg"] = base + WRAPPER + skill + "\n"

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    written = json.load(open(a.out, encoding="utf-8"))
    assert written["system_msg"].count(skill) == 1, "skill 注入次数不为 1"
    assert written["examples"] == data["examples"], "examples 被意外改动"
    assert written["instruction"] == data["instruction"], "instruction 被意外改动"
    print("已注入: %s" % a.out)
    print("  skill      : %s (%d 字符)" % (a.skill, len(skill)))
    print("  system_msg : %d 字符 -> %d 字符" % (len(base), len(written["system_msg"])))
    print("  examples/instruction 未改动 OK")


if __name__ == "__main__":
    main()
