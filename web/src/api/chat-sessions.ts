import request from './request'

export interface ChatSession {
  id: string
  title: string
  memory: string
  last_query: string
  last_answer: string
  message_count: number
  created_at: string | null
  updated_at: string | null
}

export interface ChatSessionMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: string[]
  meta: string
  detail?: {
    steps?: { title?: string; detail?: string; done?: boolean }[]
    retrieval?: Record<string, unknown>[]
    model?: string
    duration_ms?: number
  } | null
  created_at: string | null
}

export const listChatSessions = () =>
  request.get<unknown, ChatSession[]>('/chat-sessions')

export const createChatSession = (title = '新会话') =>
  request.post<unknown, ChatSession>('/chat-sessions', { title })

export const renameChatSession = (id: string, title: string) =>
  request.put<unknown, ChatSession>(`/chat-sessions/${id}`, { title })

export const deleteChatSession = (id: string) =>
  request.delete<unknown, void>(`/chat-sessions/${id}`)

export const getSessionMessages = (id: string) =>
  request.get<unknown, { session: ChatSession; messages: ChatSessionMessage[] }>(
    `/chat-sessions/${id}/messages`,
  )

export const saveChatTurn = (
  id: string,
  data: {
    question: string
    answer: string
    citations: string[]
    meta: string
    last_query: string
    last_answer: string
    detail?: Record<string, unknown> | null
  },
) => request.post<unknown, { ok: boolean; user_message_id: string; assistant_message_id: string }>(
  `/chat-sessions/${id}/turn`, data)
