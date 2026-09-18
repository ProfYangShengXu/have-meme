#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_data.py — 一键拉取 have-meme 所需的语料。

用法:
    python fetch_data.py                 # 拉到 $MEME_DATA_ROOT（默认 D:\\datasets）
    MEME_DATA_ROOT=/data/meme python fetch_data.py

产物:
    $MEME_DATA_ROOT/chinese-xinhua/     歇后语 14k / 成语 31k / 汉字 16k   (MIT)
    $MEME_DATA_ROOT/chumor/test.tsv     弱智吧笑话 3,339 行                (CC-BY-NC-SA, gated)
    $MEME_DATA_ROOT/memebench/          图文梗 1,253 条（可选）             (CC-BY-NC-SA)

然后:
    python build_db.py     # 建库
    python search.py "关键词"
"""
import os, sys, subprocess, shutil

ROOT = os.environ.get("MEME_DATA_ROOT", r"D:\datasets")
os.makedirs(ROOT, exist_ok=True)
print(f"[info] 数据根目录: {ROOT}")

def sh(cmd, **kw):
    print("  $", " ".join(cmd) if isinstance(cmd, list) else cmd)
    return subprocess.run(cmd, shell=isinstance(cmd, str),
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, **kw)

# ---------- 1. 新华字典库（MIT，最省事，强烈建议先跑这个） ----------
def get_xinhua():
    dst = os.path.join(ROOT, "chinese-xinhua")
    if os.path.exists(os.path.join(dst, "data", "xiehouyu.json")):
        print("[skip] chinese-xinhua 已存在")
        return True
    if os.path.exists(dst):
        shutil.rmtree(dst, ignore_errors=True)
    r = sh(["git", "clone", "--depth", "1",
            "https://github.com/pwxcoo/chinese-xinhua.git", dst])
    return r.returncode == 0

# ---------- 2. Chumor（gated，需要 HF token）----------
def get_chumor():
    dst = os.path.join(ROOT, "chumor")
    out = os.path.join(dst, "test.tsv")
    if os.path.exists(out):
        print("[skip] chumor 已存在")
        return True
    os.makedirs(dst, exist_ok=True)
    tok = os.environ.get("HF_TOKEN")
    if not tok:
        env_file = os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", "secrets", "hf.env")
        if os.path.exists(env_file):
            for line in open(env_file, encoding="utf-8"):
                if line.startswith("HF_TOKEN="):
                    tok = line.split("=", 1)[1].strip()
    if not tok:
        print("[warn] 没有 HF_TOKEN —— Chumor 是 gated 数据集。")
        print("       1) 去 https://huggingface.co/datasets/MichiganNLP/Chumor 点 Agree and access")
        print("       2) export HF_TOKEN=hf_xxx  后重跑本脚本")
        print("       （跳过 Chumor 也能跑，只是少了 3,339 条弱智吧笑话）")
        return False
    os.environ["HF_TOKEN"] = tok
    # hf-mirror 在国内可直连
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    from huggingface_hub import hf_hub_download
    p = hf_hub_download("MichiganNLP/Chumor", "test.tsv",
                        repo_type="dataset", local_dir=dst)
    print("  ->", p, os.path.getsize(p), "bytes")
    return True

# ---------- 3. MemeBench（可选，图文梗）----------
def get_memebench():
    dst = os.path.join(ROOT, "memebench")
    if os.path.exists(os.path.join(dst, "metadata.jsonl")):
        print("[skip] memebench 已存在")
        return True
    os.makedirs(dst, exist_ok=True)
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    try:
        from huggingface_hub import hf_hub_download
        for f in ["README.md", "memebench_v1.json", "metadata.jsonl"]:
            hf_hub_download("anonymous-neurips-2026/memebench", f,
                            repo_type="dataset", local_dir=dst)
        print("  （图片按需下载: images/image_0001.png ... 共 1253 张，约 300MB）")
        return True
    except Exception as e:
        print("[warn] memebench 拉取失败:", str(e)[:200])
        return False

if __name__ == "__main__":
    ok = {}
    ok["chinese-xinhua"] = get_xinhua()
    ok["chumor"] = get_chumor()
    ok["memebench"] = get_memebench()
    print("\n=== 结果 ===")
    for k, v in ok.items():
        print(f"  {k:16} {'OK' if v else 'FAILED/SKIPPED'}")
    print("\n下一步:  python build_db.py")
