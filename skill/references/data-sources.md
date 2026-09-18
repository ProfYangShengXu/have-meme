# 数据源与建库

## 已落盘的语料（D 盘）

| 路径 | 内容 | 条数 |
|---|---|---|
| `D:\datasets\chumor\test.tsv` | 弱智吧笑话（Joke/Explanation/Label/Source）| 3,339 行 |
| `D:\datasets\chinese-xinhua\data\xiehouyu.json` | 歇后语（riddle/answer）| 14,032 |
| `D:\datasets\chinese-xinhua\data\idiom.json` | 成语（含 pinyin/explanation）| 30,895 |
| `D:\datasets\chinese-xinhua\data\word.json` | 汉字（含 pinyin/radicals/strokes）| 16,142 |
| `D:\datasets\memebench\` | 图文 memes + VIKR 六层标注 | 1,253 |

## 建库

```bash
python D:\datasets\meme-db\build_db.py
```
预计算字段：`chars`（纯汉字）/ `py` / `py_compact`（无空格拼音）/ `py_grams`（2-3-gram）

## 数据库 schema

```sql
CREATE TABLE memes (
  id, kind,        -- joke / xiehouyu / idiom
  text,            -- 梗本体
  aux,             -- 解释 / 谜底
  label,           -- good / bad (仅 joke)
  source,
  chars, py, py_compact, py_grams, len
);
```

## 检索原理

**三路并行 + RRF（倒数排名融合）**，k=60，**带路由权重**：

```python
_ROUTE_W = {"pinyin": 1.8, "shape": 1.2, "bm25": 1.0}
```

| 路 | 实现 | 抓什么 | 权重 |
|---|---|---|---|
| `route_pinyin` | 拼音 2-3gram 倒排，得分 = 匹配长度² | 谐音 / 同音梗 | **1.8** |
| `route_shape` | 部首集合重叠 + 汉字序列子串 | 字形 / 拆字梗 | 1.2 |
| `route_bm25` | jieba 分词 + BM25Okapi | 主题 / 关键词 | 1.0 |

**⭐ 为什么拼音权重最高**（用户 2026-09-18 直接指出）：
谐音梗含一个音，**能嫁接到任何含那个音的词上**，是三者里**最容易"圆回来"**的素材。
想要更多可嫁接的素材，就再调大这个值。

**实测**：查"代码"时 `"所以，i 是会消失的对吗？"外部环境向 for 循环代码块问道`
—— 拼音路召回的，放大权重前被 BM25 压着上不来。

**已知局限**：
- 短查询（≤2 字）拼音歧义大 → 已加 0.35 折扣，但仍会有噪声
- 拼音倒排只建到 3-gram（建 4/5-gram 会到 240 万条、爆内存）
- **没有语义向量路**（v1 刻意省略：谐音梗的相似性本来就不在语义空间；加它是为了主题召回，可后续用 `bge-small-zh` 补）

## 数据获取（复现用）

```bash
# Chumor（HF 上是 gated，需 token；hf-mirror 可用）
HF_ENDPOINT=https://hf-mirror.com python -c "\
  from huggingface_hub import hf_hub_download;\
  hf_hub_download('MichiganNLP/Chumor','test.tsv',repo_type='dataset',local_dir=r'D:\\datasets\\chumor')"

# 歇后语 / 成语 / 汉字
git clone --depth 1 https://github.com/pwxcoo/chinese-xinhua.git D:/datasets/chinese-xinhua
```

HF token 存 `%LOCALAPPDATA%\hermes\secrets\hf.env`（`HF_TOKEN=...`）。

## 依赖

```
pypinyin  jieba  rank_bm25  (sentence_transformers 可选，做语义路时用)
```
装到系统 Python312（sandbox 里没有）。
