#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由 local/.env.local 的 BASE_URL / MODEL / API_KEY 生成实际运行配置，并支持「每任务只跑前 x 局」。

一般由 scripts/run_agentboard_official.sh 自动调用；也可手动：
    python3 scripts/make_run_config.py --model nvidia/nemotron-3-super-120b-a12b:free
    python3 scripts/make_run_config.py --model gpt-4o-mini --episodes 8
    python3 scripts/make_run_config.py --model gpt-4o-mini --episodes "alfworld=4,scienceworld=8,babyai=12"

「前 x 局」三种机制（来自 AgentBoard 代码本身）:
    alfworld    : run.num_exam                                    （tasks/alfworld.py:217）
    scienceworld: evaluate() 遍历 label 文件全部条目、无上限参数  -> 生成子集 label 文件
    babyai      : 断言 len(game_level)*env_num_per_task == len(labels)（tasks/babyai.py:90）
                  -> 子集取前 K*4 行、game_level 取前 K 个 level（每 level 4 个 seed）
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))            # <local>/scripts
LOCAL = os.path.dirname(HERE)                                 # <local>
ABD = os.environ.get("AGENTBOARD_DIR") or os.path.join(os.path.dirname(LOCAL), "AgentBoard")
LEVELS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 24, 25, 27, 28, 29, 31, 32]
BABYAI_PER_LEVEL = 4


def parse_episodes(s):
    """'8' -> 三个任务各 8 局；'alfworld=4,scienceworld=8,babyai=12' -> 分别指定。"""
    if not s:
        return {}
    s = s.strip()
    if "=" not in s:
        n = int(s)
        return {"alfworld": n, "scienceworld": n, "babyai": n}
    out = {}
    for part in s.split(","):
        k, v = part.split("=")
        out[k.strip()] = int(v)
    return out


def head_jsonl(src, dst, n):
    rows = [l for l in open(src, encoding="utf-8") if l.strip()]
    with open(dst, "w", encoding="utf-8") as f:
        f.writelines(rows[:n])
    return min(n, len(rows))


