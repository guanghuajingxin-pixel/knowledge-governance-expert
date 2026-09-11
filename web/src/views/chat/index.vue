<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount, computed, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { MagicStick, Search, User, ArrowUp, RefreshLeft, CopyDocument, EditPen, Delete } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { streamChat, cancelChat, type StreamEvent, type TokenUsage, type ChatResponse } from '@/api/chat'
import { listDifyDatasets, type DifyDataset } from '@/api/dify'
import { listEnabledLlmModels } from '@/api/settings'
import { getGreeting } from '@/api/agent'
import type { SearchResult } from '@/types/search'
import { citationUrl, linkEvidence } from '@/utils/chat-evidence'
import {
  listChatSessions, createChatSession, renameChatSession, deleteChatSession,
  getSessionMessages, saveChatTurn, type ChatSession,
} from '@/api/chat-sessions'
import { submitFeedback, ERROR_TYPES as QA_ERROR_TYPES } from '@/api/qa'
import { ElMessageBox } from 'element-plus'

const router = useRouter()

// Markdown 渲染：marked 解析 + DOMPurify 消毒（允许图片/视频标签）
marked.setOptions({ breaks: true, gfm: true })

// 允许 img / video / source / iframe 标签及 src 属性
const _purifyConfig = {
  ADD_TAGS: ['img', 'video', 'source', 'iframe'],
  ADD_ATTR: ['src', 'alt', 'title', 'width', 'height', 'controls', 'poster',
    'allow', 'allowfullscreen', 'frameborder', 'loading', 'referrerpolicy'],
}

// 流式节流：同一文本只解析一次，100ms 内跳过重复解析
let _lastMd = ''
let _lastHtml = ''
let _lastT = 0

function renderMd(md: string, citations?: SearchResult[]): string {
  if (!md) return ''
  // 节流：100ms 内且文本未变时返回缓存
  const cacheKey = `${md}§${JSON.stringify(citations?.map(c => [c.citation_id, citationUrl(c)]))}`
  const now = Date.now()
  if (cacheKey === _lastMd && now - _lastT < 100) return _lastHtml
  _lastMd = cacheKey
  _lastT = now
  // 预处理：修复 AI 常见的无空格标题（###标题 → ### 标题），不破坏代码块
  const fixed = linkEvidence(md, citations).replace(/^#{1,6}(?=[^\s#])/gm, '$& ')
  // 链接一律新窗口打开（文档预览链接 + 模型输出的外链）
  _lastHtml = DOMPurify.sanitize(marked.parse(fixed) as string, _purifyConfig)
    .replace(/<a /g, '<a target="_blank" rel="noopener"')
  return _lastHtml
}

// 状态
const query = ref('')
const datasets = ref<DifyDataset[]>([])
const selectedDatasetIds = ref<string[]>([])
const datasetsError = ref('')
// 仅展示系统配置中「生效」的模型；is_default 为新会话默认模型
const modelOptions = ref<Array<{ model: string; profile_id: string; profile_name: string; is_default: boolean }>>([])
const selectedModel = ref('')
const selectedProfileId = ref('')

// 用户上次手动选择的模型（本地记忆，优先于默认模型）
const MODEL_PREF_KEY = 'chat.selectedModel'

// 智能体配置中已配置的模型（非空时问答页只能从中选择，不展示系统全部模型）
const agentModels = ref<string[]>([])

function pickModel(modelName: string) {
  const opt = modelOptions.value.find((o) => o.model === modelName)
  selectedModel.value = opt?.model || modelName
  selectedProfileId.value = opt?.profile_id || ''
  if (opt) localStorage.setItem(MODEL_PREF_KEY, modelName)
}
const deepThink = ref(false)
const kbSearch = ref(true)
const dsPopoverVisible = ref(false)
// 当前流式请求的中断句柄（streamChat 返回的 abort 函数）；运行中点停止按钮调用
let abortCurrent: (() => void) | null = null

// 数据集全选 / 半选状态
const isAllSelected = computed(
  () => datasets.value.length > 0 && selectedDatasetIds.value.length === datasets.value.length,
)
const isIndeterminate = computed(
  () =>
    selectedDatasetIds.value.length > 0 &&
    selectedDatasetIds.value.length < datasets.value.length,
)
function toggleAllDatasets(val: any) {
  selectedDatasetIds.value = val ? datasets.value.map((d) => d.id) : []
}
function closeKbSearch() {
  kbSearch.value = false
  dsPopoverVisible.value = false
}

// 对话
interface StepItem {
  title: string
  detail: string
  done: boolean
}
interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  citations?: SearchResult[]
  quality?: ChatResponse['quality']
  answerStatus?: string
  meta?: string
  noResult?: boolean
  configError?: string
  steps?: StepItem[]
  followUps?: string[]
  /** 本轮是否已结束（final/error/choice_pause），用于等待逻辑 */
  done?: boolean
  time?: string
  /** 步骤是否展开（运行中/完成后均可点击切换） */
  stepsExpanded?: boolean
  /** 限时探索确认卡片：智能体暂停等待用户点选「继续探索/先这样回答」 */
  choice?: { question: string; options: string[]; answered: boolean }
  /** 本轮 Token 消耗（模型接口 usage） */
  usage?: TokenUsage
  /** 持久化后的助手消息 ID（用于点赞/纠错反馈关联） */
  dbId?: string
  /** 已提交的反馈：helpful | correct | notfound */
  feedback?: 'helpful' | 'correct' | 'notfound'
}
const messages = ref<ChatMsg[]>([])
const hasAsked = ref(false)

// 会话历史（DB 持久化，按会话隔离；DeerFlow thread 也按 session UUID 隔离）
const sessions = ref<ChatSession[]>([])
const currentSession = ref<ChatSession | null>(null)
const historyLoading = ref(false)
const scrollRef = ref<HTMLElement | null>(null)

// ============ 多会话并行运行 ============
// 运行注册表：sid → 运行态。回答跨会话并行进行，切换会话不中断；
// 当前查看的会话是否「运行中」由 loading 计算属性派生（按钮停止态/输入禁用等沿用）。
const MAX_CONCURRENT = 5
interface RunState {
  msg: ChatMsg
  abort: () => void
  status: 'running' | 'choice'
  model: string
}
const runs = reactive(new Map<string, RunState>())
// reactive Map 读取会返回响应式代理，与原始对象严格比较恒为 false；
// 身份判断必须经 toRaw 归一（否则运行状态永不收敛：转圈不落点、完成不清理）
const isRun = (sid: string, run: RunState) => {
  const cur = runs.get(sid)
  return !!cur && toRaw(cur) === toRaw(run)
}
// 有进行中/新完成回答的会话 → 内存消息数组（切回时优先展示，保留流式交互态，不被 DB 加载覆盖）
const liveArrays = new Map<string, ChatMsg[]>()
// 多轮改写上下文（last_query/last_answer）按会话隔离，避免并行会话互相污染
const sessionCtx = new Map<string, { q: string; a: string }>()
// 本页生命周期内完成过回答的会话（绿点提示；打开该会话后清除）
const finishedSids = reactive(new Set<string>())
const activeRunCount = computed(() => [...runs.values()].filter((r) => r.status === 'running').length)
const loading = computed(() => !!currentSession.value && runs.get(currentSession.value.id)?.status === 'running')

// 智能体配置（开场白/建议词/开关，来自 /agent/greeting）
const greetingText = ref('你好！我是杰克百晓生，公司知识问答助手。')
const suggestions = ref<string[]>([])
const followUpEnabled = ref(true)
const longMemoryEnabled = ref(true)

