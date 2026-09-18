#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多路中文梗检索 (v1: 拼音 / 字形 / BM25，RRF 融合)

用法:
  python search.py "李华为"
  python search.py "王警官" --top 8
  python search.py "破案率" --kind joke
"""
import os, io, sys, json, sqlite3, re, math, argparse, time
from collections import defaultdict

from pypinyin import lazy_pinyin, Style
import jieba
from rank_bm25 import BM25Okapi

ROOT   = r"D:\datasets"
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

# ---------------- 扩充打击面：随机召回 / 关联跳跃 ----------------
# 跳跃时别抽到"最后/一一/恕我直言"这种没法当话题的词
_STOP = {
    "最后", "一一", "然后", "因为", "所以", "但是", "如果", "这样", "那样",
    "什么", "怎么", "可以", "没有", "一个", "自己", "就是", "还是", "不能",
    "不会", "知道", "觉得", "时候", "现在", "已经", "开始", "出来", "起来",
    "这个", "那个", "我们", "他们", "你们", "上面", "下面", "里面", "外面",
    "前后", "大约", "应该", "于是", "而且", "并且", "虽然", "于是", "到底",
    "突然", "终于", "果然", "只好", "只能", "一定", "可能", "也许", "其实",
    "发现", "看到", "听到", "来到", "走进", "回头", "抬头", "低头", "由于",
}
_USED_FILE = os.path.join(ROOT, "meme-db", "used_memes.jsonl")

def _load_used():
    if not os.path.exists(_USED_FILE):
        return set()
    try:
        return {json.loads(l)["t"] for l in io.open(_USED_FILE, encoding="utf-8") if l.strip()}
    except Exception:
        return set()

def mark_used(text):
    """记下已经用过的梗，避免重复（追加式，可随时清空）"""
    try:
        with io.open(_USED_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": text, "ts": time.strftime("%Y-%m-%d %H:%M")},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass

def random_meme(kind="joke", avoid_used=True, tries=60):
    """随机抽一条。默认只抽 joke——成语/歇后语是词条，不是梗。
    默认避开用过的，抽完自动记账。"""
    import random as _r
    used = _load_used() if avoid_used else set()
    pool = [i for i, r in enumerate(rows) if (not kind or r["kind"] == kind)]
    _r.shuffle(pool)
    for i in pool[:tries]:
        t = rows[i]["text"]
        if t not in used and len(t) <= 60:      # 太长的不适合当抖机灵素材
            mark_used(t)
            r = rows[i]
            return dict(kind=r["kind"], text=t, aux=(r["aux"] or "")[:200],
                        label=r["label"], source=r["source"], route="random")
    return None

def wander(start_q, steps=2, n=1, kind=None):
    """
    关联跳跃：从 start_q 出发，一路"半跳"到相邻话题。
    每一跳只换一个词，所以不会突然跳得莫名其妙——像联想，不像抽签。

    做法: 检索 -> 从命中的梗里随机取一条 -> 从它文本里抽一个词 -> 用那个词再检索 -> ...
    返回走过的路径，可以只交付最后一跳（前面的是铺垫，不用说出来）。
    """
    import random as _r
    path, cur = [], start_q
    for _ in range(max(1, steps)):
        hits = search(cur, top=6, kind=kind)
        if not hits:
            break
        cand = _r.choice(hits[:4])          # 只在前几名里随机，保证质量
        path.append({"from": cur, "picked": cand["text"]})
        words = [w for w in jieba.lcut(cand["text"])
                 if 2 <= len(w) <= 4 and w not in _STOP
                 and all("\u4e00" <= c <= "\u9fff" for c in w)]
        if not words:
            break
        cur = _r.choice(words)              # 换一个词，就是换一个话题方向
    out = []
    if path:
        out = search(path[-1]["picked"][:20] or cur, top=n, kind=kind)
    return {"path": path, "exit_query": cur, "results": out}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default=None)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--kind", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--random", action="store_true", help="随便来一条")
    ap.add_argument("--wander", type=int, metavar="STEPS", help="从 query 出发关联跳跃 N 步")
    a = ap.parse_args()

    if a.random:
        r = random_meme(kind=a.kind or "joke")
        print(r["text"] if r else "(库里没货了)")
        raise SystemExit(0)

    if a.wander:
        if not a.query:
            ap.error("--wander 需要给一个起点词")
        w = wander(a.query, steps=a.wander, n=a.top, kind=a.kind)
        for r in w["results"]:
            print(f"[{r['kind']}] {r['text']}")
            if r.get("aux"):
                print(f"    -> {r['aux'][:120]}")
        raise SystemExit(0)

    if not a.query:
        ap.error("要么给 query，要么用 --random")

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
