# Dify 镜像本地补丁

通过 docker-compose.yaml 中 api 服务的 bind mount 注入，对预构建镜像的临时修复。

## datasource.py

- 修复问题：知识流水线（RAG Pipeline）中内置「文件上传（File Upload）」数据源
  （虚拟插件 `langgenius/file`，无需任何凭据）始终显示「未授权」，且没有授权入口。
- 根因：`PluginDatasourceProviderEntity.is_authorized` 默认为 `False`，
  虚拟本地文件数据源从未被置为 `True`；前端
  `notAuthed = allow_delete && !is_authorized` 因此永远判定为未授权。
- 修复：`_get_local_file_datasource_provider()` 返回的 dict 中增加
  `"is_authorized": True`。
- 适用镜像：`langgenius/dify-api:1.16.1`（容器内文件与
  `../../api/core/plugin/impl/datasource.py` 快照一致）。

## workflow.py

- 修复问题：知识流水线（RAG Pipeline）测试运行「文件上传」数据源后，
  后端报 `ValueError: Unable to resolve tenant_id for app <pipeline_id>`，
  前端表现为上传/运行失败。
- 根因：流水线复用了工作流草稿变量存储，草稿变量的 `app_id` 是
  `pipelines` 表中的 Pipeline ID；但 `models/workflow.py` 中
  `_resolve_workflow_app_tenant_id` 重建文件变量时只查 `apps` 表，
  查不到流水线 ID 直接抛错。
- 修复：`apps` 表查不到时回退查询 `pipelines` 表的 `tenant_id`。
- 适用镜像：`langgenius/dify-api:1.16.1`（注意：本地仓库
  `../../api/models/workflow.py` 与镜像内文件基线不同，本补丁基于
  镜像内文件制作，勿直接用本地快照覆盖）。

## base_app_generator.py

- 修复问题：通过 Service API `POST /datasets/{id}/pipeline/run` 运行知识流水线时，
  `inputs` 传 `{}` 报 `parent_mode is required in input form`（各流水线的
  shared 分段参数必填且变量名不统一，调用方无法穷举）。
- 根因：`_validate_inputs` 对必填变量缺失时直接抛错，即使变量配置了
  默认值也不回退；与官方 API 文档「Pass `{}` if the pipeline has no input
  variables」的语义不符。
- 修复：必填变量缺失但 `default` 非空时回退默认值并继续类型校验；
  仅必填且无默认值时维持原报错。控制台前端总是传全量值，不受影响。
- 挂载：api 与 worker 两个服务均挂载（pipeline generator 在两边都会执行）。
- 适用镜像：`langgenius/dify-api:1.16.1`（容器内文件与
  `../../api/core/app/apps/base_app_generator.py` 快照一致）。

## variables_manager.py

- 修复问题：`base_app_generator.py` 补丁的默认值回退不生效——变量实体
  的 `default` 恒为 `None`。
- 根因：流水线变量在 `workflows.rag_pipeline_variables`（JSON）中以
  `default_value` 键持久化，而 `RagPipelineVariableEntity`（继承
  graphon `VariableEntity`）的字段名是 `default`；`model_validate`
  直接丢弃 `default_value`，默认值从未进入实体。
- 修复：`convert_rag_pipeline_variable` 在构造实体前把 `default_value`
  映射为 `default`（仅当 `default` 缺失时）。
- 挂载：api 与 worker 两个服务均挂载（与 base_app_generator.py 配套）。
- 适用镜像：`langgenius/dify-api:1.16.1`（容器内文件与
  `../../api/core/app/app_config/workflow_ui_based_app/variables/manager.py` 快照一致）。

## 升级注意

升级 dify-api 镜像后，需将新版镜像内被补丁覆盖的四个文件
（`/app/api/core/plugin/impl/datasource.py`、`/app/api/models/workflow.py`、
`/app/api/core/app/apps/base_app_generator.py`、
`/app/api/core/app/app_config/workflow_ui_based_app/variables/manager.py`）
与本补丁重新比对：

1. `docker compose up -d` 前先临时移除 compose 中对应的 volumes 条目，
   启动后将四个文件从容器中导出覆盖 `patches/` 下同名文件：
   `docker exec docker-api-1 cat <容器内路径> > patches/<文件名>`。
2. 分别检查新版是否已官方修复（`_get_local_file_datasource_provider` 是否
   带 `is_authorized`；`_resolve_workflow_app_tenant_id` 是否回退查询
   pipelines 表；`_validate_inputs` 必填缺失时是否回退默认值；
   `convert_rag_pipeline_variable` 是否映射 default_value）。
   已修复的可删除对应挂载条目。
3. 未修复的，在新文件上重新打补丁后再恢复挂载。
