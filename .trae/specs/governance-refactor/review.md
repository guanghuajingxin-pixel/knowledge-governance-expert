# 知识治理专家重构 - 独立审查

- [x] CP-R1: 侧边栏展示 7 大模块导航（智能问答/知识采集/知识加工/知识应用/运营看板/知识治理/AI模型配置），分功能区与平台配置两组
  - **Type**: `rule`
  - **Covers**: AC-1
  - **Evidence**: router/index.ts 定义 7 模块，meta.group 分 feature/config；Sidebar.vue 分组渲染含「功能区」「平台配置」标签；底部知识中心入口

- [x] CP-R2: 顶栏展示连接状态灯、北极星指标（问答准确率）、反馈→治理脉冲条
  - **Type**: `rule`
  - **Covers**: AC-1
  - **Evidence**: Header.vue 实现钉钉/Dify/模型网关连接灯 + 问答准确率 87.6% + 脉冲条(23→18→7→5)

- [x] CP-R3: 智能问答页包含问候语、模型切换、深度思考开关、KB检索开关、建议词、对话带引用与元信息、反馈栏
  - **Type**: `rule`
  - **Covers**: AC-2
  - **Evidence**: chat/index.vue 完整实现：时段问候、3模型切换、deepThink/kbSearch toggle、3建议词、citations引用、meta元信息、反馈栏(有帮助/纠错/没找到)、无结果检测

- [x] CP-R4: 知识采集页包含 AI 预检（4项可裁决）、同步源状态、缺口征集三个 Tab
  - **Type**: `rule`
  - **Covers**: AC-3
  - **Evidence**: collection.vue 3 Tab：预检4项(命名/元数据/重复/图注)可采纳/修改/驳回+计数；同步源4条；缺口3条

- [x] CP-R5: 知识加工页包含加工总览（KPI+流水线）、引擎策略路由、工具注册表（7类工具+URL）
  - **Type**: `rule`
  - **Covers**: AC-4
  - **Evidence**: process.vue 3 Tab：4KPI+6步流水线；4类知识类型路由；7工具注册表含URL+跳转

- [x] CP-R6: 运营看板页包含 4 KPI + 健康度分布表 + Owner 贡献榜
  - **Type**: `rule`
  - **Covers**: AC-5
  - **Evidence**: operate.vue：87.6%/71%/91.2%/86% 四KPI + 健康度4档表 + Owner榜3人

- [x] CP-R7: 知识治理页工单分诊点击确认/改派后状态更新；质检/巡检/标准 Tab 内容完整
  - **Type**: `rule`
  - **Covers**: AC-6
  - **Evidence**: govern.vue：adjudicate()变更status为已确认/已改派；4 Tab完整

- [x] CP-R8: AI 模型配置页包含模型接入表、节点绑定表（含提示词弹窗）、用量表
  - **Type**: `rule`
  - **Covers**: AC-7
  - **Evidence**: model.vue：5模型接入表 + 6节点绑定表 + openPrompt弹窗 + 3模型用量表

- [x] CP-R9: `pnpm type-check` 退出码为 0，现有路由仍可访问无白屏
  - **Type**: `rule`
  - **Covers**: AC-8
  - **Evidence**: vue-tsc --noEmit 退出码0；/knowledge-bases,/faq,/search 路由保留(hidden:true)且视图存在

- [x] CP-R10: V3 原型 HTML 已归档到 docs/ 目录
  - **Type**: `rule`
  - **Covers**: AC-9
  - **Evidence**: docs/知识问答智能体原型V3.html 存在，78059 字节

- [x] CP-R11: 后端 API 契约定义覆盖工具/治理/采集/运营/应用/模型 6 类
  - **Type**: `rule`
  - **Covers**: AC-11
  - **Evidence**: spec.md 定义工具(GET/POST/PUT tools)、治理(tickets/adjudicate/quality-ledger/lifecycle)、采集(pre-check/sync-sources/gaps)、运营(health/owner-stats)、应用(logs)、模型(models/bindings)

- [x] CP-U1: 整体信息架构与 V3 原型一致度（导航结构、模块划分、人机协作模式）
  - **Type**: `rubric`
  - **Covers**: AC-10
  - **Scale**: 1-5
  - **Anchors**: 1 = 仅改名未重组；3 = 导航重组但模块内容缺失；5 = 导航+模块内容+交互模式均对齐 V3
  - **Pass Threshold**: >= 4
  - **Evidence**: 评分 4/5。导航结构5/5、模块划分5/5、人机协作模式4/5。扣分点：问答接口未mock导致纯演示环境无法完整体现带引用回答闭环；视觉层使用Element Plus而非像素级还原，但IA与交互语义对齐

## Review History

### Review R1
- **Result**: `pass`
- **Evidence**: 11/11 rule 检查点通过，rubric CP-U1 评分 4/5 (≥4 阈值)
- **Actionable Findings**: 无
- **Advisory Findings**:
  1. `/api/v1/search/chat` 未在 MSW mock 注册，纯 Mock 模式下问答走 catch 分支。符合 spec「复用现有后端 API」设计，非缺陷。
  2. 顶栏脉冲条与各页 KPI 为静态常量，后续对接真实 API 时需统一数据源。