// 新消息 / 流式步骤追加时滚动到底部（第一条消息仍从顶部开始）
function scrollToBottom() {
  nextTick(() => {
    const el = scrollRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

// 会话上下文（用于多轮改写）已按会话隔离：见 sessionCtx（多会话并行时互不污染）

onMounted(async () => {
  await Promise.all([loadDatasets(), (async () => { await loadGreeting(); await loadModels() })(), loadSessions()])
})

// 离开页面：中断所有进行中的回答（后端感知断连后停止 agent，避免空转耗 token）
onBeforeUnmount(() => {
  for (const r of runs.values()) r.abort?.()
  runs.clear()
  abortCurrent?.()
  abortCurrent = null
})

// ============ 会话历史 ============
async function loadSessions(selectId?: string) {
  try {
    sessions.value = await listChatSessions()
  } catch {
    sessions.value = []
    return
  }
  // 默认进入最近一次会话；指定 selectId 时切换
  const target = selectId
    ? sessions.value.find((s) => s.id === selectId)
    : sessions.value[0]
  if (target) {
    await selectSession(target.id, false)
  } else {
    resetToWelcome()
  }
}

function resetToWelcome() {
  messages.value = []
  hasAsked.value = false
  query.value = ''
  currentSession.value = null
}

async function newSession() {
  // 运行中的会话继续后台执行（不中断），仅回到欢迎页
  resetToWelcome()
}

/** 中断指定会话（缺省为当前会话）的回答：通知后端停止 agent + abort SSE，标记消息为已中断 */
function stopRun(sid?: string) {
  const target = sid || currentSession.value?.id
  if (!target) return
  const run = runs.get(target)
  if (!run) return
  runs.delete(target)
  // 确定性通知后端中断（不依赖 SSE 断连检测时机），fire-and-forget
  void cancelChat(target)
  run.abort?.()
  const m = run.msg
  m.done = true
  if (m.steps && m.steps.length) m.steps[m.steps.length - 1].done = true
  if (m.choice) m.choice.answered = true
  if (!m.content && !m.choice) m.content = '（已中断本次回答）'
  m.meta = `⏹ 已中断 · ${run.model}`
  if (currentSession.value?.id === target) scrollToBottom()
}

async function selectSession(id: string, needCheck = true) {
  if (currentSession.value?.id === id && needCheck) return
  // 切换会话**不中断**运行中的回答（runs 注册表继续持有 SSE 连接与消息对象）
  // 有进行中/新完成回答的会话：优先展示内存消息数组（含流式交互态），不被 DB 记录覆盖
  const live = liveArrays.get(id)
  if (live) {
    currentSession.value = sessions.value.find((s) => s.id === id) || currentSession.value
    if (currentSession.value?.id !== id) return
    messages.value = live
    finishedSids.delete(id)
    hasAsked.value = live.length > 0
    query.value = ''
    scrollToBottom()
    return
  }
  finishedSids.delete(id)
  historyLoading.value = true
  try {
    const res = await getSessionMessages(id)
    currentSession.value = res.session
    messages.value = res.messages.map((m) => ({
      role: m.role as 'user' | 'assistant',
      content: m.content,
      done: true,
      time: m.created_at ? m.created_at.slice(11, 16) : '',
      meta: m.meta || undefined,
      dbId: m.role === 'assistant' ? m.id : undefined,
      steps: m.detail?.steps as any,
      quality: m.detail?.quality,
      answerStatus: m.detail?.answer_status,
      citations: m.citations
        ? m.citations.map((t) => {
            // 新格式：JSON 字符串（含 url/node_id/extension）；旧格式：纯标题
            try {
              const o = JSON.parse(t)
              if (o && typeof o === 'object' && o.t) {
                return { ...o, document_title: o.t, url: o.u || '', node_id: o.n || '', extension: o.e || '' } as SearchResult
              }
            } catch { /* 纯标题，走默认 */ }
            return { document_title: t } as SearchResult
          })
        : undefined,
    }))
    hasAsked.value = messages.value.length > 0
    sessionCtx.set(id, { q: res.session.last_query || '', a: res.session.last_answer || '' })
    query.value = ''
    scrollToBottom()
  } finally {
    historyLoading.value = false
  }
}

async function removeSession(id: string) {
  await ElMessageBox.confirm('确认删除该会话？删除后不可恢复。', '删除会话', { type: 'warning' })
  await deleteChatSession(id)
  ElMessage.success('已删除')
  // 清理该会话的运行态与内存消息（运行中删除 = 中断该会话回答）
  stopRun(id)
  liveArrays.delete(id)
  finishedSids.delete(id)
  sessionCtx.delete(id)
  if (currentSession.value?.id === id) {
    resetToWelcome()
  }
  await loadSessions(currentSession.value?.id)
}

async function renameSession(s: ChatSession) {
  const { value } = await ElMessageBox.prompt('请输入新的会话标题', '重命名会话', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    inputValue: s.title,
  })
  const title = (value || '').trim()
  if (!title) return
  await renameChatSession(s.id, title)
  if (currentSession.value?.id === s.id) currentSession.value.title = title
  await loadSessions(currentSession.value?.id)
}

async function loadGreeting() {
  try {
    const g = await getGreeting()
    greetingText.value = g.greeting_enabled ? (g.greeting || '你好！我是企业知识问答助手。') : ''
    suggestions.value = g.suggested_questions || []
    followUpEnabled.value = g.follow_up_enabled
    longMemoryEnabled.value = g.long_memory_enabled
    deepThink.value = !!g.deep_think_default
    // 问答页模型下拉仅展示智能体配置中已配置的模型；
    // 用系统生效模型补全 profile 信息与「默认」标记，便于识别
    if (g.models && g.models.length) {
      agentModels.value = g.models
      let sys: Array<{ profile_id: string; profile_name: string; model: string; is_default: boolean }> = []
      try {
        sys = (await listEnabledLlmModels()).models || []
      } catch {
        /* 系统模型信息拉取失败时仅显示模型名 */
      }
      modelOptions.value = g.models.map((name: string) => {
        const hit = sys.find((o) => o.model === name)
        return { model: name, profile_id: hit?.profile_id || '', profile_name: hit?.profile_name || '', is_default: !!hit?.is_default }
      })
      const pref = localStorage.getItem(MODEL_PREF_KEY)
      const target = (pref && g.models.includes(pref)) ? pref
        : modelOptions.value.find((o) => o.is_default)?.model || g.models[0]
      pickModel(target)
    }
  } catch {
    /* 未登录/接口异常时使用默认欢迎语 */
  }
}

async function loadModels() {
  // 智能体已配置模型时，问答页只能从中选择，不回退到系统全部模型
  if (agentModels.value.length) return
  try {
    const res = await listEnabledLlmModels()
    const opts = res.models || []
    if (opts.length) {
      modelOptions.value = opts.map((m) => ({
        model: m.model,
        profile_id: m.profile_id,
        profile_name: m.profile_name,
        is_default: m.is_default,
      }))
      // 选中优先级：本地记忆的上次选择 → 默认模型 → 第一个
      const pref = localStorage.getItem(MODEL_PREF_KEY)
      const target = opts.find((o) => o.model === pref)
        || opts.find((o) => o.is_default)
        || opts[0]
      pickModel(target.model)
    } else {
      // 未配置生效模型时给占位，引导去系统配置
      modelOptions.value = [{ model: '（未配置 LLM）', profile_id: '', profile_name: '', is_default: false }]
      selectedModel.value = '（未配置 LLM）'
      selectedProfileId.value = ''
    }
  } catch {
    modelOptions.value = [{ model: '（未配置 LLM）', profile_id: '', profile_name: '', is_default: false }]
    selectedModel.value = '（未配置 LLM）'
    selectedProfileId.value = ''
  }
}

async function loadDatasets() {
  datasetsError.value = ''
  try {
    const res = await listDifyDatasets()
    datasets.value = res.items || []
    if (res.error) datasetsError.value = res.error
    // 默认全选，用户可在下拉中按需取消
    selectedDatasetIds.value = datasets.value.map((d) => d.id)
  } catch (e: any) {
    datasetsError.value = e?.message || '加载失败'
    datasets.value = []
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSendClick()
  }
}

function askSugg(q: string) {
  if (loading.value) return
  query.value = q
  handleAsk()
}

/** 发送按钮点击：运行中为「停止」（中断回答），空闲时为「发送」 */
function handleSendClick() {
  if (loading.value) {
    stopRun()
    return
  }
  handleAsk()
}

function handleAsk() {
  const q = query.value.trim()
  if (!q) return
  if (kbSearch.value && selectedDatasetIds.value.length === 0 && datasets.value.length) {
    ElMessage.warning('请至少选择一个 Dify 数据集')
    return
  }
  query.value = ''
  return askQuestion(q)
}

/** Token 数紧凑展示：≥1000 显示为 x.xk */
function fmtTok(n?: number): string {
  const v = Number(n || 0)
  if (v <= 0) return '0'
  return v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)
}

/** 限时探索确认按钮：点选后以用户消息续跑（continue/stop） */
function chooseOption(msgIdx: number, opt: string) {
  const msg = messages.value[msgIdx]
  if (!msg.choice || msg.choice.answered || loading.value) return
  msg.choice.answered = true
  const action: 'continue' | 'stop' = opt.includes('继续') ? 'continue' : 'stop'
  askQuestion(opt, action)
}

async function askQuestion(q: string, action: '' | 'continue' | 'stop' = '') {
  if (!action && kbSearch.value && selectedDatasetIds.value.length === 0 && datasets.value.length) {
    ElMessage.warning('请至少选择一个 Dify 数据集')
    return
  }
  // 并发上限：最多 5 个会话同时问答（choice 等待确认不占后端并发）
  if (!action && activeRunCount.value >= MAX_CONCURRENT) {
    ElMessage.warning(`最多支持 ${MAX_CONCURRENT} 个会话并行问答，请等待部分会话完成后再发送`)
    return
  }
  // 同一会话不允许重复发送（运行中点发送按钮已是停止语义）
  const sid0 = currentSession.value?.id || ''
  if (!action && sid0 && runs.get(sid0)?.status === 'running') {
    ElMessage.warning('当前会话正在回答中，可点击停止按钮中断后再发送')
    return
  }
  hasAsked.value = true
  messages.value.push({ role: 'user', content: q, time: nowTime() })

  // 首问时创建 DB 会话：会话 UUID 同时作为 DeerFlow thread 隔离键与记忆文档归属
  if (!currentSession.value) {
    try {
      currentSession.value = await createChatSession('新会话')
      sessions.value.unshift(currentSession.value)
    } catch {
      /* 创建失败时退化为匿名会话（不持久化），不阻断问答 */
    }
  }

  // 助手占位消息：步骤列表随流式事件实时追加
  // reactive 对象：切换会话后闭包仍直接更新同一对象，切回时视图即时呈现
  const assistantMsg = reactive<ChatMsg>({
    role: 'assistant',
    content: '',
    citations: [],
    meta: selectedModel.value,
    steps: [],
    time: nowTime(),
  })
  messages.value.push(assistantMsg)
  // 捕获本轮会话 ID：中断后即使切换了会话，持久化仍写入本轮所属会话
  const sid = currentSession.value?.id || ''
  const persistSessionId = sid
  // 多轮改写上下文按会话隔离（并行会话互不污染）
  const ctx = sessionCtx.get(sid) || { q: '', a: '' }
  sessionCtx.set(sid, ctx)
  // 登记运行态：跨会话并行，切换会话不中断
  const run: RunState = { msg: assistantMsg, abort: () => {}, status: 'running', model: selectedModel.value }
  if (sid) {
    runs.set(sid, run)
    liveArrays.set(sid, messages.value)
  }
  const viewActive = () => currentSession.value?.id === sid
  scrollToBottom()

  // 长期记忆：携带最近 3 轮问答（开启时）
  const history = longMemoryEnabled.value
    ? messages.value
        .filter((m) => m.content)
        .slice(-6)
        .map((m) => ({ role: m.role, content: m.content }))
    : []

  abortCurrent = streamChat(
    {
      query: q,
      dify_dataset_ids: kbSearch.value ? (selectedDatasetIds.value.length ? selectedDatasetIds.value : null) : [],
      last_query: ctx.q,
      last_answer: ctx.a,
      history,
      model: selectedModel.value,
      llm_profile_id: selectedProfileId.value,
      deep_think: deepThink.value,
      session_id: sid,
      action,
    },
    {
      onStep: (e: StreamEvent) => {
        const msg = assistantMsg
        if (!msg.steps) msg.steps = []
        // 标记上一步为完成
        if (msg.steps.length) msg.steps[msg.steps.length - 1].done = true
        msg.steps.push({ title: e.title || e.node || '', detail: e.detail || '', done: false })
        // 执行中实时展示步骤流（首个步骤到达即显示）
        if (viewActive()) scrollToBottom()
      },
      onDelta: (delta) => {
        const msg = assistantMsg
        msg.content = (msg.content || '') + delta
        if (viewActive()) scrollToBottom()
      },
      onChoice: (question, options) => {
        // 确认按钮卡片先渲染（流可能还在收尾），暂停落定前按钮不可点
        const msg = assistantMsg
        msg.choice = { question, options: options.length ? options : ['继续探索', '先基于已检索内容回答'], answered: false }
        if (viewActive()) scrollToBottom()
      },
      onChoicePause: (question, options, usage) => {
        const msg = assistantMsg
        msg.done = true
        if (msg.steps && msg.steps.length) msg.steps[msg.steps.length - 1].done = true
        msg.choice = { question, options: options.length ? options : ['继续探索', '先基于已检索内容回答'], answered: false }
        if (usage && usage.total_tokens > 0) msg.usage = usage
        msg.meta = `🦌 DeerFlow · 等待确认 · ${run.model}`
        // 流已结束：转为「等待确认」态（不占后端并发），用户点选后发起新请求续跑
        if (runs.get(sid) === run) run.status = 'choice'
        if (viewActive()) scrollToBottom()
      },
      onFinal: (res) => {
        const msg = assistantMsg
        msg.done = true
        // 完成：最后一步标记完成，过程条自动收起（用户可点击展开）
        if (msg.steps && msg.steps.length) msg.steps[msg.steps.length - 1].done = true
        const citations = res.citations || []
        const configError = res.config_error || ''
        const noResult = res.answer_status === 'insufficient'
        const thinkTag = deepThink.value ? '深度思考 · ' : ''
        if (res.usage && res.usage.total_tokens > 0) msg.usage = res.usage
        if (citations.length > 0) {
          msg.meta = `${thinkTag}企业知识问答 · ${citations.length} 条原文依据 · ${run.model}`
        } else if (res.answer) {
          msg.meta = `${thinkTag}企业知识问答 · ${run.model}`
        } else {
          msg.meta = `${thinkTag}未在知识库找到相关内容 · ${run.model}`
        }
        if (res.answer) msg.content = res.answer
        else if (!msg.content) msg.content = '（未生成回答）'
        msg.quality = res.quality
        msg.answerStatus = res.answer_status
        msg.citations = citations
        msg.noResult = noResult
        msg.configError = configError
        msg.followUps = followUpEnabled.value ? res.follow_ups || [] : []
        if (!configError) {
          if (res.last_query) ctx.q = res.last_query
          else if (res.rewritten_query) ctx.q = res.rewritten_query
          ctx.a = res.last_answer ?? ''
        }
        // 运行结束：出注册表；绿点提示（查看该会话时立即清除）
        if (isRun(sid, run)) runs.delete(sid)
        finishedSids.add(sid)
        if (viewActive()) scrollToBottom()
      },
      onError: (code, message) => {
        const msg = assistantMsg
        msg.done = true
        if (msg.steps && msg.steps.length) msg.steps[msg.steps.length - 1].done = true
        msg.configError = code
        msg.meta = code === 'llm_not_configured' || code === 'dify_not_configured'
          ? '需要先完成系统配置'
          : '⚠️ 回答失败，可重试'
        msg.content = message || '问答请求失败，请稍后重试。'
        if (isRun(sid, run)) runs.delete(sid)
        finishedSids.add(sid)
        if (viewActive()) scrollToBottom()
      },
      onClosed: () => {
        // 流异常收尾（未收到 final/choice_pause/config_error）：收尾运行态，避免永久「转圈」
        const msg = assistantMsg
        if (!msg.done && !msg.configError) {
          msg.done = true
          if (msg.steps && msg.steps.length) msg.steps[msg.steps.length - 1].done = true
          if (!msg.content && !msg.choice) msg.content = '（连接中断，回答未完成）'
          msg.meta = `⚠️ 连接中断 · ${run.model}`
        }
        if (runs.get(sid) === run) runs.delete(sid)
        finishedSids.add(sid)
        if (viewActive()) scrollToBottom()
      },
    },
  )
  // 中断句柄挂到运行态（停止按钮/切换清理用），并保留全局兜底引用
  run.abort = abortCurrent
  // 轮询等待 final 或 error（DeerFlow 模式下 content 会随 delta 提前出现，不能以 content 为准）
  const waitDone = () =>
    new Promise<void>((resolve) => {
      const t = setInterval(() => {
        if (assistantMsg.done || assistantMsg.configError || !isRun(sid, run)) {
          clearInterval(t)
          resolve()
        }
      }, 200)
    })
  await waitDone()
  // 等待确认态的 run 必须保留（侧栏琥珀点 + 点选续跑）；仅真正结束时出注册表
  if (isRun(sid, run) && run.status !== 'choice') runs.delete(sid)
  abortCurrent = null

  // 持久化本轮问答到会话（消息 + 记忆文档由后端滚动更新）。
  // 用本轮捕获的会话 ID 与消息对象：中断后用户可能已切换会话，
  // 不能再读 currentSession.value / messages.value[msgIdx]（会指到新会话）。
  if (persistSessionId && !assistantMsg.configError) {
    const finalMsg = assistantMsg
    // 限时探索暂停轮：无答案文本，用确认问题作为助手消息内容留存
    const persistAnswer = finalMsg.content
      || (finalMsg.choice ? `🙋 ${finalMsg.choice.question}` : '')
    try {
      const turnRes = await saveChatTurn(persistSessionId, {
        question: q,
        answer: persistAnswer,
        citations: (finalMsg.citations || [])
          .map((c) => {
            return JSON.stringify({ ...c, t: c.document_title, u: c.url || c.preview_url || '',
              n: c.node_id || '', e: c.extension || '' })
          })
          .filter(Boolean),
        meta: finalMsg.meta || '',
        last_query: ctx.q,
        last_answer: ctx.a,
        // 回答链路 + 召回片段快照，供「问答明细」展示
        detail: {
          quality: finalMsg.quality,
          answer_status: finalMsg.answerStatus,
          steps: (finalMsg.steps || []).map((s) => ({ title: s.title, detail: s.detail, done: s.done })),
          retrieval: (finalMsg.citations || []).map((c) => ({
            document_title: c.document_title,
            text: (c as any).text || '',
            score: (c as any).score,
            chunk_id: (c as any).chunk_id || '',
            chunk_index: (c as any).chunk_index,
            page_number: (c as any).page_number ?? null,
            url: (c as any).url || (c as any).preview_url || '',
          })),
          model: selectedModel.value,
        },
      })
      finalMsg.dbId = turnRes.assistant_message_id
      // 首问后标题变为问题，仅刷新侧边栏列表；
      // 不能 loadSessions() 全量重载消息——那会用 DB 记录替换内存消息，
      // 导致限时探索的 choice 按钮对象与 token usage 等交互态丢失。
      await refreshSessionList()
    } catch {
      /* 持久化失败不影响界面 */
    }
  }
}

/** 只刷新侧边栏会话列表（标题/排序），不重载当前对话消息，保留交互态。 */
async function refreshSessionList() {
  try {
    const list = await listChatSessions()
    sessions.value = list
    if (currentSession.value) {
      const fresh = list.find((s: ChatSession) => s.id === currentSession.value!.id)
      if (fresh) currentSession.value.title = fresh.title
    }
  } catch {
    /* 列表刷新失败不影响界面 */
  }
}

// 引用展开：默认只显示前 5 条，可展开全部
const MAX_REFS = 5
const expandedRefs = ref<Set<number>>(new Set())

// 步骤展开/收起切换
function toggleSteps(i: number) {
  const msg = messages.value[i]
  msg.stepsExpanded = !msg.stepsExpanded
}
function toggleRefs(i: number) {
  if (expandedRefs.value.has(i)) expandedRefs.value.delete(i)
  else expandedRefs.value.add(i)
}

function copyText(text: string) {
  navigator.clipboard.writeText(text).then(() => ElMessage.success('已复制')).catch(() => ElMessage.error('复制失败'))
}

function editQuestion(text: string) {
  query.value = text
  const el = document.querySelector('.input-field') as HTMLTextAreaElement | null
  if (el) {
    el.focus()
    el.setSelectionRange(text.length, text.length)
  }
}

function nowTime() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// 重新对话：清空消息回到欢迎态（下一首问时创建新会话与新 DeerFlow thread）
function restart() {
  resetToWelcome()
}

function goToConfig() {
  router.push('/model')
}

// ===== 问答反馈（点赞/纠错/没找到，持久化到 qa_feedbacks） =====
const corrVisible = ref(false)
const corrSubmitting = ref(false)
const corrForm = reactive({ error_type: '内容错误', knowledge_title: '', knowledge_url: '', content: '' })
const corrTarget = ref<{ m?: ChatMsg; question: string }>({ question: '' })

function questionOf(m: ChatMsg): string {
  const idx = messages.value.indexOf(m)
  for (let k = idx - 1; k >= 0; k--) {
    if (messages.value[k].role === 'user') return messages.value[k].content
  }
  return ''
}

async function feedback(
  type: 'helpful' | 'correct' | 'notfound',
  m?: ChatMsg,
  cite?: { document_title?: string; url?: string; preview_url?: string },
) {
  if (!m) return
  if (m.feedback) {
    ElMessage.info('本条已反馈过，感谢您的参与')
    return
  }
  const question = questionOf(m)
  if (type === 'correct') {
    // 纠错：弹窗收集错误类型/知识标题/说明，生成工单
    corrTarget.value = { m, question }
    corrForm.error_type = '内容错误'
    // 从引用来源点击纠错：自动带入该条知识的名称与链接（钉钉外链 url 或本地预览 preview_url）
    corrForm.knowledge_title = cite?.document_title || m.citations?.[0]?.document_title || ''
    corrForm.knowledge_url = cite?.url || cite?.preview_url || m.citations?.[0]?.url || m.citations?.[0]?.preview_url || ''
    corrForm.content = ''
    corrVisible.value = true
    return
  }
  try {
    await submitFeedback({
      feedback_type: type,
      session_id: currentSession.value?.id,
      message_id: m.dbId,
      question,
    })
    m.feedback = type
    ElMessage.success(type === 'helpful' ? '已记录「有帮助」，感谢反馈' : '已记录「没找到」，将用于知识缺口分析')
  } catch (e: any) {
    ElMessage.error(e?.message || '反馈失败，请稍后重试')
  }
}

async function submitCorrection() {
  const { m, question } = corrTarget.value
  if (!m) return
  if (!corrForm.knowledge_title.trim() && !corrForm.content.trim()) {
    ElMessage.warning('请填写知识标题或纠错说明')
    return
  }
  corrSubmitting.value = true
  try {
    await submitFeedback({
      feedback_type: 'correct',
      session_id: currentSession.value?.id,
      message_id: m.dbId,
      knowledge_title: corrForm.knowledge_title,
      knowledge_url: corrForm.knowledge_url,
      error_type: corrForm.error_type,
      content: corrForm.content,
      question,
    })
    m.feedback = 'correct'
    corrVisible.value = false
    ElMessage.success('纠错已提交，知识管理员将在「知识运营-知识纠错」中跟进')
  } catch (e: any) {
    ElMessage.error(e?.message || '提交失败，请稍后重试')
  } finally {
    corrSubmitting.value = false
  }
}
</script>

<template>
  <div class="chat-page">
    <!-- 会话历史侧边栏 -->
    <aside class="history-panel">
      <button type="button" class="new-chat-btn" @click="newSession">
        <el-icon><RefreshLeft /></el-icon> 新建会话
      </button>
      <div class="history-title">会话历史</div>
      <div v-loading="historyLoading" class="history-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="history-item"
          :class="{ active: currentSession?.id === s.id }"
          @click="selectSession(s.id)"
        >
          <span v-if="runs.get(s.id)?.status === 'running'" class="run-spinner" title="回答进行中"></span>
          <span v-else-if="runs.get(s.id)" class="run-choice-dot" title="等待确认：打开会话完成选择"></span>
          <span
            v-else-if="finishedSids.has(s.id) && s.id !== currentSession?.id"
            class="run-done-dot"
            title="有新完成的回答"
          ></span>
          <span class="history-name">{{ s.title }}</span>
          <span class="history-ops" @click.stop>
            <el-tooltip content="重命名" placement="top">
              <el-icon class="op-icon" @click="renameSession(s)"><EditPen /></el-icon>
            </el-tooltip>
            <el-tooltip content="删除" placement="top">
              <el-icon class="op-icon op-del" @click="removeSession(s.id)"><Delete /></el-icon>
            </el-tooltip>
          </span>
        </div>
        <div v-if="!sessions.length && !historyLoading" class="history-empty">暂无历史会话</div>
      </div>
    </aside>

    <div class="chat-card">
      <!-- 聊天头部：助手身份卡 -->
      <header class="chat-header">
        <div class="assistant-identity">
          <div class="assistant-avatar"><el-icon><MagicStick /></el-icon></div>
          <div class="assistant-meta">
            <span class="assistant-name">杰克百晓生</span>
            <span class="assistant-status">
              <span class="status-dot" :class="{ busy: loading }"></span>
              {{ loading ? '正在思考…' : '在线 · 随时解答' }}
            </span>
          </div>
        </div>
        <div class="header-actions">
          <button type="button" class="icon-btn" title="重新对话" @click="restart">
            <el-icon><RefreshLeft /></el-icon>
          </button>
        </div>
      </header>

      <!-- 消息滚动区 -->
      <div ref="scrollRef" class="chat-scroll">
        <!-- 欢迎空状态 -->
        <div v-if="!hasAsked" class="welcome">
          <h1 v-if="greetingText" class="welcome-title">{{ greetingText }}</h1>
          <p class="welcome-subtitle">我可以基于企业知识库回答问题，答案附带引用溯源。</p>
          <div v-if="datasetsError" class="warn-tip">
            ⚠️ Dify 知识库加载失败：{{ datasetsError }}，请到「系统配置」页配置 Dify 服务地址与 API Key。
          </div>
          <div v-else-if="!datasets.length" class="warn-tip">
            尚未加载到 Dify 数据集，请到「系统配置」页配置 Dify 并保存后回到本页。
          </div>
        </div>

        <!-- 消息列表 -->
        <div v-else class="chat-area">
          <div v-for="(m, i) in messages" :key="i" class="message" :class="m.role === 'user' ? 'message--user' : 'message--assistant'">
            <!-- 头像 -->
            <div class="message__avatar" :class="m.role === 'user' ? 'avatar--user' : 'avatar--ai'">
              <el-icon><User v-if="m.role === 'user'" /><MagicStick v-else /></el-icon>
            </div>
            <div class="message__col">
              <!-- 用户消息 -->
              <template v-if="m.role === 'user'">
                <div class="message__bubble bubble--user">
                  <span class="bubble-text">{{ m.content }}</span>
                  <!-- 悬停整行时显示：复制 / 编辑 / 时间，离开隐藏 -->
                  <div class="msg-meta">
                    <span class="msg-actions">
                      <el-tooltip content="复制" placement="top">
                        <el-icon class="msg-act-icon" @click="copyText(m.content)"><CopyDocument /></el-icon>
                      </el-tooltip>
                      <el-tooltip content="编辑" placement="top">
                        <el-icon class="msg-act-icon" @click="editQuestion(m.content)"><EditPen /></el-icon>
                      </el-tooltip>
                    </span>
                    <span class="msg-time">{{ m.time }}</span>
                  </div>
                </div>
              </template>

              <!-- 助手消息 -->
              <template v-else>
                <!-- typing 圆点（首个步骤到达前） -->
                <div v-if="!(m.steps && m.steps.length) && !m.content && !m.configError" class="typing-bubble">
                  <span class="typing-dot"></span>
                  <span class="typing-dot"></span>
                  <span class="typing-dot"></span>
                </div>

                <!-- 检索过程：运行中显示当前步骤（点击可展开全部），问答结束后仍可随时展开/收起 -->
                <div
                  v-if="m.steps && m.steps.length"
                  class="steps-bar"
                  :class="{ 'steps-bar--live': !m.done }"
                >
                  <div class="steps-bar__header" @click="toggleSteps(i)">
                    <template v-if="!m.done && !m.stepsExpanded">
                      <span class="step-spinner"></span>
                      <span class="step-live-title">{{ m.steps[m.steps.length - 1]?.title }}</span>
                      <span class="step-live-detail">{{ m.steps[m.steps.length - 1]?.detail }}</span>
                      <span class="steps-expand-hint">▸ 展开过程</span>
                    </template>
                    <template v-else>
                      <span class="steps-bar__label">
                        {{ m.stepsExpanded ? '▾' : '▸' }} 智能体检索过程 · 共 {{ m.steps.length }} 步{{ !m.done ? '（进行中…）' : '' }}
                      </span>
                      <span v-if="!m.done" class="step-spinner step-spinner--right"></span>
                    </template>
                  </div>
                  <div v-if="m.stepsExpanded" class="steps-bar__body">
                    <div
                      v-for="(st, si) in m.steps"
                      :key="si"
                      class="step-item"
                      :class="{ done: si < m.steps.length - 1 || m.done }"
                    >
                      <span class="step-dot">
                        <span v-if="si === m.steps.length - 1 && !m.done" class="step-spinner step-spinner--mini"></span>
                        <template v-else>✓</template>
                      </span>
                      <span class="step-title">{{ st.title }}</span>
                      <span class="step-detail">{{ st.detail }}</span>
                    </div>
                  </div>
                </div>

                <!-- 限时探索确认卡片：智能体暂停等待用户选择是否继续 -->
                <div v-if="m.choice" class="choice-card">
                  <div class="choice-q">🙋 {{ m.choice.question }}</div>
                  <div class="choice-opts">
                    <button
                      v-for="(opt, oi) in m.choice.options"
                      :key="oi"
                      type="button"
                      class="choice-btn"
                      :class="{ 'choice-btn--primary': opt.includes('继续') }"
                      :disabled="m.choice.answered || loading"
                      @click="chooseOption(i, opt)"
                    >{{ opt }}</button>
                  </div>
                </div>

                <!-- 答案 / 配置提示 / 知识缺口 -->
                <div v-if="m.content || m.configError || m.noResult" class="message__bubble bubble--ai">
                  <template v-if="m.configError">
                    <div class="cfg-tip">
                      <div class="cfg-text">{{ m.content }}</div>
                      <div class="gap-actions">
                        <el-button type="primary" size="small" @click="goToConfig">⚙️ 前往系统配置</el-button>
                      </div>
                    </div>
                  </template>
                  <template v-else-if="m.content">
                    <div v-if="m.answerStatus" class="evidence-status" role="status">
                      <el-tag v-if="m.answerStatus === 'answered'" type="success">已通过证据核验</el-tag>
                      <el-tag v-else-if="m.answerStatus === 'partial'" type="warning">部分有依据 · 尚有缺口</el-tag>
                      <el-tag v-else-if="m.answerStatus === 'insufficient'" type="warning">证据不足</el-tag>
                      <el-tag v-else-if="m.answerStatus === 'clarification'" type="info">需要补充信息</el-tag>
                      <el-tag v-if="m.quality?.dws === 'hit'" type="info">已补查钉钉知识</el-tag>
                    </div>
                    <el-alert v-for="warning in m.quality?.warnings || []" :key="warning"
                      :title="warning" type="warning" :closable="false" show-icon class="evidence-warning" />
                    <div
                      class="ans-text md-body"
                      v-html="renderMd(m.content, m.citations)"
                    ></div>
                    <span class="msg-actions ans-acts">
                      <el-tooltip content="复制答案" placement="top">
                        <el-icon class="msg-act-icon" @click="copyText(m.content)"><CopyDocument /></el-icon>
                      </el-tooltip>
                    </span>
                    <div v-if="m.citations && m.citations.length" class="refs">
                      <div class="refs-title">
                        引用来源（{{ m.citations.length }}）
                        <span v-if="m.citations.length > MAX_REFS" class="refs-toggle" @click="toggleRefs(i)">
                          {{ expandedRefs.has(i) ? '收起' : `展开全部 ${m.citations.length} 条` }}
                        </span>
                      </div>
                      <div
                        v-for="(c, ci) in (expandedRefs.has(i) ? m.citations : m.citations.slice(0, MAX_REFS))"
                        :key="ci" class="ref"
                      >
                        <span class="cite">[{{ c.citation_id || ci + 1 }}]</span>
                        <a v-if="citationUrl(c)" class="ref-title ref-link" :href="citationUrl(c)" :title="c.document_title" target="_blank" rel="noopener">{{ c.document_title || '未知文档' }}</a>
                        <span v-else class="ref-title" :title="c.document_title">{{ c.document_title || '未知文档' }}</span>
                        <el-popover v-if="c.quote || c.text" trigger="click" :width="420" placement="top">
                          <template #reference><el-button link type="primary" size="small">查看依据</el-button></template>
                          <div class="evidence-excerpt">{{ c.quote || c.text }}</div>
                          <small v-if="c.partial">此处为原文片段，请结合源文档核对适用范围。</small>
                        </el-popover>
                        <span v-if="c.page_number" class="ref-page">第 {{ c.page_number }} 页</span>
                        <span class="doc-tag">{{ c.source === 'dws' ? '钉钉' : '知识库' }}</span>
                        <el-tooltip content="对这条知识纠错" placement="top">
                          <span class="ref-correct" @click="feedback('correct', m, c)">👎 纠错</span>
                        </el-tooltip>
                      </div>
                    </div>
                    <div class="feedbackbar">
                      <span class="fb-label">有帮助吗？</span>
                      <el-button size="small" :type="m.feedback === 'helpful' ? 'success' : ''"
                                 :disabled="!!m.feedback" @click="feedback('helpful', m)">👍 有帮助</el-button>
                      <el-button size="small" :type="m.feedback === 'correct' ? 'danger' : ''"
                                 :disabled="!!m.feedback" @click="feedback('correct', m)">👎 纠错</el-button>
                      <el-button size="small" :type="m.feedback === 'notfound' ? 'warning' : ''"
                                 :disabled="!!m.feedback" @click="feedback('notfound', m)">❓ 没找到想要的</el-button>
                    </div>
                    <!-- 下一步问题建议 -->
                    <div v-if="m.followUps && m.followUps.length" class="followups">
                      <div class="followups-label">你可能还想问：</div>
                      <button
                        v-for="(f, fi) in m.followUps"
                        :key="fi"
                        type="button"
                        class="followup-chip"
                        @click="askSugg(f)"
                      >{{ f }}</button>
                    </div>
                  </template>
                </div>
                <div class="message__time">
                  {{ m.meta ? m.meta + ' · ' : '' }}{{ m.time }}<template v-if="m.usage && m.usage.total_tokens > 0"> · ↑{{ fmtTok(m.usage.input_tokens) }} ↓{{ fmtTok(m.usage.output_tokens) }} tokens</template>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 建议问题胶囊 -->
      <div v-if="!hasAsked" class="suggestion-chips">
        <button
          v-for="s in suggestions"
          :key="s"
          type="button"
          class="suggestion-chip"
          @click="askSugg(s)"
        >{{ s }}</button>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        <div class="input-tools">
          <el-select
            :model-value="selectedModel"
            size="small"
            style="width: 210px"
            @update:model-value="pickModel"
          >
            <el-option
              v-for="m in modelOptions"
              :key="`${m.profile_id}-${m.model}`"
              :label="m.profile_name ? `${m.model}（${m.profile_name}）` : m.model"
              :value="m.model"
            >
              <span>{{ m.model }}</span>
              <span v-if="m.is_default" style="float: right; color: #409eff; font-size: 12px">默认</span>
            </el-option>
          </el-select>
          <div class="tgl" :class="{ on: deepThink }" @click="deepThink = !deepThink">
            <el-icon><MagicStick /></el-icon> 深度思考
          </div>
          <el-popover
            v-model:visible="dsPopoverVisible"
            trigger="click"
            placement="top-start"
            :width="280"
            :show-arrow="false"
            popper-class="kb-ds-popover"
            @show="kbSearch = true"
          >
            <template #reference>
              <div class="tgl" :class="{ on: kbSearch }">
                <el-icon><Search /></el-icon> 知识库检索
                <span v-if="kbSearch" class="ds-badge">{{ selectedDatasetIds.length }}/{{ datasets.length }}</span>
              </div>
            </template>
            <div class="ds-pop">
              <div class="ds-pop-bar">
                <span>选择数据集</span>
                <el-button link size="small" @click="closeKbSearch">关闭检索</el-button>
              </div>
              <el-divider style="margin: 6px 0" />
              <el-checkbox
                :model-value="isAllSelected"
                :indeterminate="isIndeterminate"
                @change="toggleAllDatasets"
              >全选</el-checkbox>
              <el-checkbox-group v-model="selectedDatasetIds" class="ds-pop-list">
                <el-checkbox v-for="d in datasets" :key="d.id" :label="d.id">{{ d.name }}</el-checkbox>
              </el-checkbox-group>
            </div>
          </el-popover>
        </div>
        <div class="input-row">
          <textarea
            v-model="query"
            class="input-field"
            rows="1"
            placeholder="输入你的问题…"
            @keydown="handleKeydown"
          />
          <button
            type="button"
            class="send-btn"
            :class="{ active: !!query.trim() && !loading, stopping: loading }"
            :disabled="!loading && !query.trim()"
            :title="loading ? '停止回答' : '发送'"
            @click="handleSendClick"
          >
            <span v-if="loading" class="stop-square"></span>
            <el-icon v-else><ArrowUp /></el-icon>
          </button>
        </div>
      </div>
    </div>

    <!-- 纠错反馈弹窗 -->
    <el-dialog v-model="corrVisible" title="知识纠错反馈" width="520px" append-to-body>
      <el-form label-width="92px">
        <el-form-item label="相关问题">
          <div class="corr-question">{{ corrTarget.question || '-' }}</div>
        </el-form-item>
        <el-form-item label="知识标题">
          <el-input v-model="corrForm.knowledge_title" placeholder="出错的知识/文档标题" />
        </el-form-item>
        <el-form-item v-if="corrForm.knowledge_url" label="知识链接">
          <el-link type="primary" :href="corrForm.knowledge_url" target="_blank" :underline="false" style="max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            {{ corrForm.knowledge_url }}
          </el-link>
        </el-form-item>
        <el-form-item label="错误类型">
          <el-select v-model="corrForm.error_type" style="width: 100%">
            <el-option v-for="t in QA_ERROR_TYPES" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="纠错说明">
          <el-input v-model="corrForm.content" type="textarea" :rows="4"
                    placeholder="请描述具体错误内容，便于知识 Owner 修正" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="corrVisible = false">取消</el-button>
        <el-button type="primary" :loading="corrSubmitting" @click="submitCorrection">提交纠错</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* ===== 设计令牌（仅问答页作用域，不改全局主题） ===== */
.chat-page {
  --brand: #6157FF;
  --brand-ink: #FFFFFF;
  --bg: #F8FAFC;
  --surface: #FFFFFF;
  --surface-2: #F1F5F9;
  --ink: #0F172A;
  --ink-2: #64748B;
  --ink-3: #94A3B8;
  --line: #E2E8F0;
  --success: #10B981;
  --radius-md: 0.75rem;
  --radius-lg: 1rem;
  --shadow-1: 0 1px 2px rgba(15,23,42,.05), 0 1px 1px rgba(15,23,42,.03);
  --shadow-2: 0 8px 24px -8px rgba(15,23,42,.18);

  min-height: 100%;
  height: 100%;
  display: flex;
  flex-direction: row;
  gap: 12px;
  background: var(--bg);
  padding: 12px;
  box-sizing: border-box;
}

/* ===== 会话历史侧边栏 ===== */
.history-panel {
  flex: 0 0 240px;
  width: 240px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-1);
  padding: 12px;
  box-sizing: border-box;
  overflow: hidden;
}
.new-chat-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 9px 0;
  border: none;
  border-radius: var(--radius-md);
  background: var(--brand);
  color: var(--brand-ink);
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity .15s;
}
.new-chat-btn:hover { opacity: .9; }
.history-title {
  font-size: 12px;
  color: var(--ink-3);
  padding: 12px 4px 6px;
  letter-spacing: .5px;
}
.history-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.history-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: 13px;
  color: var(--ink-2);
  transition: background .15s;
}
.history-item:hover { background: var(--surface-2); }
.history-item.active { background: color-mix(in srgb, var(--brand) 10%, transparent); color: var(--brand); font-weight: 600; }
.history-name {
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-ops {
  flex: 0 0 auto;
  display: none;
  align-items: center;
  gap: 6px;
}
.history-item:hover .history-ops { display: flex; }
.op-icon { font-size: 13px; color: var(--ink-3); cursor: pointer; }
.op-icon:hover { color: var(--brand); }
.op-icon.op-del:hover { color: #ef4444; }

/* 会话运行状态指示：转圈 = 进行中；绿点 = 有新完成的回答 */
.run-spinner {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
  border: 2px solid #6157ff;
  border-top-color: transparent;
  border-radius: 50%;
  animation: run-spin 0.8s linear infinite;
}
@keyframes run-spin {
  to { transform: rotate(360deg); }
}
.run-done-dot {
  width: 8px;
  height: 8px;
  flex-shrink: 0;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.15);
}
.run-choice-dot {
  width: 9px;
  height: 9px;
  flex-shrink: 0;
  border-radius: 50%;
  background: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.18);
}
.history-empty { font-size: 12.5px; color: var(--ink-3); text-align: center; padding: 20px 0; }

