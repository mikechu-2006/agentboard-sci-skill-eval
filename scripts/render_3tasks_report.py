#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 AgentBoard 三任务运行日志渲染成一份 Markdown 报告：
开头是「测试参数 metadata + 指标」，正文是默认折叠的交互细节（思维链 / 模型原始输出 / 完整 prompt / 环境 observation）。

用法:
    python3 local/scripts/render_3tasks_report.py                 # 自动发现默认路径
    python3 local/scripts/render_3tasks_report.py --results AgentBoard/results/3tasks \\
            --llm local/logs/agentboard_3tasks_llm_trace.jsonl \\
            --out local/logs/agentboard_3tasks_report.md

设计要点:
- 只用标准库；运行中（数据不全）或运行结束后都能用，缺什么就跳过并注明
- 指标优先取官方 all_results.txt；缺的用 logs/<task>.jsonl 现场计算（并标明来源）
- 轮次对齐: 只有「调用异常」(error) 不占轮次（AgentBoard 会重试）；**空回复（finish_reason=length，thinking 吃满 max_tokens）仍占一轮**
  —— 它被当成空动作执行掉了，若从对齐序列里剔除，其后所有轮次的"留痕第 N 次调用"和"模型原始输出"都会错位；
  每轮标注 内容一致 / 顺序对齐 / 空回复 / 无留痕
- 不读取也不输出 API key（只记录 BASE_URL）
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess

BT = chr(96)
HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.dirname(HERE)
ABD = os.environ.get("AGENTBOARD_DIR") or os.path.join(os.path.dirname(LOCAL), "AgentBoard")
DEFAULT_TASKS = ["alfworld", "scienceworld", "babyai"]
TASK_LABEL = {"alfworld": "AlfWorld", "scienceworld": "ScienceWorld", "babyai": "BabyAI"}
PROJECT_PH = "$" + "{PROJECT_PATH}"


def code(s):
    return BT + str(s) + BT


def read_text(path):
    if not path or not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def load_json_stream(path):
    rows = []
    text = read_text(path)
    if not text.strip():
        return rows
    dec = json.JSONDecoder()
    i = 0
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        if i >= len(text):
            break
        try:
            obj, end = dec.raw_decode(text, i)
        except Exception:
            nl = text.find(chr(10), i)
            if nl < 0:
                break
            i = nl + 1
            continue
        rows.append(obj)
        i = end
    return rows


def clip(text, n):
    text = "" if text is None else str(text)
    if len(text) <= n:
        return text
    return text[:n] + chr(10) + "...[truncated %d chars]" % (len(text) - n)


def details(lines, summary, body, limit=20000):
    if body is None or str(body).strip() == "":
        return
    lines.append("<details><summary>%s</summary>" % summary)
    lines.append("")
    lines.append("~~~")
    lines.append(clip(body, limit))
    lines.append("~~~")
    lines.append("")
    lines.append("</details>")
    lines.append("")


def turns_of(traj):
    if not traj:
        return []
    if isinstance(traj, dict):
        def key(name):
            tail = str(name).split()[-1]
            return int(tail) if tail.isdigit() else 0
        items = [traj[k] for k in sorted(traj.keys(), key=key)]
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            out.append({"action": it.get("Action"), "observation": it.get("Observation"),
                        "progress": it.get("Progress Rate"), "goal": it.get("Goal")})
        return out
    groups, order = {}, []
    for idx, it in enumerate(traj):
        if not isinstance(it, dict):
            continue
        k = it.get("id", idx)
        if k not in groups:
            groups[k] = {"action": None, "observation": None, "progress": None, "goal": None}
            order.append(k)
        for src, dst in (("Action", "action"), ("Observation", "observation"),
                         ("Progress Rate", "progress"), ("Goal", "goal")):
            if src in it and groups[k][dst] is None:
                groups[k][dst] = it[src]
    return [groups[k] for k in order]


def norm_action(text, task):
    s = (text or "").strip()
    if "action" in s.lower():
        for line in s.split(chr(10)):
            if "action" in line.lower() and ":" in line:
                s = line.split(":", 1)[1]
                break
    s = s.strip().strip("'/").split(chr(10))[0].strip()
    if task == "alfworld":
        if " in " in s:
            s = s.replace(" in ", " in/on ")
        elif " on " in s:
            s = s.replace(" on ", " in/on ")
        if s.endswith("."):
            s = s[:-1].strip()
    return s.lower()


