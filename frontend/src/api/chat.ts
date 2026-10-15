// 聊天模式 API 封装：POST /api/v1/chat（同步）+ POST /api/v1/chat/stream（SSE 流式）
import { http, getToken, setToken } from './client'
import type { ChatRequest, ChatResponse, StreamEvent } from './types'

async function* readSSE(resp: Response): AsyncGenerator<StreamEvent> {
  if (!resp.ok || !resp.body) {
    throw new Error(`聊天流式请求失败 (${resp.status})`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE 帧：data: <json>\n\n（服务端逐行推送）
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const line = frame.trim()
      if (!line.startsWith('data: ')) continue
      try {
        yield JSON.parse(line.slice(6)) as StreamEvent
      } catch {
        /* 忽略无法解析的帧 */
      }
    }
  }
}

export const chatApi = {
  send(req: ChatRequest): Promise<ChatResponse> {
    return http.post<ChatResponse>('/api/v1/chat', req)
  },

  /** SSE 流式：逐步 yield 事件（status 进度 → delta 文本 → done 完成） */
  async *stream(req: ChatRequest): AsyncGenerator<StreamEvent> {
    let resp: Response
    try {
      // 必须带 Bearer token（后端 chat/stream 需登录鉴权）
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      const token = getToken()
      if (token) headers.Authorization = `Bearer ${token}`
      resp = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers,
        body: JSON.stringify(req),
      })
      // SSE 走原生 fetch（非 http 封装）：401 需与 http 封装一致处理——
      // token 失效/过期 → 清理会话并跳登录页，避免卡在"流式请求失败(401)"
      if (resp.status === 401) {
        setToken(null)
        if (!window.location.pathname.startsWith('/login')) {
          window.location.href = '/login'
        }
        throw new Error('登录已过期，请重新登录')
      }
    } catch (e) {
      if (e instanceof Error && e.message === '登录已过期，请重新登录') throw e
      throw new Error('无法连接后端服务，请确认 FastAPI 已启动（见 docs/RUN_GUIDE.md）')
    }
    for await (const ev of readSSE(resp)) {
      yield ev
    }
  },
}
