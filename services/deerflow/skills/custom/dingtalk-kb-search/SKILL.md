---
name: dingtalk-kb-search
description: 钉钉知识库全文检索：用 dws aisearch enterprise 跨格式提取正文，adoc 补充全文，标注来源，禁止网络搜索。
---

# 钉钉知识库检索技能 (dingtalk-kb-search)

## 适用场景

当用户要求在钉钉知识库中查找内容、检索知识、搜索文档正文时使用。不用于纯文档标题搜索或本地文件查找。

## 前置条件

- 已安装 `dws` CLI 并完成钉钉登录认证
- 有钉钉知识库访问权限

## 检索标准流程

### 第一步：AI 搜问全文检索（首选，必做）

使用 `dws aisearch enterprise` 跨文档全文检索。该工具能从 PPTX/PDF/adoc/axls 等所有格式的钉钉文档中提取正文片段，不受文档格式限制。

```bash
dws aisearch enterprise --query "关键词" --format json
```

**关键词策略：**
1. 先用精确词搜（如 `"JBS三大支柱"`）
2. 再用拆分词搜（如 `"JBS"`、`"支柱"`、`"战略"` 等）
3. 多轮搜索确保覆盖全面

**结果解析：**
- `result[].snippet` — 包含匹配的正文片段，是核心内容来源
- `result[].title` — 文档标题
- `result[].url` — 文档链接
- `result[].nodeId` — 文档节点 ID
- `result[].meta.doc_type` — 文档格式（pptx/pdf/adoc 等）
- `result[].sourceType` — 来源类型（document/todo 等，优先取 document）

### 第二步：adoc 文档补充全文（按需）

如果需要更完整的内容，且文档类型为 `adoc`，可用 `dws doc +fetch` 读取全文：

```bash
dws doc +fetch --node <nodeId> --detail full --format json
```

> ⚠️ `dws doc +fetch` 仅支持 adoc 格式。PPTX/PDF/axls 等格式会报错 `invalidRequest.inputArgs.invalid`，不要重试，依赖 aisearch 的 snippet 即可。

### 第三步：知识库节点浏览（补充定位）

如果需要确认文档所在位置或查找同目录下其他文档：

```bash
# 列出知识库下某节点的子节点
dws wiki +node-list --workspace <workspaceId> --node <folderNodeId> --format json
```

### 第四步：输出规范

**必须遵守：**

1. **标注来源** — 每条引用必须标明：
   - 知识库名称
   - 文档标题
   - 文档链接（url）

2. **引用原文** — 直接引用 aisearch 返回的 snippet 片段，不做改写或网络补充

3. **结构化输出** — 按主题组织内容，非简单罗列搜索结果

4. **找不到时明确说明** — 「在知识库中未找到相关内容」

5. **禁止网络搜索** — 用户要求查知识库时，不从网络搜索补充内容

## 常见错误与规避

| 错误行为 | 正确做法 |
|---------|---------|
| 用 `dws doc +fetch` 读 PPTX/PDF | 用 `dws aisearch enterprise` 搜正文片段 |
| 只搜一轮就结束 | 精确词 + 拆分词多轮搜索 |
| 混入网络搜索结果 | 只输出知识库内找到的内容 |
| 不标来源 | 每条引用标注知识库名+文档标题+链接 |
| 用 `dws doc +search` 搜正文 | `doc +search` 只搜标题，全文检索用 `aisearch enterprise` |

## 关键工具对照

| 需求 | 工具 | 说明 |
|------|------|------|
| 全文检索（跨格式） | `dws aisearch enterprise --query "关键词"` | **首选**，支持所有格式 |
| 读取 adoc 全文 | `dws doc +fetch --node <nodeId>` | 仅 adoc 格式 |
| 搜索文档标题 | `dws doc +search --query "关键词"` | 只匹配标题，不搜正文 |
| 浏览知识库节点 | `dws wiki +node-list --workspace <wsId> --node <nodeId>` | 定位文档位置 |
| 获取节点元信息 | `dws wiki +node-get --workspace <wsId> --node <nodeId>` | 查看节点详情 |
| 下载文件 | `dws drive +download --node <nodeId>` | 可能受网络限制 |

## 示例

### 示例 1：检索"JBS三大支柱"

```bash
# 第一轮：精确词
dws aisearch enterprise --query "JBS三大支柱" --format json

# 第二轮：拆分词补充
dws aisearch enterprise --query "JBS 战略" --format json
dws aisearch enterprise --query "增长 精益 领导力" --format json
```

从 snippet 中提取核心内容，标注来源文档和链接，结构化输出。

### 示例 2：检索"零缺陷管理"

```bash
dws aisearch enterprise --query "零缺陷" --format json
dws aisearch enterprise --query "PONC 质量管理" --format json
```

如结果中有 adoc 文档，可用 `dws doc +fetch` 补充全文。

## 输出模板

```
## [主题名称]

**来源：钉钉知识库 - [知识库名称]**

[正文内容，引用 snippet 原文片段]

---

**引用文档：**
1. 《文档标题》
   - 知识库：[知识库名称]
   - 链接：[url]
2. ...
```
