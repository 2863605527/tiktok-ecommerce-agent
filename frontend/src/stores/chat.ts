// 聊天模式 store：多会话历史（按用户隔离 localStorage）+ SSE 流式发送
import { defineStore } from 'pinia'
import { ref, nextTick } from 'vue'
import { chatApi } from '@/api/chat'
import { useAuthStore } from '@/stores/auth'
import type { ChatData, ChatMessage } from '@/api/types'

let seq = 0
const LS_PREFIX = 'tk-agent:chat:conversations:'

function lsKey(): string {
  // 按用户名隔离：每个登录用户只有自己的会话历史
  const auth = useAuthStore()
  return LS_PREFIX + (auth.user?.username ?? 'guest')
}

export interface Conversation {
  id: string
  title: string
  createdAt: number
  messages: ChatMessage[]
}

function newId(): string {
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(lsKey())
    if (!raw) return []
    const list = JSON.parse(raw) as Conversation[]
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

function persist(list: Conversation[]) {
  try {
    localStorage.setItem(lsKey(), JSON.stringify(list))
  } catch {
    /* 存储不可用则忽略（会话级） */
  }
}

const welcome: ChatMessage = {
  id: -1,
  role: 'assistant',
  content:
    '你好，我是 TikTok 电商选品助手（日本站主推）\n' +
    '我可以帮你：\n' +
    '· 分析商品能不能卖（真实竞品 + 评论 RAG 分析 + 找家纺货源 + 日文上架素材）\n' +
    '· 找国内货源（找家纺网，一件代发）\n' +
    '· 生成日文上架素材（标题 / 关键词 / 描述 / 规格翻译）\n\n' +
    '直接说需求就行，比如：帮我分析 ボックスシーツ 冬用 能不能卖。\n' +
    '（我只聊商品/电商话题，其他内容不在我的回答范围内）',
}

export const useChatStore = defineStore('chat', () => {
  // 不立即加载：init() 时按当前登录用户加载（新用户 → 干净历史）
  const conversations = ref<Conversation[]>([])
  const activeId = ref<string | null>(null)
  const sending = ref(false)
  const region = ref('JP')
  const language = ref('ja')
  const category = ref('bedding')

  const active = (): Conversation | null =>
    conversations.value.find((c) => c.id === activeId.value) ?? null

  // 当前会话消息（与 conversation.messages 同一引用，切换会话即替换）
  const messages = ref<ChatMessage[]>([])

  function _useConversation(conv: Conversation) {
    activeId.value = conv.id
    messages.value = conv.messages
  }

  function newConversation() {
    const conv: Conversation = {
      id: newId(),
      title: '新对话',
      createdAt: Date.now(),
      messages: [{ ...welcome, id: ++seq }],
    }
    conversations.value.unshift(conv)
    _useConversation(conv)
    persist(conversations.value)
  }

  function selectConversation(id: string) {
    const conv = conversations.value.find((c) => c.id === id)
    if (!conv) return
    _useConversation(conv)
    scrollToBottomDelayed()
  }

  function removeConversation(id: string) {
    const idx = conversations.value.findIndex((c) => c.id === id)
    if (idx === -1) return
    conversations.value.splice(idx, 1)
    persist(conversations.value)
    if (activeId.value === id) {
      if (conversations.value.length) {
        _useConversation(conversations.value[0])
      } else {
        activeId.value = null
        messages.value = []
      }
    }
  }

  /** 重命名会话（双击标题触发） */
  function renameConversation(id: string, title: string) {
    const conv = conversations.value.find((c) => c.id === id)
    const t = title.trim()
    if (!conv || !t) return
    conv.title = t.length > 30 ? t.slice(0, 30) + '…' : t
    persist(conversations.value)
  }

  /** 导出当前会话为 Markdown（复盘/交接） */
  function exportMarkdown(id: string): string {
    const conv = conversations.value.find((c) => c.id === id)
    if (!conv) return ''
    const lines: string[] = [
      `# ${conv.title}`,
      '',
      `> 导出时间：${new Date().toLocaleString('zh-CN')} · 会话 ID：${id}`,
      '',
    ]
    for (const m of conv.messages) {
      if (m.role === 'user') {
        lines.push('## 🧑 我', '', m.content, '')
      } else {
        lines.push('## 🤖 AI', '')
        if (m.steps && m.steps.length) {
          lines.push('### 思考过程', '')
          for (const s of m.steps) lines.push(`- ${s.stage}: ${s.text}`)
          lines.push('')
        }
        if (m.content) lines.push(m.content, '')
        const d = m.data
        if (d?.products?.length) {
          lines.push('### 竞品', '')
          for (const p of d.products) {
            lines.push(`- **${p.title}** · ${p.price} ${p.currency ?? ''}${p.url ? ` · ${p.url}` : ''}`)
          }
          lines.push('')
        }
        if (d?.offers?.length) {
          lines.push('### 货源', '')
          for (const o of d.offers) {
            lines.push(`- **${o.title}** · ${o.price} · ${o.supplier_name}${o.url ? ` · ${o.url}` : ''}`)
          }
          lines.push('')
        }
        if (d?.listing) {
          lines.push('### 上架素材', '', `- 标题：${d.listing.title}`, `- 关键词：${(d.listing.keywords || []).join(' / ')}`, '')
        }
      }
    }
    return lines.join('\n')
  }

  /** 下载文本文件（UTF-8 BOM，Windows 记事本可读） */
  function downloadText(text: string, filename: string) {
    const blob = new Blob(['\ufeff' + text], { type: 'text/markdown;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = filename
    a.click()
    URL.revokeObjectURL(a.href)
  }

  function pushMessage(m: Partial<ChatMessage> & { role: 'user' | 'assistant'; content: string }): ChatMessage {
    const msg: ChatMessage = { id: ++seq, ...m }
    messages.value.push(msg)
    // 关键：必须返回 reactive 数组中的「代理对象」而不是原始对象。
    // 直接改原始对象的属性不会触发 Vue 依赖更新（模板读的是代理），
    // 流式逐字/状态行就会全部攒到最后一次渲染——表现为"转圈后一下出来"。
    return messages.value[messages.value.length - 1]
  }

  function _persistActive() {
    const conv = active()
    if (!conv) return
    // 标题取第一条用户消息
    const firstUser = conv.messages.find((m) => m.role === 'user')
    if (firstUser) {
      const t = firstUser.content.replace(/\s+/g, ' ').trim()
      if (t) conv.title = t.length > 18 ? t.slice(0, 18) + '…' : t
    }
    persist(conversations.value)
  }

  async function send(text: string) {
    const content = text.trim()
    if (!content || sending.value) return

    // 没有会话则新建
    if (!active()) newConversation()

    pushMessage({ role: 'user', content })
    const startedAt = Date.now()
    const pending = pushMessage({
      role: 'assistant',
      content: '',
      loading: true,
      thinking: true,
      steps: [],
    })
    sending.value = true

    let replyText = ''
    try {
      for await (const ev of chatApi.stream({
        message: content,
        region: region.value,
        category: category.value,
        language: language.value,
        conversation_id: activeId.value ?? undefined,
      })) {
        if (ev.type === 'status') {
          // 阶段进度 → 思考过程步骤（大模型 agent 式："调用 XX"逐步展示）
          pending.steps = [...(pending.steps ?? []), { stage: ev.stage, text: ev.text }]
          pending.thinking = true
        } else if (ev.type === 'delta') {
          if (pending.steps && pending.steps.length) {
            // 重活分支：阶段小结（"✓ 匹配到N条货源"）并入最后一个思考步骤，
            // 作为该步骤的完成结果，不污染最终正文
            const last = pending.steps[pending.steps.length - 1]
            pending.steps = [
              ...pending.steps.slice(0, -1),
              { ...last, text: last.text + '\n' + ev.text },
            ]
          } else {
            // 快速分支（自我介绍/范围外/缺商品词）：delta 即最终答复，累积后一次性展示
            replyText += ev.text
            pending.content = replyText
          }
        } else if (ev.type === 'done') {
          pending.content = replyText || ev.reply
          pending.intent = ev.intent
          pending.needsProduct = ev.needs_product
          pending.data = ev.data as ChatData | null
          pending.thinking = false
          pending.thinkingSeconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000))
          pending.loading = false
          _persistActive()
        } else if (ev.type === 'error') {
          pending.thinking = false
          pending.loading = false
          pending.content = replyText ? replyText + '\n\n' + ev.text : ev.text
        }
      }
    } catch (e) {
      pending.thinking = false
      pending.loading = false
      pending.content = e instanceof Error ? `出错了：${e.message}` : '出错了，请稍后重试。'
    } finally {
      sending.value = false
      await nextTick()
      scrollToBottom()
    }
  }

  async function scrollToBottom() {
    const el = document.querySelector('[data-chat-scroll]')
    if (el) el.scrollTop = el.scrollHeight
  }

  // 图片/卡片异步渲染后高度会变化，分多次滚动保证落到底部（刷新/切换会话用）
  function scrollToBottomDelayed() {
    scrollToBottom()
    setTimeout(() => scrollToBottom(), 120)
    setTimeout(() => scrollToBottom(), 500)
    setTimeout(() => scrollToBottom(), 1200)
  }

  async function init() {
    // 等待认证就绪：未登录不加载（登录页场景）；登录后加载「该用户」自己的历史
    const auth = useAuthStore()
    if (!auth.initialized) await auth.init()
    if (!auth.user) {
      conversations.value = []
      activeId.value = null
      messages.value = []
      return
    }
    conversations.value = loadConversations()
    if (!conversations.value.length) {
      newConversation()
      return
    }
    _useConversation(conversations.value[0])
  }

  return {
    conversations, activeId, messages, sending, region, language, category,
    newConversation, selectConversation, removeConversation, renameConversation,
    exportMarkdown, downloadText,
    send, scrollToBottom, scrollToBottomDelayed, init,
  }
})
