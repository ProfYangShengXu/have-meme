#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
建库：把三个中文梗语料合并进一个 SQLite，并预计算检索用的派生字段。

数据源:
  D:\\datasets\\chumor\\test.tsv           弱智吧笑话 (Joke/Explanation/Label/Source)
  D:\\datasets\\chinese-xinhua\\data\\xiehouyu.json   歇后语 (riddle/answer)
  D:\\datasets\\chinese-xinhua\\data\\idiom.json      成语   (word/pinyin/explanation)
  D:\\datasets\\chinese-xinhua\\data\\word.json       汉字   (word/pinyin/radicals)

输出:
  D:\\datasets\\meme-db\\meme.db
"""
import os, io, json, csv, sqlite3, re, sys
from pypinyin import lazy_pinyin, Style

ROOT = r"D:\datasets"
DB   = os.path.join(ROOT, "meme-db", "meme.db")
os.makedirs(os.path.dirname(DB), exist_ok=True)

# ---------- 拼音 / 字形 派生 ----------
_py_cache = {}

def to_pinyin(s: str) -> str:
    """汉字 -> 无声调拼音，空格分隔"""
    if s in _py_cache:
        return _py_cache[s]
    out = " ".join(lazy_pinyin(s, style=Style.NORMAL, errors=lambda x: list(x)))
    _py_cache[s] = out
    return out

def to_pinyin_compact(s: str) -> str:
    """无空格无调拼音，用于前缀/子串匹配"""
    return to_pinyin(s).replace(" ", "")

def py_ngrams(s: str, n_max: int = 4) -> str:
    """拼音的 n-gram 串（用 | 分隔），给谐音召回用"""
    p = to_pinyin_compact(s)
    grams = []
    L = len(p)
    for n in (2, 3, 4):
        if n > n_max:
            break
        for i in range(max(0, L - n + 1)):
            grams.append(p[i:i + n])
    return "|".join(sorted(set(grams)))[:4000]

def hanzi_seq(s: str) -> str:
    """只留汉字，给字形路用"""
    return "".join(ch for ch in s if "\u4e00" <= ch <= "\u9fff")

# ---------- 建表 ----------
con = sqlite3.connect(DB)
cur = con.cursor()
cur.executescript("""
DROP TABLE IF EXISTS memes;
CREATE TABLE memes (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  kind        TEXT,      -- joke / xiehouyu / idiom
  text        TEXT,      -- 主体文本（梗本身）
  aux         TEXT,      -- 辅助文本（成语释义 / 歇后语谜底 / 笑话解释）
  label       TEXT,      -- good / bad / NULL
  source      TEXT,      -- 来源标记
  chars       TEXT,      -- 纯汉字序列
  py          TEXT,      -- 带空格拼音
  py_compact  TEXT,      -- 无空格拼音
  py_grams    TEXT,      -- 拼音 n-gram
  len         INTEGER
);
CREATE INDEX idx_kind ON memes(kind);
CREATE INDEX idx_py_compact ON memes(py_compact);
CREATE INDEX idx_chars ON memes(chars);
""")

rows = []

# 1) 弱智吧笑话
p = os.path.join(ROOT, "chumor", "test.tsv")
if os.path.exists(p):
    before = len(rows)
    with io.open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            joke = (r.get("Joke") or "").strip()
            if not joke:
                continue
            joke = re.sub(r"^标题[:：]\s*", "", joke).strip()
            rows.append(dict(kind="joke", text=joke,
                             aux=(r.get("Explanation") or "").strip(),
                             label=(r.get("Label") or "").strip() or None,
                             source="chumor:" + (r.get("Source") or "")))
    print(f"[chumor]   {len(rows)-before} 条")

# 2) 歇后语
p = os.path.join(ROOT, "chinese-xinhua", "data", "xiehouyu.json")
if os.path.exists(p):
    before = len(rows)
    data = json.load(io.open(p, encoding="utf-8"))
    for d in data:
        rid, ans = (d.get("riddle") or "").strip(), (d.get("answer") or "").strip()
        if not rid:
            continue
        rows.append(dict(kind="xiehouyu", text=rid, aux=ans,
                         label=None, source="xinhua"))
    print(f"[xiehouyu] {len(rows)-before} 条")

# 3) 成语
p = os.path.join(ROOT, "chinese-xinhua", "data", "idiom.json")
if os.path.exists(p):
    before = len(rows)
    data = json.load(io.open(p, encoding="utf-8"))
    for d in data:
        w = (d.get("word") or "").strip()
        if not w or len(w) < 2:
            continue
        rows.append(dict(kind="idiom", text=w,
                         aux=(d.get("explanation") or "").strip()[:300],
                         label=None, source="xinhua"))
    print(f"[idiom]    {len(rows)-before} 条")

# 4) 用户原创梗（自己接的 / 写出来的好梗，追加式，不随重建丢失）
p = os.path.join(ROOT, "meme-db", "user_memes.jsonl")
if os.path.exists(p):
    before = len(rows)
    for _line in io.open(p, encoding="utf-8"):
        _line = _line.strip()
        if not _line:
            continue
        try:
            d = json.loads(_line)
        except Exception:
            continue
        if not d.get("text"):
            continue
        rows.append(dict(kind="user", text=d["text"], aux=d.get("aux", ""),
                         label="good", source="user:" + str(d.get("date", ""))))
    print(f"[user]     {len(rows)-before} 条")

# ---------- 写库 ----------
print(f"\n总计 {len(rows)} 条，开始计算派生字段...")
payload = []
for i, r in enumerate(rows):
    txt = r["text"]
    payload.append((r["kind"], txt, r.get("aux") or "", r.get("label"),
                    r.get("source") or "", hanzi_seq(txt),
                    to_pinyin(txt), to_pinyin_compact(txt),
                    py_ngrams(txt), len(txt)))
    if (i + 1) % 10000 == 0:
        print(f"   ... {i+1}")

cur.executemany("""INSERT INTO memes
  (kind,text,aux,label,source,chars,py,py_compact,py_grams,len)
  VALUES (?,?,?,?,?,?,?,?,?,?)""", payload)
con.commit()

for k, c in cur.execute("SELECT kind, COUNT(*) FROM memes GROUP BY kind"):
    print(f"  {k:10} {c}")
print("DB:", DB, f"{os.path.getsize(DB)/1e6:.1f} MB")
con.close()