.chat-card {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-2);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ===== 头部助手身份卡 ===== */
.chat-header {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--line);
}
.assistant-identity { display: flex; align-items: center; gap: 12px; }
.assistant-avatar {
  width: 42px; height: 42px; border-radius: 50%;
  display: grid; place-items: center;
  background: linear-gradient(135deg, var(--brand) 0%, color-mix(in srgb, var(--brand) 70%, #fff) 100%);
  color: var(--brand-ink);
  font-size: 20px;
  border: 2px solid var(--surface);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--brand) 20%, transparent);
}
.assistant-meta { display: flex; flex-direction: column; gap: 2px; }
.assistant-name { font-weight: 600; font-size: 15px; color: var(--ink); }
.assistant-status { font-size: 12.5px; color: var(--ink-2); display: flex; align-items: center; gap: 6px; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--success); }
.status-dot.busy { background: #F59E0B; animation: pulse 1.2s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .35; } }
.header-actions { display: flex; gap: 8px; }
.icon-btn {
  width: 36px; height: 36px; border-radius: var(--radius-md);
  border: 1px solid transparent; background: transparent; color: var(--ink-2);
  display: grid; place-items: center; cursor: pointer; font-size: 17px;
  transition: background .2s, color .2s;
}
.icon-btn:hover { background: var(--surface-2); color: var(--ink); }

/* ===== 滚动 / 欢迎区 ===== */
.chat-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
}
.chat-area { margin-top: 0; }
.welcome {
  margin: auto;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; padding: 40px 20px; gap: 8px; animation: fadeIn .4s ease;
}
.welcome-title { font-size: 20px; font-weight: 600; color: var(--ink); margin: 0; white-space: pre-line; line-height: 1.6; }
.welcome-subtitle { font-size: 14px; color: var(--ink-2); max-width: 380px; margin: 0; }
.warn-tip { margin: 12px auto 0; max-width: 560px; padding: 8px 12px; background: #fff7e6; border: 1px solid #ffd591; color: #ad6800; border-radius: 10px; font-size: 12.5px; line-height: 1.7; }

/* ===== 消息列表 ===== */
.chat-area { display: flex; flex-direction: column; gap: 18px; }
.message { display: flex; gap: 10px; max-width: 92%; animation: fadeIn .3s ease; }
.message--user { align-self: flex-end; flex-direction: row-reverse; }
.message--assistant { align-self: flex-start; }
.message__avatar {
  width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0;
  display: grid; place-items: center; margin-top: 2px; font-size: 15px;
}
.avatar--ai {
  background: linear-gradient(135deg, var(--brand) 0%, color-mix(in srgb, var(--brand) 70%, #fff) 100%);
  color: var(--brand-ink);
}
.avatar--user { background: var(--surface-2); color: var(--ink-2); }
.message__col { min-width: 0; display: flex; flex-direction: column; }
.message--user .message__col { align-items: flex-end; }

.message__bubble {
  padding: 11px 15px; border-radius: var(--radius-md);
  font-size: 13.5px; line-height: 1.8; word-break: break-word;
  box-shadow: var(--shadow-1);
}
.bubble--user {
  /* 蓝色底色只包裹问题文字（.bubble-text），不覆盖下方操作区 */
  background: none;
  padding: 0;
  box-shadow: none;
  color: var(--ink);
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.bubble--user .bubble-text {
  display: inline-block;
  background: var(--surface-2);
  padding: 11px 15px;
  border-radius: var(--radius-md);
  border-bottom-right-radius: 4px;
  box-shadow: var(--shadow-1);
  word-break: break-word;
}

/* 问题消息操作行（复制 / 编辑 / 时间）：悬停整行显示，离开隐藏 */
.msg-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 6px;
  opacity: 0;
  transition: opacity .2s;
}
.message--user:hover .msg-meta { opacity: 1; }
.msg-meta .msg-actions { opacity: 1; margin: 0; }
.msg-time { font-size: 11px; color: var(--ink-3); }
.bubble--ai {
  background: color-mix(in srgb, var(--brand) 6%, #fff);
  border: 1px solid color-mix(in srgb, var(--brand) 10%, transparent);
  border-bottom-left-radius: 4px;
  color: var(--ink);
  min-width: 200px;
}
.message__time { font-size: 11px; color: var(--ink-3); margin-top: 4px; padding: 0 4px; }

/* 复制 / 编辑操作（hover 显示，文字下方） */
.msg-actions { display: flex; gap: 10px; width: fit-content; margin-top: 6px; opacity: 0; transition: opacity .2s; }
.message__bubble:hover .msg-actions { opacity: 1; }
.msg-act-icon { cursor: pointer; font-size: 14px; color: var(--ink-3); }
.msg-act-icon:hover { color: var(--brand); }
.ans-acts { justify-content: flex-end; margin-left: auto; }
.bubble-text { white-space: pre-wrap; }

/* typing 圆点 */
.typing-bubble {
  padding: 15px 18px; border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--brand) 6%, #fff);
  border: 1px solid color-mix(in srgb, var(--brand) 10%, transparent);
  display: inline-flex; align-items: center; gap: 5px; width: fit-content;
}
.typing-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--brand); opacity: .5; animation: bounce 1.4s infinite ease-in-out both; }
.typing-dot:nth-child(1) { animation-delay: -.32s; }
.typing-dot:nth-child(2) { animation-delay: -.16s; }
@keyframes bounce { 0%,80%,100% { transform: translateY(0); opacity: .4; } 40% { transform: translateY(-5px); opacity: 1; } }

/* 检索过程条：运行中（紫底实时状态）与完成后（灰底可展开）共用 */
.step-spinner {
  flex: 0 0 auto;
  width: 13px; height: 13px;
  border: 2px solid color-mix(in srgb, var(--brand) 25%, transparent);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: step-spin .7s linear infinite;
}
.step-spinner--mini { width: 10px; height: 10px; border-width: 1.5px; display: inline-block; }
.step-spinner--right { margin-left: auto; }
@keyframes step-spin { to { transform: rotate(360deg); } }

.steps-bar {
  margin-bottom: 8px;
  border-radius: var(--radius-md);
  border: 1px solid var(--line);
  background: var(--bg-gray, #f8f9fc);
  overflow: hidden;
}
/* 运行中：紫色高亮的实时状态条（点击同样可展开全部步骤） */
.steps-bar--live {
  background: color-mix(in srgb, var(--brand) 6%, #fff);
  border-color: color-mix(in srgb, var(--brand) 18%, transparent);
}
.steps-bar__header {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 14px; cursor: pointer;
  font-size: 12.5px; color: var(--ink-2);
  min-height: 34px;
  transition: background .15s;
}
.steps-bar__header:hover { background: color-mix(in srgb, var(--brand) 6%, transparent); }
.steps-bar__label { font-weight: 500; }
.step-live-title { font-weight: 600; color: var(--brand); flex: 0 0 auto; }
.step-live-detail { color: var(--ink-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.steps-expand-hint { margin-left: auto; flex: 0 0 auto; font-size: 11.5px; color: var(--brand); opacity: .8; }
.steps-bar__body { padding: 4px 14px 8px; border-top: 1px dashed var(--line); }

/* 步骤条目（展开态） */
.step-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-2); padding: 2px 0; }
.step-item.done { color: var(--success); }
.step-item .step-dot { width: 16px; text-align: center; font-weight: bold; display: inline-flex; justify-content: center; }
.step-item .step-title { font-weight: 500; }
.step-item .step-detail { color: var(--ink-3); }

/* 限时探索确认卡片 */
.choice-card {
  margin-bottom: 8px;
  padding: 12px 14px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--brand) 5%, #fff);
  border: 1px solid color-mix(in srgb, var(--brand) 22%, transparent);
}
.choice-q { font-size: 13px; color: var(--ink); line-height: 1.7; margin-bottom: 10px; }
.choice-opts { display: flex; gap: 8px; flex-wrap: wrap; }
.choice-btn {
  border: 1px solid color-mix(in srgb, var(--brand) 35%, #fff);
  background: var(--surface);
  color: var(--brand);
  border-radius: 999px;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
  transition: all .15s ease;
}
.choice-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--brand) 10%, #fff);
  transform: translateY(-1px);
}
.choice-btn--primary {
  background: var(--brand);
  color: var(--brand-ink);
  border-color: var(--brand);
}
.choice-btn--primary:hover:not(:disabled) {
  background: color-mix(in srgb, var(--brand) 86%, #000);
}
.choice-btn:disabled { cursor: not-allowed; opacity: .55; }

/* 引用来源 */
.refs { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--line); font-size: 12px; color: var(--ink-2); }
.refs-title { font-weight: 600; margin-bottom: 6px; color: var(--ink); }
.refs-toggle { margin-left: 8px; color: var(--brand); cursor: pointer; font-size: 12px; font-weight: 400; }
.ref { display: flex; align-items: center; gap: 6px; padding: 3px 0; }
.ref > :not(.ref-title) { flex-shrink: 0; }
.cite { display: inline-block; background: color-mix(in srgb, var(--brand) 12%, #fff); color: var(--brand); border-radius: 4px; padding: 0 5px; font-size: 11px; }
.ref-title { flex: 1; color: var(--ink); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ref-page { flex-shrink: 0; color: var(--ink-3); font-size: 11px; }
.doc-tag { display: inline-block; background: color-mix(in srgb, var(--brand) 10%, #fff); color: var(--brand); border-radius: 4px; padding: 0 6px; font-size: 11px; line-height: 18px; }
.gap-actions { margin-top: 12px; display: flex; gap: 8px; }
.cfg-tip { background: #fff7e6; border: 1px solid #ffd591; border-radius: 10px; padding: 12px 14px; }
.cfg-text { color: #ad6800; white-space: pre-line; line-height: 1.8; }
.feedbackbar { display: flex; gap: 8px; margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--line); align-items: center; flex-wrap: wrap; }
.corr-question { font-size: 13.5px; color: #374151; line-height: 1.6; background: #F9FAFB; border-radius: 6px; padding: 8px 10px; max-height: 80px; overflow-y: auto; }
.ref-link { text-decoration: none; }
.ref-link:hover { color: var(--brand); text-decoration: underline; }
.ref-correct { margin-left: auto; font-size: 11.5px; color: #9CA3AF; cursor: pointer; flex-shrink: 0; }
.ref-correct:hover { color: #DC2626; }
.fb-label { font-size: 12px; color: var(--ink-3); }

/* ===== 建议问题胶囊 ===== */
.suggestion-chips {
  flex: 0 0 auto;
  display: flex; gap: 10px; overflow-x: auto;
  padding: 4px 20px 12px;
  scrollbar-width: none;
}
.suggestion-chips::-webkit-scrollbar { display: none; }
.suggestion-chip {
  flex: 0 0 auto; padding: 8px 15px; border-radius: 999px;
  border: 1px solid var(--line); background: var(--surface); color: var(--ink-2);
  font-size: 13px; cursor: pointer; white-space: nowrap;
  transition: transform .2s, border-color .2s, color .2s, box-shadow .2s;
}
.suggestion-chip:hover { transform: translateY(-2px); border-color: var(--brand); color: var(--brand); box-shadow: var(--shadow-1); }

/* ===== 答案内追问建议 ===== */
.followups { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
.followups-label { font-size: 12.5px; color: var(--ink-2); }
.followup-chip {
  border: 1px solid var(--line); background: #f7f6ff; color: var(--brand);
  border-radius: 14px; padding: 5px 13px; font-size: 12.5px; cursor: pointer;
  transition: all .15s ease; text-align: left;
}
.followup-chip:hover { border-color: var(--brand); background: #efedff; transform: translateX(2px); }

/* ===== 输入区 ===== */
.input-area {
  flex: 0 0 auto;
  margin: 0 16px 16px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface);
  padding: 8px 10px;
  transition: box-shadow .2s, border-color .2s;
}
.input-area:focus-within { border-color: var(--brand); box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand) 18%, transparent); }
.input-tools { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 2px 4px 6px; }
.input-row { display: flex; align-items: flex-end; gap: 10px; }
.input-field {
  flex: 1 1 auto; min-width: 0; border: 0; outline: 0; resize: none;
  background: transparent; color: var(--ink); font-family: inherit;
  font-size: 15px; line-height: 1.6; padding: 8px 4px; max-height: 140px; min-height: 26px;
}
.input-field::placeholder { color: var(--ink-3); }
.send-btn {
  width: 40px; height: 40px; border-radius: 50%; border: 0; flex-shrink: 0;
  background: var(--surface-2); color: var(--ink-3);
  display: grid; place-items: center; cursor: pointer; font-size: 18px;
  transition: background .2s, color .2s, transform .2s;
}
.send-btn.active { background: var(--brand); color: var(--brand-ink); }
.send-btn.active:hover { background: color-mix(in srgb, var(--brand) 86%, #000); transform: scale(1.05); }
.send-btn:disabled { cursor: not-allowed; opacity: .7; }
/* 运行中：发送按钮变为停止按钮（深色底 + 白色方块） */
.send-btn.stopping { background: var(--ink); color: #fff; opacity: 1; cursor: pointer; }
.send-btn.stopping:hover { background: #000; transform: scale(1.05); }
.stop-square { width: 13px; height: 13px; border-radius: 3px; background: currentColor; display: block; }

.tgl { display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--ink-2); border: 1px solid var(--line); border-radius: 8px; padding: 4px 10px; cursor: pointer; user-select: none; background: var(--surface); }
.tgl.on { color: var(--brand); border-color: color-mix(in srgb, var(--brand) 35%, #fff); background: color-mix(in srgb, var(--brand) 8%, #fff); }
.ds-badge { font-size: 11px; color: var(--brand); margin-left: 2px; }

.ds-pop { font-size: 13px; }
.ds-pop-bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 2px; }
.ds-pop-list { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.ds-pop-list .el-checkbox { margin-right: 0; }

@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

/* ===== Element Plus 主色统一为品牌紫（限本页） ===== */
.input-tools :deep(.el-select .el-input.is-focus .el-input__wrapper),
.input-tools :deep(.el-select .el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px var(--brand) inset; }
/* 复选框：完全遵循 Element Plus 原生样式，仅通过主题变量 --el-color-primary 控制主色，
   不覆盖 background/border/::after 等内部结构，避免破坏 hover/focus/过渡/indeterminate 横线等原生交互。
   注意：.ds-pop 在 el-popover teleport 后脱离组件，--brand 未定义，故不在此设变量，
   由全局 .kb-ds-popover 统一设置 Element Plus 主题变量 */
.input-tools { --el-color-primary: var(--brand); }
.bubble--ai :deep(.el-button--primary),
.cfg-tip :deep(.el-button--primary) { background: var(--brand); border-color: var(--brand); }
.bubble--ai :deep(.el-button--primary:hover),
.cfg-tip :deep(.el-button--primary:hover) { background: color-mix(in srgb, var(--brand) 86%, #000); border-color: color-mix(in srgb, var(--brand) 86%, #000); }

/* Markdown 渲染样式 */
.md-body { font-size: 14px; line-height: 1.7; word-break: break-word; }
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) { margin: 0.6em 0 0.3em; font-weight: 600; line-height: 1.4; }
.md-body :deep(h1) { font-size: 1.3em; }
.md-body :deep(h2) { font-size: 1.15em; }
.md-body :deep(h3) { font-size: 1.05em; }
.md-body :deep(h4) { font-size: 1em; }
.md-body :deep(p) { margin: 0.4em 0; }
.md-body :deep(ul),
.md-body :deep(ol) { margin: 0.3em 0; padding-left: 1.4em; }
.md-body :deep(li) { margin: 0.15em 0; }
.md-body :deep(strong) { font-weight: 600; }
.md-body :deep(em) { font-style: italic; }
.md-body :deep(code) { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.88em; background: rgba(0,0,0,0.06); padding: 0.1em 0.35em; border-radius: 3px; }
.md-body :deep(pre) { background: rgba(0,0,0,0.06); padding: 0.6em 0.8em; border-radius: 6px; overflow-x: auto; margin: 0.5em 0; }
.md-body :deep(pre code) { background: none; padding: 0; }
.md-body :deep(blockquote) { border-left: 3px solid var(--brand, #6157FF); margin: 0.5em 0; padding: 0.2em 0.8em; color: #666; }
.md-body :deep(hr) { border: none; border-top: 1px solid #e0e0e0; margin: 0.6em 0; }
.md-body :deep(table) { border-collapse: collapse; width: 100%; margin: 0.5em 0; font-size: 0.92em; }
.md-body :deep(th),
.md-body :deep(td) { border: 1px solid #ddd; padding: 0.3em 0.6em; text-align: left; }
.md-body :deep(th) { background: rgba(97,87,255,0.08); font-weight: 600; }
.md-body :deep(a) { color: var(--brand, #6157FF); text-decoration: underline; }
/* 图片/视频渲染 */
.md-body :deep(img) { max-width: 100%; border-radius: 8px; margin: 0.4em 0; }
.md-body :deep(video) { max-width: 100%; border-radius: 8px; margin: 0.4em 0; }
.md-body :deep(iframe) { width: 100%; min-height: 200px; border: none; border-radius: 8px; margin: 0.4em 0; }
.evidence-status { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.evidence-warning { margin-bottom: 8px; }
.evidence-excerpt { white-space: pre-wrap; max-height: 300px; overflow: auto; line-height: 1.7; overflow-wrap: anywhere; }
</style>

<!-- el-popover teleport 到 body，脱离组件 scoped 作用域；
     仅设置 Element Plus 主题变量，让复选框原生样式（对勾/横线/hover/focus/过渡）完整生效 -->
<style>
.kb-ds-popover {
  --el-color-primary: #6157ff;
  --el-color-primary-light-3: #8a83ff;
  --el-color-primary-light-5: #b3aeff;
  --el-color-primary-light-7: #dcd9ff;
  --el-color-primary-light-8: #eae8ff;
  --el-color-primary-light-9: #f4f3ff;
  --el-color-primary-dark-2: #4e46cc;
  --el-checkbox-checked-bg-color: var(--el-color-primary);
  --el-checkbox-checked-input-border-color: var(--el-color-primary);
  --el-checkbox-input-border-color-hover: var(--el-color-primary);
}
</style>
