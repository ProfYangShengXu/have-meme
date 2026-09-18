#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多路中文梗检索 (v1: 拼音 / 字形 / BM25，RRF 融合)

用法:
  python search.py "李华为"
  python search.py "王警官" --top 8
  python search.py "破案率" --kind joke
"""
import os, io, sys, json, sqlite3, re, math, argparse
from collections import defaultdict

from pypinyin import lazy_pinyin, Style
import jieba
from rank_bm25 import BM25Okapi

ROOT   = os.environ.get("MEME_DATA_ROOT", r"D:\datasets")
DB     = os.path.join(ROOT, "meme-db", "meme.db")
HANZI  = os.path.join(ROOT, "chinese-xinhua", "data", "word.json")

# ---------------- 基础工具 ----------------
def py_compact(s: str) -> str:
    return "".join(lazy_pinyin(s, style=Style.NORMAL, errors=lambda x: list(x)))

def hanzi_only(s: str) -> str:
    return "".join(c for c in s if "\u4e00" <= c <= "\u9fff")

# 字 -> 部首
_RAD = None
def radicals_map():
    global _RAD
    if _RAD is None:
        _RAD = {}
        if os.path.exists(HANZI):
            for d in json.load(io.open(HANZI, encoding="utf-8")):
                w, r = d.get("word"), d.get("radicals")
                if w and r:
                    _RAD[w] = r
    return _RAD

# ---------------- 载入 ----------------
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = list(con.execute(
    "SELECT id,kind,text,aux,label,source,chars,py,py_compact,py_grams,len FROM memes"))
print(f"[load] {len(rows)} 条", file=sys.stderr)

# BM25 索引（jieba 分词，只对 text+aux 前 120 字）
_corpus_tokens = []
for r in rows:
    seg = (r["text"] + " " + (r["aux"] or "")[:120])
    _corpus_tokens.append([w for w in jieba.lcut(seg) if w.strip()])
BM25 = BM25Okapi(_corpus_tokens)

# 拼音倒排（紧凑拼音 -> 行号），用于子串召回
_py_idx = defaultdict(list)
for i, r in enumerate(rows):
    p = r["py_compact"] or ""
    for L in (2, 3):
        for j in range(0, max(0, len(p) - L + 1), 1):
            _py_idx[p[j:j + L]].append(i)

# ---------------- 各路召回 ----------------
def route_pinyin(q, limit=200):
    """把查询转拼音，找拼音里含该串的条目（谐音/同音召回）"""
    qp = py_compact(q)
    if len(qp) < 2:
        return []
    hits = defaultdict(int)
    for L in range(len(qp), 1, -1):
        for j in range(0, len(qp) - L + 1):
            sub = qp[j:j + L]
            if len(sub) < 2:
                continue
            for i in _py_idx.get(sub, []):
                hits[i] += len(sub) ** 2      # 长匹配权重平方增长
    # 短查询（<=2 字）拼音歧义大，整体折扣，避免"华为"这种召回噪声
    qh_len = len(hanzi_only(q))
    damp = 0.35 if qh_len <= 2 else (0.75 if qh_len == 3 else 1.0)
    out = sorted(hits.items(), key=lambda x: -x[1])[:limit]
    return [(i, "pinyin", f"拼音片段命中({s*damp:.0f})") for i, s in out]

def route_shape(q, limit=200):
    """字形：按部首集合重叠 + 汉字序列子串"""
    rmap = radicals_map()
    qh = hanzi_only(q)
    if not qh:
        return []
    q_rad = [rmap.get(c) for c in qh if rmap.get(c)]
    q_set = set(q_rad)
    scored = []
    for i, r in enumerate(rows):
        ch = r["chars"] or ""
        if not ch:
            continue
        s = 0.0
        if qh and qh in ch:                       # 直接子串
            s += 10.0
        else:                                      # 部首重叠
            for c in ch[:12]:
                if rmap.get(c) in q_set:
                    s += 1.0
        if s > 0:
            scored.append((i, s))
    scored.sort(key=lambda x: -x[1])
    return [(i, "shape", "字形/部首相近") for i, _ in scored[:limit]]

def route_bm25(q, limit=200):
    toks = [w for w in jieba.lcut(q) if w.strip()]
    if not toks:
        return []
    scores = BM25.get_scores(toks)
    idx = sorted(range(len(scores)), key=lambda i: -scores[i])[:limit]
    return [(i, "bm25", "关键词相关") for i in idx if scores[i] > 0]

# ---------------- RRF 融合 ----------------
def rrf(rank_lists, k=60):
    agg, why = defaultdict(float), {}
    for lst in rank_lists:
        for rank, (i, route, reason) in enumerate(lst):
            agg[i] += 1.0 / (k + rank + 1)
            why.setdefault(i, []).append(route)
    return sorted(agg.items(), key=lambda x: -x[1]), why

# ---------------- 主 ----------------
def search(q, top=10, kind=None, per_route=200):
    ls = [route_pinyin(q, per_route), route_shape(q, per_route), route_bm25(q, per_route)]
    merged, why = rrf(ls)
    out, seen = [], set()
    for i, sc in merged:
        r = rows[i]
        if kind and r["kind"] != kind:
            continue
        key = (r["text"] or "")[:60]          # 同一笑话多份解释 -> 只留最高分那条
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(score=round(sc, 5), kind=r["kind"], route="+".join(sorted(set(why[i]))),
                        text=r["text"], aux=(r["aux"] or "")[:200],
                        label=r["label"], source=r["source"]))
        if len(out) >= top:
            break
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--kind", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = search(a.query, a.top, a.kind)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(f"\n查询: {a.query}   拼音: {py_compact(a.query)}")
        for n, r in enumerate(res, 1):
            print(f"\n{n}. [{r['kind']}] {r['route']}  score={r['score']}")
            print(f"   {r['text']}")
            if r['aux']:
                print(f"   → {r['aux'][:120]}")