def extra_body_block(provider, thinking, effort=None):
    """按接口厂商生成 extra_body：DeepSeek 认 thinking.type / reasoning_effort，OpenRouter 认 reasoning.enabled / reasoning.effort。"""
    if effort:
        if provider == "deepseek":
            return '    extra_body:\n      reasoning_effort: "%s"' % effort
        if provider == "openrouter":
            return '    extra_body:\n      reasoning:\n        effort: "%s"' % effort
        return None
    if thinking is None:
        return None
    if provider == "deepseek":
        return "    extra_body:\n      thinking:\n        type: %s" % ("enabled" if thinking == "true" else "disabled")
    if provider == "openrouter":
        return "    extra_body:\n      reasoning:\n        enabled: %s" % thinking
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="模型 ID（写进 llm 段的 engine）")
    ap.add_argument("--episodes", default=None, help="每任务前 x 局：8 或 alfworld=4,scienceworld=8,babyai=12")
    ap.add_argument("--max-tokens", default=None, help="覆盖 max_tokens")
    ap.add_argument("--temperature", default=None, help="覆盖 temperature")
    ap.add_argument("--thinking", "--reasoning", dest="thinking", default=None, choices=["true", "false"],
                    help="是否开启思考模式（按 --base-url 自动写成 DeepSeek thinking.type / OpenRouter reasoning.enabled）")
    ap.add_argument("--base-url", default="", help="接口地址，用于识别厂商（含 deepseek / openrouter）")
    ap.add_argument("--reasoning-effort", default=None, choices=["none", "low", "high", "max"],
                    help="思考强度（DeepSeek: reasoning_effort / OpenRouter: reasoning.effort）；none 表示关闭")
    ap.add_argument("--extra-body", default=None, help="自定义 extra_body 的 JSON（优先级最高）")
    ap.add_argument("--dir", default=ABD, help="AgentBoard 目录")
    ap.add_argument("--template", default="eval_configs/local_3tasks.yaml", help="模板配置（相对 --dir）")
    ap.add_argument("--out", default="eval_configs/local_3tasks_run.yaml", help="生成的运行配置（相对 --dir）")
    a = ap.parse_args()

    def path(p):
        return p if os.path.isabs(p) else os.path.join(a.dir, p)

    tpl = path(a.template)
    if not os.path.exists(tpl):
        sys.exit("找不到模板 %s" % tpl)
    txt = open(tpl, encoding="utf-8").read()

    txt, n = re.subn(r"(\n    engine:\s*)\S+", lambda m: m.group(1) + a.model, txt, count=1)
    if n != 1:
        sys.exit("模板里没找到 engine 字段")
    if a.max_tokens:
        txt = re.sub(r"(\n    max_tokens:\s*)\S+", lambda m: m.group(1) + a.max_tokens, txt, count=1)
    if a.temperature:
        txt = re.sub(r"(\n    temperature:\s*)\S+", lambda m: m.group(1) + a.temperature, txt, count=1)
    provider = "deepseek" if "deepseek" in (a.base_url or "").lower() else (
        "openrouter" if "openrouter" in (a.base_url or "").lower() else "")
    if a.extra_body:
        block = "    extra_body:\n" + "".join(
            "      %s: %s\n" % (k, json.dumps(v, ensure_ascii=False)) for k, v in json.loads(a.extra_body).items())
        block = block.rstrip(chr(10))
    else:
        block = extra_body_block(provider, a.thinking, a.reasoning_effort)
    if block is not None:
        if "    extra_body: {}" in txt:
            txt = txt.replace("    extra_body: {}", block)
        else:
            txt = re.sub(r"\n    extra_body:\n(?:      .*\n)+", chr(10) + block + chr(10), txt, count=1)
    elif a.thinking is not None:
        print("  [警告] 无法从 BASE_URL 识别厂商，extra_body 保持模板原样；请用 --extra-body 手动指定")

    eps = parse_episodes(a.episodes)
    lines = []
    if eps:
        data = os.path.join(a.dir, "data")
        if "alfworld" in eps:
            txt = re.sub(r"(\n  num_exam:\s*)\d+", lambda m: m.group(1) + str(eps["alfworld"]), txt, count=1)
            lines.append("  alfworld    : num_exam = %d（label 文件不动）" % eps["alfworld"])
        if "scienceworld" in eps:
            cnt = head_jsonl(os.path.join(data, "scienceworld", "test.jsonl"),
                             os.path.join(data, "scienceworld", "test_smoke.jsonl"), eps["scienceworld"])
            txt = txt.replace("data/scienceworld/test.jsonl", "data/scienceworld/test_smoke.jsonl")
            lines.append("  scienceworld: test_smoke.jsonl = %d 行" % cnt)
        if "babyai" in eps:
            k = max(1, eps["babyai"] // BABYAI_PER_LEVEL)
            cnt = head_jsonl(os.path.join(data, "babyai", "test.jsonl"),
                             os.path.join(data, "babyai", "test_smoke.jsonl"), k * BABYAI_PER_LEVEL)
            txt = txt.replace("data/babyai/test.jsonl", "data/babyai/test_smoke.jsonl")
            txt = re.sub(r"(\n    game_level:\s*)\[[^\]]*\]",
                         lambda m: m.group(1) + "[" + ", ".join(str(x) for x in LEVELS[:k]) + "]", txt, count=1)
            lines.append("  babyai      : test_smoke.jsonl = %d 行（levels=%d × %d seeds）" % (cnt, k, BABYAI_PER_LEVEL))

    out = path(a.out)
    open(out, "w", encoding="utf-8").write(txt)
    print("已生成运行配置: %s" % os.path.relpath(out, a.dir))
    print("  engine      : %s" % a.model)
    for l in lines:
        print(l)
    if not eps:
        print("  episodes    : 全量（未指定前 x 局）")


if __name__ == "__main__":
    main()
