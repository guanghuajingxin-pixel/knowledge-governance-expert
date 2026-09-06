# 知识治理专家重构 - 实施计划

> 任务按业务价值排序：智能问答 > 知识治理 > 知识采集 > 知识加工 > 运营看板 > 知识应用 > AI模型配置。Task 2（导航+路由）是所有视图的基础，需最先完成。

## Task 1: 归档 V3 原型 HTML
- **Status**: `completed`
- **Priority**: low
- **Depends On**: None
- **Description**:
  - 将 `/Users/hjx/.qwenworkcn/workspace/mtns9rknieg49qat/outputs/知识问答智能体原型V3.html` 复制到项目 `docs/` 目录。
- **Acceptance Criteria Addressed**: AC-9
- **Test Requirements**:
  - `rule` TR-1.1: `docs/知识问答智能体原型V3.html` 存在且非空；Evidence: `ls -la docs/`
- **Completion Evidence**:
  - 文件已复制到 `docs/知识问答智能体原型V3.html`（78059 字节）

## Task 2: 重组路由 + 侧边栏 + 顶栏
- **Status**: `completed`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - `router/index.ts`：新增 7 大模块路由。保留现有路由为隐藏入口。
  - `Sidebar.vue`：导航改为 V3 结构，分「功能区」与「平台配置」两组；底部保留知识中心入口。
  - `Header.vue` 顶栏：连接状态灯、北极星指标、反馈→治理脉冲条。
- **Acceptance Criteria Addressed**: AC-1, AC-8, AC-11
- **Test Requirements**:
  - `rule` TR-2.1: 侧边栏 7 大模块 + 平台管理分组，可路由
  - `rule` TR-2.2: 顶栏连接状态+准确率+脉冲条
  - `rule` TR-2.3: 原有路由仍可访问
- **Completion Evidence**:
  - 路由配置 `router/index.ts` 已更新，7 大模块路由已添加
  - 侧边栏显示「知识治理专家」+ 功能区（7模块）+ 平台配置分组 + 底部知识中心
  - 顶栏显示钉钉/Dify/模型网关连接灯 + 问答准确率 87.6% + 反馈→治理脉冲条
  - 浏览器验证：导航可点击路由，原有路由 /knowledge-bases /faq /search 仍可访问

## Task 3: 智能问答页增强（M1）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**: 重写 `views/chat/index.vue` 为 V3 风格。
- **Acceptance Criteria Addressed**: AC-2
- **Test Requirements**:
  - `rule` TR-3.1: 发送问题后展示回答+引用+元信息+反馈栏
  - `rule` TR-3.2: 模型切换/深度思考/KB开关可切换
  - `rule` TR-3.3: 建议词点击可填入发送
  - `rubric` TR-3.4: 问答页 UX 与 V3 一致度；threshold >=4
- **Completion Evidence**:
  - 页面渲染：问候语、输入框、模型选择器、深度思考开关、知识库检索开关、建议词条
  - 复用 `api/chat.ts` 真实问答 API，回答带引用来源与元信息
  - 无结果检测：召回为空时显示知识缺口提示+征集按钮
  - rubric TR-3.4 评分：4/5（布局与交互对齐 V3，引用展示复用现有结构）

## Task 4: 知识治理页（M2）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**: 新建 `views/governance/govern.vue`，4 个 Tab。
- **Acceptance Criteria Addressed**: AC-6
- **Test Requirements**:
  - `rule` TR-4.1: 工单分诊确认/改派后状态变更
  - `rule` TR-4.2: 质检/巡检/标准三 Tab 内容完整
- **Completion Evidence**:
  - 工单分诊表：4 条工单，点击「确认执行」后状态变为「已确认」（浏览器验证通过）
  - 质检台账、生命周期巡检、治理标准三个 Tab 内容完整展示
  - 3 个 KPI（分诊/回流/关单率）展示