def parse_env_file(path):
    base = ""
    for line in read_text(path).splitlines():
        line = line.split("#")[0].strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() in ("BASE_URL", "OPENAI_API_BASE"):
            base = v.strip().strip('"').strip("'")
    return base


def load_config(path):
    txt = read_text(path)
    cfg = {"_path": path}

    def grab(pattern, default=None):
        m = re.search(pattern, txt, re.M)
        return m.group(1).strip() if m else default

    cfg["max_num_steps"] = grab(r"^\s{2}max_num_steps:\s*(\S+)")
    cfg["num_exam"] = grab(r"^\s{2}num_exam:\s*(\S+)")
    cfg["engine"] = grab(r"^\s{4}engine:\s*(\S+)")
    cfg["max_tokens"] = grab(r"^\s{4}max_tokens:\s*(\S+)")
    cfg["temperature"] = grab(r"^\s{4}temperature:\s*(\S+)")
    cfg["top_p"] = grab(r"^\s{4}top_p:\s*(\S+)")
    cfg["stop"] = grab(r"^\s{4}stop:\s*(\S+)")
    cfg["retry_delays"] = grab(r"^\s{4}retry_delays:\s*(\S+)")
    cfg["reasoning"] = grab(r"^\s{8}enabled:\s*(\S+)")
    cfg["trace_path"] = grab(r"^\s{4}trace_path:\s*(\S+)")
    cfg["label_paths"] = {}
    for task in DEFAULT_TASKS:
        m = re.search(r"^\s{2}%s:\n(.*?)(?=^\s{2}\S|\Z)" % task, txt, re.M | re.S)
        if m:
            lm = re.search(r"label_path:\s*(\S+)", m.group(1))
            if lm:
                cfg["label_paths"][task] = lm.group(1).replace(PROJECT_PH, ABD)
    return cfg


def file_fingerprint(path):
    if not path or not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    with open(path, "rb") as f:
        n = sum(1 for _ in f)
    return {"lines": n, "bytes": os.path.getsize(path), "sha256_8": h.hexdigest()[:8]}


def docker_image_id(image):
    try:
        out = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                             capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            return out.stdout.strip()[:19]
    except Exception:
        pass
    return ""


