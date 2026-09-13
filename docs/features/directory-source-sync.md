# 钉钉目录采集修复说明

目录同步的目标是 Dify 知识库。钉钉是来源；在线文档需要钉钉官方导出，普通上传文件直接下载原文件。

## 问题与修复

- 历史 `prepare_document` 会把 PPTX 抽取成 Markdown，丢失图片、表格和版式。当前只校验文件，保留名称、扩展名和原字节，不再转文本入库。
- 目录与单文件原来各自组装上传协议。现在共用 `kb_common.clients.dify_document`，统一普通分段规则、流水线运行请求与响应解析。
- 目标库按 ID 绑定，并读取详情识别 `runtime_mode` / `pipeline_id`。旧任务没有 ID 时才按唯一名称查找；改名不切换目标，同名不随意选第一个。
- 流水线使用本地文件上传与已发布 `pipeline/run`，不套用普通 ETL 的扩展名过滤。实际解析能力仍由流水线中的解析节点决定。
- 目录遍历包含嵌套文件夹和文档下的子节点，不依赖文件夹必须返回 `hasChildren=true`。深度超限整次失败，避免把未遍历到的文件误当作源端删除。
- 在线文档类型同时读取节点 `extension` 与文件名；普通 PDF/Word 不因 `ALIDOC` 分类被误导出为 DOCX。已验证的在线文档导出为 DOCX、XLSX；脑图/白板提示先在钉钉导出 PDF；每个节点独立保存，避免同名覆盖。
- 流水线替换先完成新文档索引，再删除旧文档。普通库历史错误文档不能 `update-by-file` 时也按此方式恢复；仍在索引的旧文档提示等待。
- 流水线输入表单仅取所选本地文件节点及 `shared` 参数，补齐已发布默认值，不再注入固定 `max_chunk_length=1024`，也不要求填写其他网页数据源的 URL。
- 更换目标库后清除旧的远端文档映射，保留逐文档开关；原目标库的已有文档保留。运行中不能更换目标库。
- 删除了无人调用的文本降级上传助手、旧配置构造函数和计数/路径助手，保留仍用于问答的原文解析能力。

## 验证

```bash
cd services/kb-api
uv run --with pytest python -m pytest tests/test_sync.py tests/test_sync_regressions.py tests/test_lossless_collection.py ../kb-common/tests/test_document_upload.py -q
cd ../../web
pnpm test:run src/components/collection/__tests__/PipelineInputs.test.ts
pnpm type-check
pnpm build
```

68 项后端测试及 5 项参数表单测试通过，前端类型检查与生产构建通过。回归覆盖原文件字节、普通库分段规则、目录流水线三步上传、嵌套遍历、单文档失败后继续、索引失败保留旧文档、按 ID 选择目标与流水线参数分支。

运行记录中已有 `.doc` 被 `dify_extractor` 拒绝并报 `Could not detect encoding` 的情况：这表示文件已送达流水线，但解析节点不支持该文件。需要在目标流水线配置能处理旧版 Word 的解析节点；采集端保留原文件并报告失败。上传上限默认 15 MB，可在系统配置的 Dify 链接配置中调整，需与 Dify 自身 UPLOAD_FILE_SIZE_LIMIT 和网关一致；超限明确报错，不转成文本规避限制。

真实环境已用临时 DOCX 验证普通库和公共关系部流水线均创建文档，随后删除测试文档；未批量重跑业务目录。回下载遇到普通库文件预览地址 502、流水线文档 download 接口报告没有可下载的上传文件，因此不能声称已完成远端 SHA256 一致性验证。流水线请求超时且未返回文档 ID 时，仍需先在 Dify 确认执行结果，避免重复上传。

## 原文件与页面参数配置

- 指定文档同步与目录同步共用 `fetch_source_file`：普通文件通过节点 ID 解析存储条目、获取签名地址后原样下载；下载校验 Content-Length、Content-MD5 及节点 size（如有）。不把 ETag 一概当作 MD5。指定文档同步返回源文件 SHA256 和大小。
- 在线文字文档用当前 DWS `doc +export` 导出 DOCX，在线表格导出 XLSX；独立临时目录隔离每次导出，禁止旧文件冒充成功。钉钉在线协作批注、权限、历史版本和特殊控件的保真范围由官方导出能力决定。
- 三个采集入口共用 `PipelineInputs.vue`，展示文件分支与 shared 参数、补齐默认值、提前校验必填项。未读取到已发布定义时，可导入 `.pipeline`（最多 1 MB）生成表单，或填写 JSON。导入仅保存表单定义，不执行或发布配置中的工作流。
- 《公共关系部.pipeline》的文件节点为 `1750836380067`，7 个共享参数是 `parent_mode`、`parent_dilmiter`、`parent_length`、`child_delimiter`、`child_length`、`clean_1`、`clean_2`。不要求填写其它网页分支的 `jina_reader_url`。
- 该流水线的条件分支两路都连接 Dify Extractor；`full_doc` 的工具提示注明超过 10000 tokens 会截断，清洗开关也会改变索引文本。原文件无改写不代表解析文本/索引保留版式或所有内容。
- 同步列表预演请求超时 10 分钟。本任务先前按要求设置过 8 小时任务上限；2026-09-13 收尾时发现工作区同时新增 RAGFlow 长解析修改，将 .env、默认配置与示例中的任务/索引上限调整为 604800 秒（7 天）。该并行修改未被本次覆盖，不能再声称当前生效值是 8 小时。

接口依据：[普通库 create-by-file](https://docs.dify.ai/zh/api-reference/documents/create-document-by-file)、[流水线文件上传](https://docs.dify.ai/zh/api-reference/knowledge-pipeline/upload-pipeline-file)、[运行已发布流水线](https://docs.dify.ai/zh/api-reference/knowledge-pipeline/run-pipeline)。
