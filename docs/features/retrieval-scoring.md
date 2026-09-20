# 基于 RAGFlow 源码的检索服务

## 来源与实现范围

检索核心位于 `services/kb-common/kb_common/rag/ragflow_nlp/`，移植自本项目
RAGFlow checkout（revision `7f09c774370dc9ae4eda91492a502dd10c9c51b3`）：

- `query.py`：问句清理、查询扩展、粗细粒度词项、词项与相邻词对相似度。
- `term_weight.py`：词频、词性、实体类别及 IDF 权重。
- `query_base.py`：中英文边界、查询特殊字符与问句处理。
- `search.py`：候选分段字段组合、向量/重排加权公式、稳定排序和后置阈值。
- RAGFlow 依赖的 `infinity-sdk==0.7.3`：原始 `RagTokenizer` 与 HUQIE 词典。

词典、实体词库和同义词词库随 kb-common 打包，运行时不依赖 RAGFlow 目录或
服务进程。来源摘要见 `ragflow_nlp/sources.json`，版权与修改说明见 `NOTICE`，
Apache-2.0 许可随代码保留。分词器的英语处理使用 Snowball stemming；未包含
WordNet lemmatization、WordNet 同义词及 Redis 在线同义词，以免运行时下载模型。

## 流程

1. 过滤知识库、文档范围、文档和分段启用状态，剔除不可用父段的子段。
2. 使用 RAGFlow 分词、问句清理和同义词扩展生成召回查询。
3. 本地 MinerU 分段：BM25 召回（正文/标题/关键词权重 2/10/30）与真实向量
   召回取并集，各路最多 1024 个候选。原 ES 通道使用 RAGFlow 查询表达式进行
   BM25 召回，加上 kNN 召回，候选范围大于最终 TopK。
4. 使用 RAGFlow 词项权重和相邻词对权重计算相关性，并与余弦相似度加权。
5. 开启 Rerank 时取 `max(64, TopK × 5)` 个候选，模型输入为自然文本，
   使用模型分数替换语义分量，再做加权，而不是直接覆盖成模型分数。
6. 按最终 Score 稳定排序、应用阈值、父段去重、取 TopK。

SQL 分段的 BM25 是本项目存储适配器，并非原封不动运行 RAGFlow 的 ES/Infinity
存储层。没有引入 GraphRAG、PageRank 或项目数据模型中不存在的生成问题字段。

## Score 定义

- 全文：RAGFlow 加权词项覆盖率。
- 向量：真实余弦相似度。
- 混合：`(1 − w) × token_similarity + w × vector_similarity`，默认 `w=0.7`。
- 混合 + Rerank：`(1 − w) × token_similarity + w × rerank_score`。
- 向量 + Rerank：`w=1`，最终分数就是模型分数。
- 全文 + Rerank：全文候选召回后加入重排阶段，默认 `w=0.7`。

`rerank_score` 是模型原始 0～1 分数；`vector_similarity` 仍保留真实余弦分数，
不会混用。`retrieval_score` 记录重排前分数，`semantic_weight` 记录最终权重。
UI 显示评分类型、各分项及混合公式，条形图采用绝对刻度。
Score 是相关性信号，不代表答案正确概率。不同外部引擎分数未统一校准。

移植时修正了上游的两个边界：空查询/完全无重合返回零；用于召回的扩展短语
和按权重重排的词不进入评分分母，评分使用清理后的原始查询词序，因此完全
覆盖原始词及相邻词对时为 1。保留原算法 0.4 单词、0.6 相邻词对权重。
不按本次最高分、结果名次或候选数量归一化。

## 模型与运行

复用系统的 Embedding / Rerank 配置；指定重排配置仅对当前请求生效。
返回数量、索引、维度、有限值和模型分数范围必须有效，否则明确报错。
模型不可用时不使用关键词结果冒充向量结果。

本地 MinerU 分段尚无持久化向量索引：首次查询对符合范围的全部叶分段按 32 条
批量生成向量，使用按模型/地址/凭据摘要/内容隔离的进程缓存（最多 8192 条）。
不会为了减少 embedding 请求而先用关键词筛掉语义候选；大库冷启动仍较慢。
分词词典首次初始化约数秒，随后复用。数据库 schema 无变化。

更新后在服务目录执行 `uv sync` 并重启服务。Dockerfile 已加入 datrie C 扩展
构建所需的编译步骤；实际 Docker 镜像构建需在部署环境验证。

## 验证

```bash
cd services/kb-api
.venv/bin/python -m unittest tests.test_ragflow_kernel tests.test_retrieval_scoring tests.test_managed_libraries -q
```

测试包含直接加载上游源码的词项评分对照、独立手算相邻词权重、中文分词、
繁简/全角、问句清理、无字面交集的向量召回、混合权重、重排索引异常、范围
过滤和父段去重。真实业务准确率需要标注查询集和可用模型服务进行评估。