def git_commit(repo):
    try:
        out = subprocess.run(["git", "-C", repo, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def fmt_ts(ts):
    try:
        return dt.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def human(sec):
    sec = float(sec or 0)
    if sec < 60:
        return "%.1f 秒" % sec
    if sec < 3600:
        return "%.1f 分钟" % (sec / 60.0)
    return "%.2f 小时" % (sec / 3600.0)


def pct(x, total):
    return "%.0f%%" % (100.0 * x / total) if total else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(ABD, "results", "3tasks"))
    ap.add_argument("--llm", default=os.path.join(LOCAL, "logs", "agentboard_3tasks_llm_trace.jsonl"))
    ap.add_argument("--runlog", default=os.path.join(LOCAL, "logs", "agentboard_3tasks_run.log"))
    ap.add_argument("--config", default=None)
    ap.add_argument("--env", default=os.path.join(LOCAL, ".env.local"))
    ap.add_argument("--image", default="zzh202121/agentboard:0117")
    ap.add_argument("--tasks", default=",".join(DEFAULT_TASKS))
    ap.add_argument("--out", default=os.path.join(LOCAL, "logs", "agentboard_3tasks_report.md"))
    ap.add_argument("--prompt-limit", type=int, default=20000)
    args = ap.parse_args()
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]

    cfg_path = args.config
    if not cfg_path:
        for cand in ("local_3tasks_run.yaml", "local_3tasks.yaml"):
            p = os.path.join(ABD, "eval_configs", cand)
            if os.path.exists(p):
                cfg_path = p
                break
    cfg = load_config(cfg_path)

    raw_llm = load_json_stream(args.llm)
    # 调用异常（error）会被 AgentBoard 重试，不占轮次；空回复（token 上限截断）会被当成空动作执行，**占一轮**。
    ok_llm = [r for r in raw_llm if not r.get("error")]
    err_llm = [r for r in raw_llm if r.get("error")]
    empty_idx = set(i for i, r in enumerate(ok_llm) if not (r.get("response") or "").strip())
    req0 = next((r.get("request") or {} for r in ok_llm), {})
    tok = {"prompt": 0, "completion": 0, "reasoning": 0}
    for r in ok_llm:
        u = r.get("usage") or {}
        tok["prompt"] += u.get("prompt_tokens") or 0
        tok["completion"] += u.get("completion_tokens") or 0
        tok["reasoning"] += ((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    tok_empty = {"completion": 0, "reasoning": 0}
    for i in empty_idx:
        u = ok_llm[i].get("usage") or {}
        tok_empty["completion"] += u.get("completion_tokens") or 0
        tok_empty["reasoning"] += ((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    ts_all = [r.get("ts") for r in raw_llm if r.get("ts")]
    wall = (max(ts_all) - min(ts_all)) if len(ts_all) >= 2 else 0

    runlog = read_text(args.runlog)
    rl_times = re.findall(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", runlog, re.M)
    rl_err = len(re.findall(r"^Error on attempt", runlog, re.M))
    rl_fail = len(re.findall(r"^Failed to get completion", runlog, re.M))

    official = {}
    for line in read_text(os.path.join(args.results, "all_results.txt")).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            official[d.get("task_name")] = d
        except Exception:
            pass

    data = {}
    for task in tasks:
        rows = load_json_stream(os.path.join(args.results, "logs", "%s.jsonl" % task))
        examples = []
        for row in rows:
            turns = turns_of(row.get("trajectory"))
            examples.append({"row": row, "turns": turns,
                             "steps": sum(1 for t in turns if t.get("action"))})
        data[task] = examples

    total_turns = sum(len(e["turns"]) for task in tasks for e in (data.get(task) or []))
    produced = [t for t in tasks if (data.get(t) or [])]
    if len(official) >= len(tasks) and total_turns == len(ok_llm):
        status = "已完成（%d 个任务的官方指标均已落盘，轮次对齐一致）" % len(produced)
    elif produced:
        status = "运行中 / 数据不完整（已产生: %s；轮次对齐 %d↔%d）" % (
            ", ".join(TASK_LABEL.get(t, t) for t in produced), total_turns, len(ok_llm))
    else:
        status = "无数据"

    L = []
    L.append("# AgentBoard 三任务评测报告")
    L.append("")
    L.append("> 交互细节默认折叠（点击 <summary> 展开）；由 " + code("local/scripts/render_3tasks_report.py") + " 生成。")
    L.append("")

    L.append("## 1. 测试参数（metadata）")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("| --- | --- |")
    L.append("| 生成时间 | %s |" % dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    L.append("| 运行状态 | %s |" % status)
    if rl_times:
        t0 = dt.datetime.strptime(rl_times[0], "%Y-%m-%d %H:%M:%S")
        t1 = dt.datetime.strptime(rl_times[-1], "%Y-%m-%d %H:%M:%S")
        L.append("| 运行窗口（run log） | %s → %s（%s） |" % (rl_times[0], rl_times[-1], human((t1 - t0).total_seconds())))
    elif ts_all:
        L.append("| 运行窗口（LLM 留痕） | %s → %s（%s） |" % (fmt_ts(min(ts_all)), fmt_ts(max(ts_all)), human(wall)))
    L.append("| 任务顺序 | %s |" % ", ".join(TASK_LABEL.get(t, t) for t in tasks))
    L.append("| 每局步数上限 max_num_steps | %s |" % (cfg.get("max_num_steps") or "-"))
    L.append("| alfworld 局数上限 num_exam | %s |" % (cfg.get("num_exam") or "-"))
    L.append("| 模型 engine | %s |" % (req0.get("model") or cfg.get("engine") or "-"))
    L.append("| 接口 BASE_URL | %s |" % (parse_env_file(args.env) or "-"))
    L.append("| 采样参数（留痕实测） | temperature=%s, top_p=%s, max_tokens=%s, stop=%s |" % (
        req0.get("temperature", cfg.get("temperature", "-")), req0.get("top_p", cfg.get("top_p", "-")),
        req0.get("max_tokens", cfg.get("max_tokens", "-")), json.dumps(req0.get("stop", cfg.get("stop")), ensure_ascii=False)))
    L.append("| 思维链 reasoning | %s |" % (cfg.get("reasoning") or "-"))
    L.append("| 配置来源 | %s |" % (os.path.relpath(cfg_path, os.path.dirname(ABD)) if cfg_path else "-"))
    L.append("| LLM 留痕 | %s |" % os.path.relpath(args.llm, os.path.dirname(ABD)))
    L.append("| 结果目录 | %s |" % os.path.relpath(args.results, os.path.dirname(ABD)))
    img_id = docker_image_id(args.image)
    L.append("| 镜像 | %s%s |" % (args.image, ("（" + img_id + "）") if img_id else ""))
    commit = git_commit(ABD)
    if commit:
        L.append("| AgentBoard 代码版本 | %s |" % code(commit))
    for task in tasks:
        lp = (cfg.get("label_paths") or {}).get(task)
        fp = file_fingerprint(lp) if lp else None
        if fp:
            L.append("| %s 标注文件 | %s（%d 行, %d 字节, sha256:%s） |" % (
                TASK_LABEL.get(task, task), os.path.relpath(lp, os.path.dirname(ABD)),
                fp["lines"], fp["bytes"], fp["sha256_8"]))
    L.append("")

    L.append("## 2. 指标")
    L.append("")
    L.append("### 2.1 分任务汇总")
    L.append("")
    L.append("| 任务 | 局数 | success | progress | grounding | easy/hard | 平均步数 | 中位步数 | 撞上限局数 | 来源 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    max_steps = int(cfg.get("max_num_steps") or 0)
    for task in tasks:
        ex = data.get(task) or []
        off = official.get(task)
        if off:
            sr, pr, ga = off.get("success_rate"), off.get("progress_rate"), off.get("grounding_acc")
            eh = "%.2f / %.2f" % (off.get("success_rate_easy") or 0, off.get("success_rate_hard") or 0)
            src = "all_results.txt"
        elif ex:
            n = len(ex)
            sr = sum(1 for e in ex if e["row"].get("is_done")) * 1.0 / n
            pr = sum(float(e["row"].get("progress_rate") or 0) for e in ex) / n
            ga = sum(float(e["row"].get("grounding_acc") or 0) for e in ex) / n
            easy = [e for e in ex if e["row"].get("difficulty") == "easy"]
            hard = [e for e in ex if e["row"].get("difficulty") == "hard"]
            eh = "%.2f / %.2f" % (
                (sum(1 for e in easy if e["row"].get("is_done")) / len(easy)) if easy else 0,
                (sum(1 for e in hard if e["row"].get("is_done")) / len(hard)) if hard else 0)
            src = "现场计算"
        else:
            L.append("| %s | 0 | - | - | - | - | - | - | - | 无数据 |" % TASK_LABEL.get(task, task))
            continue
        steps = sorted(e["steps"] for e in ex) if ex else []
        avg = ("%.1f" % (sum(steps) / len(steps))) if steps else "-"
        med = ("%d" % steps[len(steps) // 2]) if steps else "-"
        cap = sum(1 for s in steps if max_steps and s >= max_steps) if steps else 0
        L.append("| %s | %d | %.3f | %.3f | %.3f | %s | %s | %s | %d | %s |" % (
            TASK_LABEL.get(task, task), len(ex), sr or 0, pr or 0, ga or 0, eh, avg, med, cap, src))
    L.append("")
    L.append("### 2.2 LLM 用量与健康度")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("| --- | --- |")
    L.append("| LLM 调用总数 | %d（调用异常(重试) %d；空回复(token 上限截断，仍占轮次) %d，占比 %s） |" % (
        len(raw_llm), len(err_llm), len(empty_idx), pct(len(empty_idx), len(raw_llm))))
    L.append("| token 用量 | prompt %d + completion %d（其中 reasoning %d） |" % (tok["prompt"], tok["completion"], tok["reasoning"]))
    if empty_idx:
        L.append("| 空回复轮 token | completion %d（其中 reasoning %d）——全部被浪费 |" % (
            tok_empty["completion"], tok_empty["reasoning"]))
    L.append("| 平均每轮耗时 | %s |" % human(sum(float(r.get("elapsed") or 0) for r in ok_llm) / max(1, len(ok_llm))))
    L.append("| 轮次对齐 | 留痕(非异常) %d 条 ↔ %d 轮交互%s |" % (
        len(ok_llm), total_turns, "" if len(ok_llm) == total_turns else "（不一致：部分轮次无留痕）"))
    if rl_err or rl_fail:
        L.append("| run log 中的失败 | Error on attempt %d 次；中途放弃（Failed to get completion）%d 次 |" % (rl_err, rl_fail))
    L.append("")

    L.append("### 2.3 逐局明细")
    L.append("")
    for task in tasks:
        ex = data.get(task) or []
        if not ex:
            continue
        L.append("**%s**" % TASK_LABEL.get(task, task))
        L.append("")
        L.append("| # | difficulty | done | progress | grounding | steps | 备注 |")
        L.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i, e in enumerate(ex):
            row = e["row"]
            n_turns = len(e["turns"])
            n_empty = n_turns - e["steps"]
            note = ""
            if max_steps and n_turns >= max_steps:
                note = "轮数撞上限"
            if n_empty:
                note = (note + "；" if note else "") + "空动作 %d 次（token 上限截断）" % n_empty
            if not row.get("is_done") and n_turns == 0:
                note = "未能发出动作（LLM 失败？）"
            L.append("| %s | %s | %s | %.2f | %.2f | %d | %s |" % (
                row.get("id", i), row.get("difficulty", "-"), row.get("is_done"),
                float(row.get("progress_rate") or 0), float(row.get("grounding_acc") or 0), e["steps"], note))
        L.append("")

    L.append("## 3. 轨迹（默认折叠交互细节）")
    L.append("")
    ptr = 0
    for ti, task in enumerate(tasks):
        ex = data.get(task) or []
        if not ex:
            continue
        L.append("### 3.%d %s" % (ti + 1, TASK_LABEL.get(task, task)))
        L.append("")
        for i, e in enumerate(ex):
            row = e["row"]
            first = ok_llm[ptr] if ptr < len(ok_llm) else None
            L.append("#### %s Game %s | %s | done=%s | progress=%s | grounding=%s | steps=%d" % (
                TASK_LABEL.get(task, task), row.get("id", i), row.get("task_name") or (row.get("goal") or "")[:40],
                row.get("is_done"), round(float(row.get("progress_rate") or 0), 3),
                round(float(row.get("grounding_acc") or 0), 3), e["steps"]))
            L.append("")
            L.append("- **goal**: %s" % row.get("goal"))
            L.append("- **difficulty**: %s" % row.get("difficulty"))
            L.append("- **score_change_record**: %s" % row.get("score_change_record"))
            L.append("")
            if first:
                um = next((m.get("content") for m in (first.get("messages") or []) if m.get("role") == "user"), "")
                details(L, "首轮完整 prompt（= 注入记录：instruction + in-context 示例 + goal + 记忆）", um, args.prompt_limit)
            for k, turn in enumerate(e["turns"], 1):
                rec = ok_llm[ptr] if ptr < len(ok_llm) else None
                act = turn.get("action")
                L.append("##### TURN %d — 执行动作: %s" % (k, ("**" + str(act) + "**") if act else "（无）"))
                L.append("")
                if rec is not None:
                    resp_empty = not (rec.get("response") or "").strip()
                    same = (not resp_empty) and norm_action(rec.get("response"), task) == norm_action(act, task)
                    if resp_empty:
                        tag = "空回复（finish_reason=%s，thinking 吃满 max_tokens → 环境按空动作处理）" % (rec.get("finish_reason") or "?")
                    elif same:
                        tag = "内容一致"
                    else:
                        tag = "顺序对齐（解析器可能改写过输出）"
                    L.append("- 对齐: %s | 留痕第 %s 次调用" % (tag, rec.get("turn")))
                    L.append("")
                    details(L, "思维链 reasoning（模型内部思考，仅供分析）", rec.get("reasoning"))
                    details(L, "模型原始输出（解析前）", rec.get("response"))
                    um = next((m.get("content") for m in (rec.get("messages") or []) if m.get("role") == "user"), "")
                    details(L, "本轮完整 prompt（system + user）", um, args.prompt_limit)
                    ptr += 1
                else:
                    L.append("- 对齐: 无留痕（该轮没有对应的成功 LLM 调用）")
                    L.append("")
                details(L, "环境 observation（本轮动作执行后）", turn.get("observation"))
                if turn.get("progress") is not None:
                    details(L, "进度 / 状态", "progress(reward) = %s" % turn.get("progress"))
            L.append("---")
            L.append("")

    L.append("## 4. 对齐校验")
    L.append("")
    L.append("- 交互轮数（trajectory 里的 Action）: %d" % total_turns)
    L.append("- 留痕（非异常）调用: %d 条，其中空回复 %d 条（仍占轮次）；调用异常 %d 条已剔除" % (
        len(ok_llm), len(empty_idx), len(err_llm)))
    L.append("- 结论: %s" % ("轮数与留痕数一致 ✅" if total_turns == len(ok_llm) else "不一致（运行中或存在未记录轮次）"))
    L.append("")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(chr(10).join(L))
    print("已生成报告: %s" % args.out)
    print("  局数: %s | 轮数: %d | LLM 调用: %d 非异常（其中空回复 %d）/ %d 异常" % (
        {t: len(data.get(t) or []) for t in tasks}, total_turns, len(ok_llm), len(empty_idx), len(err_llm)))


if __name__ == "__main__":
    main()