## Task 5: 知识采集页（M3）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**: 新建 `views/governance/collection.vue`，3 个 Tab。
- **Acceptance Criteria Addressed**: AC-3
- **Test Requirements**:
  - `rule` TR-5.1: 上传触发预检，4 项可裁决，计数更新，可放行
  - `rule` TR-5.2: 同步源表+缺口表 Mock 数据完整
- **Completion Evidence**:
  - AI 预检：4 项检查（命名/元数据/重复/图注），每项可采纳/修改/驳回，计数更新
  - 同步源状态表：4 条同步源数据
  - 缺口与征集表：3 条缺口数据

## Task 6: 知识加工页（M4）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**: 新建 `views/governance/process.vue`，3 个 Tab。
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `rule` TR-6.1: 加工总览 KPI+流水线表
  - `rule` TR-6.2: 策略路由表 4 类知识类型
  - `rule` TR-6.3: 工具注册表含 7 类工具+跳转 URL
- **Completion Evidence**:
  - 加工总览：4 KPI + 6 步流水线表
  - 策略路由：4 类知识类型（制度/手册/FAQ/视频）
  - 工具注册表：7 个工具（Dify/同步后台/minerU/OCR/ASR/Rerank/模型网关）含管理入口 URL 与跳转按钮

## Task 7: 运营看板页（M5）
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 2
- **Description**: 新建 `views/governance/operate.vue`。
- **Acceptance Criteria Addressed**: AC-5
- **Test Requirements**:
  - `rule` TR-7.1: 4 KPI 数值展示
  - `rule` TR-7.2: 健康度表+Owner榜展示
- **Completion Evidence**:
  - 4 KPI：问答准确率 87.6%、活跃知识占比 71%、评测通过率 91.2%、Owner 响应率 86%
  - 健康度分布表：优秀/良好/待改进/风险 4 档
  - Owner 贡献榜：3 位 Owner 数据

## Task 8: 知识应用页（M6）
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 2
- **Description**: 新建 `views/governance/apply.vue`。
- **Acceptance Criteria Addressed**: AC-8（部分）
- **Test Requirements**:
  - `rule` TR-8.1: 三端卡片+问答日志表展示
- **Completion Evidence**:
  - 三端卡片：Dify 智能体、千问办公、人类门户
  - 问答日志表：4 条日志记录

## Task 9: AI 模型配置页（M7）
- **Status**: `completed`
- **Priority**: medium
- **Depends On**: Task 2
- **Description**: 新建 `views/governance/model.vue`。
- **Acceptance Criteria Addressed**: AC-7
- **Test Requirements**:
  - `rule` TR-9.1: 模型接入表+绑定表+用量表展示
  - `rule` TR-9.2: 提示词查看弹窗可打开
- **Completion Evidence**:
  - 模型接入表：5 个模型
  - 节点绑定表：6 个链路节点，含 temp/结构化输出/提示词
  - 点击「查看」按钮，提示词弹窗正常展示（浏览器验证通过）
  - 用量表：3 个模型用量数据

## Task 10: 类型检查 + 全页面冒烟验证
- **Status**: `completed`
- **Priority**: high
- **Depends On**: Task 1, 2, 3, 4, 5, 6, 7, 8, 9
- **Description**: type-check + 全页面验证。
- **Acceptance Criteria Addressed**: AC-8, AC-10
- **Test Requirements**:
  - `rule` TR-10.1: type-check 退出码 0
  - `rule` TR-10.2: 7 大模块页面无白屏
  - `rubric` TR-10.3: 整体 IA 与 V3 一致度；threshold >=4
- **Completion Evidence**:
  - `pnpm type-check` 通过，退出码 0，无 TS 错误
  - 7 大模块页面全部正常渲染，无白屏（浏览器验证通过）
  - 交互验证：工单分诊状态变更、提示词弹窗打开、预检裁决计数
  - rubric TR-10.3 评分：4/5（导航结构、模块划分、人机协作模式均对齐 V3 原型）
