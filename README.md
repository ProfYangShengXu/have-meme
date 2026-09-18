# have-meme · 让模型「有梗」

> 一个中文语言梗的**多路检索库** + 一套**可复用的抖机灵方法论**。
> 数据不随仓库分发（许可各异），用 `fetch_data.py` 自己拉。

---

## 这是什么

中文网络里最好笑的那批语言梗，集中在**弱智吧**（"一本正经地陈述荒谬"）和**歇后语**里。
它们的共同点是：**笑点不是靠瞎编，而是把一条真逻辑推到荒谬的终点**。

这个项目做两件事：

1. **多路检索**：把 4.8 万条真实梗语料建成 SQLite，用 **拼音 / 字形 / 关键词** 三路并行召回 + RRF 融合
2. **方法论文档**：把"怎么写出这种梗"拆成可执行的规则（见 `skill/SKILL.md`）

## 为什么需要"多路"

**谐音梗和字形梗的相似性，不在语义空间里。**

```
"李华"  →  "李华为"
语义向量：警察 vs 科技公司，距离极远   ✗
拼音：    li-hua → li-hua-wei        前缀完全命中 ✓
```

所以纯向量检索抓不到谐音梗。本项目用**拼音 n-gram 倒排** + **部首/字形匹配** + **BM25** 补上。

## 快速开始

```bash
pip install pypinyin jieba rank_bm25

export MEME_DATA_ROOT=/your/data/dir      # 默认 D:\datasets (Windows)
python fetch_data.py                      # 拉语料（Chumor 需要 HF token，见下）
python build_db.py                        # 建库（4.8 万条，约 25 MB / 3 秒）
python search.py "王警官"                  # 检索
```

```bash
python search.py "破案率" --kind joke --top 5
python search.py "韭菜" --json
```

Python 里复用（一次加载，多查询）：

```python
import sys; sys.path.insert(0, ".")
import search as S
for r in S.search("导师", top=5):
    print(r["kind"], r["route"], r["text"])
# route 字段告诉你它是被哪几路召回的 -> 用来判断可信度
```

## 语料构成

| 来源 | 条数 | 许可 |
|---|---|---|
| **Chumor**（弱智吧，Michigan NLP）| 3,339 | CC-BY-NC-SA 4.0 |
| **chinese-xinhua** 歇后语 | 14,032 | MIT |
| **chinese-xinhua** 成语 | 30,895 | MIT |
| **MemeBench**（图文梗，可选）| 1,253 | CC-BY-NC-SA 4.0 |

⚠️ **Chumor 与 MemeBench 是非商用许可**：本项目代码可用于任何用途，但**用这两份语料做商业产品需要另行取得授权**。

## 抖机灵的方法论（核心）

这套规则比检索本身更重要 —— 详见 [`skill/SKILL.md`](skill/SKILL.md)。摘要：

### 一条梗成立需要三样东西

| 要素 | 含义 |
|---|---|
| **集体记忆** | 这个词/概念对方一定知道（"托梦" ✓，"batch/checkpoint" ✗）|
| **真逻辑** | 这套知识里**真有一条规则**能推下去 |
| **荒谬结论** | 推出来的结果荒谬，但推理每一步都合法 |

### 对照

```
✗ 睡吧，知识我帮你打包好了，梦里自动解压。
   —— "解压"和"梦"之间没有任何桥，纯拼贴

✓ 睡吧。真改成托梦上课，你还得先睡着才收得到。
   —— 托梦的前提就是睡着 → 你"想睡"反而成了完成学业的条件
```

### 输出格式

**梗就是回答本身，放在最前面，后面不要跟任何解释。**
逻辑链是写作者自己内部的质检工具，不是交付内容 —— 解释笑话就是拆自己的台。

## 仓库结构

```
have-meme/
├── fetch_data.py            拉语料（按需，不入库）
├── build_db.py              建 SQLite + 预计算拼音/字形字段
├── search.py                三路检索 + RRF 融合
└── skill/
    ├── SKILL.md             完整方法论（六类机制 / 输出格式 / 反面清单）
    └── references/
        ├── mechanics.md     每种机制的真实语料
        └── data-sources.md  数据源与检索原理
```

## 已知局限

- **短查询（≤2 字）拼音歧义大** → 已加 0.35 折扣，但仍会有噪声
- **拼音倒排只建到 3-gram**（建 4/5-gram 会到 240 万条、爆内存）
- **没有语义向量路** —— 这是刻意的：谐音梗的相似性本来就不在语义空间。做"主题召回"时可以补一路 `bge-small-zh`
- **同一笑话有多份解释**（Chumor 的 `Label` 字段是 good/bad 人工判定），检索时按文本去重

## 致谢

- **Chumor** — He et al., *Chumor 2.0: Towards Better Benchmarking Chinese Humor Understanding* (Findings of ACL 2025) · [arXiv:2412.17729](https://arxiv.org/abs/2412.17729)
- **chinese-xinhua** — [pwxcoo/chinese-xinhua](https://github.com/pwxcoo/chinese-xinhua)
- **MemeBench** — *MemeBench: Diagnosing Cultural-Semantic Understanding in LVLMs through Memes*

## License

代码：MIT（见 `LICENSE`）
数据：各自遵循其原许可 **（Chumor / MemeBench 为非商用）**
