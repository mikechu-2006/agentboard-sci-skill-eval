#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量对比（五口径）：ScienceWorld 30 局
   NEW3 = sci_manual30c（手改 prompt v2 + reasoning_effort=low + 截断提醒）
   NEW2 = sci_manual30b（手改 prompt v2）
   NEW1 = sci_manual30 （手改 prompt v1）
   OLD  = sci_skill30  （注入 skill，旧 prompt，默认思考强度）
   CTRL = skill_eval_30（无 skill，旧 prompt）
"""
import json, os, re

LABEL = 'AgentBoard/data/scienceworld/test_smoke.jsonl'
ARMS = [('NEW3 low+notice', 'AgentBoard/results/sci_manual30c/logs/scienceworld.jsonl', 'local/logs/agentboard_sci_manual30c_llm_trace.jsonl'),
        ('NEW2 prompt-v2',  'AgentBoard/results/sci_manual30b/logs/scienceworld.jsonl', 'local/logs/agentboard_sci_manual30b_llm_trace.jsonl'),
        ('NEW1 prompt-v1',  'AgentBoard/results/sci_manual30/logs/scienceworld.jsonl',  'local/logs/agentboard_sci_manual30_llm_trace.jsonl'),
        ('OLD  skill-old',  'AgentBoard/results/sci_skill30/logs/scienceworld.jsonl',   None),
        ('CTRL no-skill',   'AgentBoard/results/skill_eval_30/logs/scienceworld.jsonl', None)]

def load_jsonl(p):
    out = []
    if p and os.path.exists(p):
        for line in open(p, errors='replace'):
            line = line.strip()
            if line:
                try: out.append(json.loads(line))
                except Exception: pass
    return out

def load_pretty(p):
    objs = []
    if not os.path.exists(p): return objs
    txt = open(p, errors='replace').read(); dec = json.JSONDecoder(); i = 0
    while i < len(txt):
        while i < len(txt) and txt[i] in ' \n\t\r': i += 1
        if i >= len(txt): break
        try: obj, j = dec.raw_decode(txt, i)
        except Exception: break
        objs.append(obj); i = j
    return objs

def turns_of(o):
    traj = o.get('trajectory')
    traj = json.loads(traj) if isinstance(traj, str) else (traj or {})
    ks = sorted(traj.keys(), key=lambda s: int(re.search(r'(\d+)', s).group(1)) if re.search(r'(\d+)', s) else 0)
    return [((traj[k].get('Action') or '').strip(), (traj[k].get('Observation') or '').strip()) for k in ks]

labels = load_jsonl(LABEL)
data = [(n, load_pretty(p), t) for n, p, t in ARMS]

print('=' * 92)
print('A) 汇总')
print('=' * 92)
for name, rows, _ in data:
    if not rows:
        print('  %-16s （无数据）' % name); continue
    n = len(rows)
    sr = sum(1 for o in rows if str(o.get('is_done')).lower() == 'true') / n
    pr = sum(float(o.get('progress_rate') or 0) for o in rows) / n
    gr = sum(float(o.get('grounding_acc') or 0) for o in rows) / n
    empty = sum(1 for o in rows for a, _ in turns_of(o) if not a)
    print('  %-16s n=%d SR=%.3f PR=%.3f ground=%.3f 轮数=%-4d 空动作=%-3d (%.1f%%)' % (
        name, n, sr, pr, gr, sum(len(turns_of(o)) for o in rows), empty,
        100.0 * empty / max(1, sum(len(turns_of(o)) for o in rows))))

print()
print('=' * 92)
print('B) 逐局（T/F + progress），Δ = NEW2 -> NEW3')
print('=' * 92)
maps = [(n, {str(o.get('id', i)): o for i, o in enumerate(rows)}) for n, rows, _ in data if rows]
hdr = '  id | %-32s |' % 'task'
for n, _ in maps: hdr += ' %-11s |' % n.split()[0]
hdr += ' Δ(v2→v3)'
print(hdr)
def cell(o):
    return '    -      ' if not o else '%s/%.2f' % ('T' if str(o.get('is_done')).lower() == 'true' else 'F', float(o.get('progress_rate') or 0))
ids = sorted({i for _, m in maps for i in m}, key=lambda x: int(x) if x.isdigit() else 0)
for i in ids:
    task = ''
    for _, m in maps:
        if i in m: task = m[i].get('task_name') or ''; break
    line = '  %3s | %-32s |' % (i, str(task)[:32])
    for _, m in maps: line += ' %-11s |' % cell(m.get(i))
    if '8   ' in '' : pass
    o2 = maps[1][1].get(i) if len(maps) > 1 else None
    o3 = maps[0][1].get(i)
    if o2 and o3:
        d = float(o3.get('progress_rate') or 0) - float(o2.get('progress_rate') or 0)
        line += (' %+.2f' % d) if abs(d) > 1e-9 else '  ='
    print(line)

print()
print('=' * 92)
print('C) NEW3 失败局诊断')
print('=' * 92)
new3 = data[0][1]
for i, o in enumerate(new3):
    if str(o.get('is_done')).lower() == 'true': continue
    subs = labels[i]['subgoals'] if i < len(labels) else []
    obs = [ob for _, ob in turns_of(o)]
    matched = [False] * len(subs)
    for ob in obs:
        for k, pat in enumerate(subs):
            try:
                if re.search(pat, ob): matched[k] = True
            except Exception: pass
    miss = [subs[k] for k in range(len(subs)) if not matched[k]]
    ne = sum(1 for a, _ in turns_of(o) if not a)
    print('  id=%-2d %-32s prog=%.2f 空动作=%-2d 缺: %s' % (i, str(o.get('task_name'))[:32], float(o.get('progress_rate') or 0), ne, miss))

print()
print('=' * 92)
print('D) 机制 / 截断统计')
print('=' * 92)
for name, rows, trace in data:
    if not rows: continue
    turns = sum(len(turns_of(o)) for o in rows)
    empty = sum(1 for o in rows for a, _ in turns_of(o) if not a)
    recs = load_jsonl(trace) if trace else []
    ok = [r for r in recs if not r.get('error')]
    rt = [((r.get('usage') or {}).get('completion_tokens_details') or {}).get('reasoning_tokens') or 0 for r in ok]
    rt_avg = (sum(rt) / len(rt)) if rt else 0
    inj = sum(1 for r in ok if r.get('notice_injected'))
    eff = set()
    for r in ok[:50]:
        b = r.get('request') or {}
        if 'reasoning_effort' in b: eff.add(str(b.get('reasoning_effort')))
    print('  %-16s 轮数=%-4d 空动作=%-3d (%.1f%%) | 平均 reasoning_tokens=%-5.0f | notice注入=%-3d | effort=%s' % (
        name, turns, empty, 100.0 * empty / max(1, turns), rt_avg, inj, sorted(eff) or '-'))

print()
print('=' * 92)
print('E) NEW3 的截断提醒是否真的进了请求（抽查）')
print('=' * 92)
recs = load_jsonl(data[0][2]); ok = [r for r in recs if not r.get('error')]
shown = 0
for r in ok:
    if r.get('notice_injected'):
        sysmsg = ''.join((m.get('content') or '') for m in (r.get('request') or {}).get('messages') or [] if m.get('role') == 'system')
        tail = sysmsg[-200:]
        print('  turn %-3s empty_total=%s streak=%s' % (r.get('turn'), r.get('empty_total'), r.get('empty_streak')))
        print('     system 尾部: ...%s' % ' '.join(tail.split())[-170:])
        shown += 1
        if shown >= 4: break
if not shown: print('  （本轮没有出现空回复 → 没有注入，属正常）')
