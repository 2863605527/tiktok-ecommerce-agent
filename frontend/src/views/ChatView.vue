<script setup lang="ts">
// 电商助手聊天页（KeepAlive name=chat：切走再回来不丢会话/进行中的流）
defineOptions({ name: 'chat' })
import { computed, onActivated, onBeforeUnmount, onMounted, ref, nextTick } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useFavoritesStore } from '@/stores/favorites'
import { useToastStore } from '@/stores/toast'
import StatusBar from '@/components/StatusBar.vue'
import ChatMessage from '@/components/ChatMessage.vue'
import type { ChatMessage as ChatMessageType } from '@/api/types'

const store = useChatStore()
const fav = useFavoritesStore()
const toast = useToastStore()

const input = ref('')
const inputEl = ref<HTMLTextAreaElement | null>(null)
const convSearch = ref('')
const showFav = ref(false)
const renamingId = ref<string | null>(null)
const renameText = ref('')
// 窄屏侧栏折叠（<860px 时抽屉式）
const sidebarCollapsed = ref(false)

const QUICK_PROMPTS = [
  { icon: '🔍', text: '帮我分析 ボックスシーツ 冬用 能不能卖' },
  { icon: '📦', text: '找 牛奶绒床笠 四件套 的货源' },
  { icon: '✍️', text: '生成 法兰绒床笠 的上架素材' },
  { icon: '🎬', text: '生成 牛奶绒床笠 的带货脚本' },
  { icon: '💰', text: '售价3000 成本80 运费50 算下利润' },
  { icon: '🔄', text: '去1688找货源' },
]

const REGIONS = [
  { value: 'JP', label: '日本 JP' },
  { value: 'US', label: '美国 US' },
  { value: 'UK', label: '欧洲 UK' },
  { value: 'SG', label: '新加坡 SG' },
]

const LANGUAGES = [
  { value: 'ja', label: '日本語' },
  { value: 'en', label: 'English' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
  { value: 'de', label: 'Deutsch' },
  { value: 'ko', label: '한국어' },
]

const CATEGORIES = [
  { value: 'bedding', label: '床上用品' },
  { value: 'electronics', label: '电子' },
  { value: 'apparel', label: '服装' },
]

// 会话搜索过滤
const filteredConvs = computed(() => {
  const q = convSearch.value.trim().toLowerCase()
  if (!q) return store.conversations
  return store.conversations.filter((c) =>
    c.title.toLowerCase().includes(q) ||
    c.messages.some((m) => m.content.toLowerCase().includes(q)))
})

/** 发送：单条；输入多行 → 批量选品（每行一个商品，串行逐个分析） */
async function onSend() {
  const text = input.value
  if (!text.trim() || store.sending) return
  input.value = ''
  autoResize()
  // 批量模式：显式换行 = 多个商品名（如"牛奶绒床笠\n法兰绒床笠"）
  const lines = text.split('\n').map((s) => s.trim()).filter((s) => s.length >= 1)
  if (lines.length > 1) {
    toast.info(`批量选品：共 ${lines.length} 个商品，逐个分析中…`)
    for (const line of lines) {
      await store.send(line)
    }
    toast.success(`批量分析完成（${lines.length} 个商品）`)
  } else {
    await store.send(text.trim())
  }
}

/** 失败消息重试：重新发送同一条 */
async function onRetry(m: ChatMessageType) {
  if (store.sending) return
  toast.info('正在重试…')
  await store.send(m.content)
}

function onQuick(p: { icon: string; text: string }) {
  if (store.sending) return
  store.send(p.text)
}

/** 输入框自适应增高 */
function autoResize() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(120, el.scrollHeight) + 'px'
}

/** 导出会话 Markdown */
function exportConv(id: string) {
  const md = store.exportMarkdown(id)
  if (!md) return
  const conv = store.conversations.find((c) => c.id === id)
  const name = (conv?.title || '对话').replace(/[\\/:*?"<>|]/g, '_').slice(0, 40)
  store.downloadText(md, `${name}.md`)
  toast.success('会话已导出（Markdown）')
}

/** 重命名交互 */
function startRename(id: string) {
  const conv = store.conversations.find((c) => c.id === id)
  if (!conv) return
  renamingId.value = id
  renameText.value = conv.title
}
function commitRename(id: string) {
  store.renameConversation(id, renameText.value)
  renamingId.value = null
}

/** 收藏库导出 CSV */
function exportFavCSV() {
  if (!fav.count) return
  const csv = '\ufeff' + fav.exportCSV()
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `选品收藏_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
  toast.success('收藏库已导出（CSV）')
}

/** 清空收藏库（防误触：二次确认） */
function clearFav() {
  if (!fav.count) return
  if (window.confirm(`确定清空 ${fav.count} 条收藏吗？此操作不可恢复。`)) {
    fav.clear()
    toast.info('收藏库已清空')
  }
}

/** 键盘快捷键：Ctrl+Enter 发送、Ctrl+K 聚焦、Ctrl+N 新对话 */
function onKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    inputEl.value?.focus()
  } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
    e.preventDefault()
    store.newConversation()
  }
}

function convTime(ts: number): string {
  const d = new Date(ts)
  const now = new Date()
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

function favKindLabel(kind: string): string {
  return kind === 'product' ? '竞品' : kind === 'offer' ? '货源' : '素材'
}

/** 最近分析过的商品（跨会话提取，点击回填输入框，方便续聊） */
const recentProducts = computed(() => {
  const seen: string[] = []
  for (const c of store.conversations) {
    for (const m of c.messages) {
      if (m.role === 'user' && (m.intent === 'select_product' || (m.data && (m.data.products?.length || m.data.report)))) {
        const t = m.content.split('\n')[0].trim().slice(0, 40)
        if (t && !seen.includes(t)) seen.push(t)
      }
    }
  }
  return seen.slice(0, 5)
})

function useRecent(text: string) {
  input.value = text
  autoResize()
  inputEl.value?.focus()
}

onMounted(async () => {
  await store.init()
  fav.init()
  window.addEventListener('keydown', onKeydown)
  await nextTick()
  store.scrollToBottomDelayed()
})

onActivated(() => {
  store.scrollToBottomDelayed()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="chat-page">
    <!-- 数据源状态 -->
    <StatusBar />

    <div class="chat-layout">
      <!-- 窄屏折叠开关（<860px 显示） -->
      <button class="sidebar-toggle" :title="sidebarCollapsed ? '展开会话栏' : '收起会话栏'"
        @click="sidebarCollapsed = !sidebarCollapsed">
        {{ sidebarCollapsed ? '☰' : '✕' }}
      </button>

      <!-- 左侧：会话历史 + 收藏库（窄屏折叠为抽屉） -->
      <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
        <button class="new-chat" :disabled="store.sending" @click="store.newConversation()">
          ＋ 新对话
          <span class="kbd">Ctrl+N</span>
        </button>

        <!-- 收藏 / 会话 切换 -->
        <div class="side-tabs">
          <button class="side-tab" :class="{ on: !showFav }" @click="showFav = false">
            会话
            <span class="cnt">{{ store.conversations.length }}</span>
          </button>
          <button class="side-tab" :class="{ on: showFav }" @click="showFav = true">
            ★ 收藏
            <span class="cnt" :class="{ hot: fav.count > 0 }">{{ fav.count }}</span>
          </button>
        </div>

        <!-- 收藏库面板 -->
        <template v-if="showFav">
          <div class="fav-actions">
            <button class="mini" :disabled="!fav.count" @click="exportFavCSV">导出 CSV</button>
            <button class="mini danger" :disabled="!fav.count" @click="clearFav">清空</button>
          </div>
          <div class="conv-list">
            <div v-if="!fav.count" class="conv-empty">
              还没有收藏<br>在结果卡片点 ☆ 收藏竞品/货源/素材
            </div>
            <div v-for="f in fav.items" :key="f.id" class="fav-item">
              <div class="fav-kind">{{ favKindLabel(f.kind) }}</div>
              <div class="fav-main">
                <div class="fav-title">{{ f.title }}</div>
                <div class="fav-meta">
                  {{ f.price ? f.price + ' · ' : '' }}{{ f.extra }}
                </div>
                <a v-if="f.url" :href="f.url" target="_blank" rel="noopener" class="fav-link">打开链接 ↗</a>
              </div>
              <button class="conv-del" title="移除收藏" @click="fav.remove(f.id)">×</button>
            </div>
          </div>
        </template>

        <!-- 会话列表面板 -->
        <template v-else>
          <div class="conv-search">
            <input v-model="convSearch" class="search-input" placeholder="搜索会话 / 内容…" />
          </div>
          <div class="conv-list">
            <div v-if="!filteredConvs.length" class="conv-empty">
              {{ convSearch ? '没有匹配的会话' : '暂无历史会话' }}
            </div>
            <div
              v-for="c in filteredConvs"
              :key="c.id"
              class="conv-item"
              :class="{ active: c.id === store.activeId }"
              @click="store.selectConversation(c.id)"
            >
              <template v-if="renamingId === c.id">
                <input
                  v-model="renameText"
                  class="rename-input"
                  autofocus
                  @keydown.enter.stop.prevent="commitRename(c.id)"
                  @keydown.esc.stop="renamingId = null"
                  @blur="commitRename(c.id)"
                  @click.stop
                />
              </template>
              <template v-else>
                <span class="conv-title" :title="c.title" @dblclick.stop="startRename(c.id)">
                  {{ c.title }}
                </span>
                <span class="conv-time">{{ convTime(c.createdAt) }}</span>
                <button class="conv-del" title="导出 Markdown" @click.stop="exportConv(c.id)">⇩</button>
                <button class="conv-del" title="重命名" @click.stop="startRename(c.id)">✎</button>
                <button class="conv-del danger" title="删除会话" @click.stop="store.removeConversation(c.id)">×</button>
              </template>
            </div>
          </div>
        </template>
      </aside>

      <!-- 右侧：对话主体 -->
      <div class="chat-main">
        <!-- 会话设置 -->
        <div class="settings">
          <label>
            <span>市场</span>
            <select v-model="store.region">
              <option v-for="r in REGIONS" :key="r.value" :value="r.value">{{ r.label }}</option>
            </select>
          </label>
          <label>
            <span>品类</span>
            <select v-model="store.category">
              <option v-for="c in CATEGORIES" :key="c.value" :value="c.value">{{ c.label }}</option>
            </select>
          </label>
          <label>
            <span>文案语言</span>
            <select v-model="store.language">
              <option v-for="l in LANGUAGES" :key="l.value" :value="l.value">{{ l.label }}</option>
            </select>
          </label>
          <span class="settings-tip">只聊商品 / 选品 / 货源 / 上架，其他内容不在回答范围</span>
        </div>

        <!-- 快捷指令 -->
        <div class="quick">
          <button v-for="q in QUICK_PROMPTS" :key="q.text" class="quick-chip" :disabled="store.sending"
            @click="onQuick(q)">
            <span class="q-icon">{{ q.icon }}</span>{{ q.text }}
          </button>
        </div>

        <!-- 最近分析的商品（续聊快捷入口） -->
        <div v-if="recentProducts.length" class="recent">
          <span class="recent-label">最近分析</span>
          <button v-for="r in recentProducts" :key="r" class="recent-chip" :disabled="store.sending"
            :title="'点击回填：' + r" @click="useRecent(r)">
            {{ r }}
          </button>
        </div>

        <!-- 消息区 -->
        <div class="messages" data-chat-scroll>
          <div v-if="!store.messages.length" class="empty-tip">
            <div class="empty-emoji">🛏️</div>
            <div class="empty-title">我是你的 TikTok 选品助手（日本站主推）</div>
            <div class="empty-sub">问商品选品 / 找货源 / 生成上架素材，或者从上方快捷指令开始</div>
          </div>
          <ChatMessage v-for="m in store.messages" :key="m.id" :msg="m" @retry="onRetry(m)" />
        </div>

        <!-- 输入区 -->
        <div class="input-bar">
          <textarea
            ref="inputEl"
            v-model="input"
            rows="1"
            placeholder="例：帮我分析 ボックスシーツ 冬用 能不能卖（Enter 发送，Ctrl+Enter 也发送）"
            @keydown.enter.exact.prevent="onSend"
            @input="autoResize"
          />
          <button class="send-btn" :disabled="store.sending || !input.trim()" @click="onSend">
            {{ store.sending ? '处理中…' : '发送' }}
          </button>
        </div>
        <div class="input-hint">
          <span>Enter 发送</span>·<span>Ctrl+K 聚焦输入</span>·<span>Ctrl+N 新对话</span>·<span>双击会话标题可重命名</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 120px);
}

.chat-layout {
  flex: 1;
  display: flex;
  gap: 14px;
  min-height: 0;
  position: relative;
}

/* 窄屏侧栏折叠开关 */
.sidebar-toggle {
  display: none;
  position: absolute;
  left: 0;
  top: 0;
  z-index: 20;
  width: 34px;
  height: 34px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-dim);
  border-radius: var(--radius-sm);
  font-size: 14px;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
}

/* ---- 左侧会话历史 ---- */
.sidebar {
  flex: 0 0 248px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.new-chat {
  background: var(--primary);
  border: none;
  color: #fff;
  border-radius: var(--radius-md);
  padding: 11px 0;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: background var(--dur) var(--ease);
}

.new-chat:hover:not(:disabled) {
  background: var(--primary-hover);
}

.new-chat:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.kbd {
  font-size: 10px;
  font-weight: 500;
  opacity: 0.75;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 4px;
  padding: 0 5px;
}

.side-tabs {
  display: flex;
  gap: 6px;
  flex: 0 0 auto;
}

.side-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid var(--border);
  background: var(--bg);
  border-radius: var(--radius-sm);
  padding: 6px 0;
  font-size: 12px;
  color: var(--text-dim);
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}

.side-tab.on {
  background: var(--primary-bg);
  border-color: var(--primary);
  color: var(--primary);
  font-weight: 600;
}

.cnt {
  background: var(--bg-card);
  border-radius: 999px;
  font-size: 10px;
  padding: 0 7px;
  color: var(--text-dim);
}

.cnt.hot {
  background: var(--warn-bg);
  color: var(--warn);
}

.conv-search {
  flex: 0 0 auto;
}

.search-input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 7px 11px;
  font-size: 12px;
  background: var(--bg);
  color: var(--text);
  outline: none;
  transition: border-color var(--dur);
}

.search-input:focus {
  border-color: var(--primary);
}

.conv-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.conv-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 13px;
  color: var(--text-dim);
  transition: background var(--dur);
}

.conv-item:hover {
  background: var(--bg-card-hover);
}

.conv-item.active {
  background: var(--primary-bg);
  color: var(--primary);
  font-weight: 600;
}

.conv-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-time {
  flex: 0 0 auto;
  font-size: 10px;
  color: var(--text-faint);
}

.conv-del {
  flex: 0 0 auto;
  border: none;
  background: transparent;
  color: var(--text-faint);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 5px;
  border-radius: 6px;
  opacity: 0;
  transition: opacity var(--dur);
}

.conv-item:hover .conv-del {
  opacity: 1;
}

.conv-del:hover {
  color: var(--primary);
  background: var(--primary-bg);
}

.conv-del.danger:hover {
  color: var(--danger);
  background: var(--danger-bg);
}

.rename-input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--primary);
  border-radius: 6px;
  padding: 3px 8px;
  font-size: 12px;
  outline: none;
}

.conv-empty {
  text-align: center;
  color: var(--text-dim);
  font-size: 12px;
  padding: 28px 8px;
  line-height: 1.8;
}

/* 收藏项 */
.fav-actions {
  display: flex;
  gap: 6px;
  flex: 0 0 auto;
}

.fav-actions .mini {
  flex: 1;
  border: 1px solid var(--border);
  background: var(--bg);
  border-radius: var(--radius-sm);
  padding: 6px 0;
  font-size: 12px;
  color: var(--text-dim);
  cursor: pointer;
}

.fav-actions .mini:hover:not(:disabled) {
  color: var(--primary);
  border-color: var(--primary);
}

.fav-actions .mini.danger:hover:not(:disabled) {
  color: var(--danger);
  border-color: var(--danger);
}

.fav-actions .mini:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.fav-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 9px 10px;
  border-radius: var(--radius-sm);
  background: var(--bg);
  margin-bottom: 2px;
}

.fav-kind {
  flex: 0 0 auto;
  font-size: 10px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-bg);
  border-radius: 5px;
  padding: 1px 6px;
  margin-top: 1px;
}

.fav-main {
  flex: 1;
  min-width: 0;
}

.fav-title {
  font-size: 12px;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.fav-meta {
  font-size: 11px;
  color: var(--text-faint);
  margin-top: 2px;
}

.fav-link {
  font-size: 11px;
  color: var(--primary);
}

/* ---- 右侧对话 ---- */
.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.settings {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  box-shadow: var(--shadow-sm);
}

.settings label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-dim);
}

.settings select {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  padding: 5px 10px;
  font-size: 13px;
  outline: none;
  cursor: pointer;
  transition: border-color var(--dur);
}

.settings select:focus {
  border-color: var(--primary);
}

.settings-tip {
  font-size: 11px;
  color: var(--text-faint);
  margin-left: auto;
}

.quick {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.quick-chip {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-dim);
  font-size: 12px;
  padding: 6px 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all var(--dur) var(--ease);
  box-shadow: var(--shadow-sm);
}

.q-icon {
  font-size: 13px;
}

.quick-chip:hover:not(:disabled) {
  color: var(--primary);
  border-color: var(--primary);
  transform: translateY(-1px);
}

.quick-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ---- 最近分析商品（续聊入口） ---- */
.recent {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.recent-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-faint);
  flex: 0 0 auto;
}

.recent-chip {
  border: 1px dashed var(--border);
  background: var(--bg-card);
  color: var(--text-dim);
  border-radius: 999px;
  font-size: 11px;
  padding: 4px 12px;
  cursor: pointer;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: all var(--dur) var(--ease);
}

.recent-chip:hover:not(:disabled) {
  color: var(--primary);
  border-color: var(--primary);
  border-style: solid;
}

.recent-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 4px 4px 12px;
  scroll-behavior: smooth;
}

.empty-tip {
  text-align: center;
  color: var(--text-dim);
  padding: 56px 0;
}

.empty-emoji {
  font-size: 44px;
  margin-bottom: 10px;
}

.empty-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 4px;
}

.empty-sub {
  font-size: 13px;
  color: var(--text-dim);
}

.input-bar {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 12px 14px;
  box-shadow: var(--shadow);
  transition: border-color var(--dur), box-shadow var(--dur);
}

.input-bar:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-bg), var(--shadow);
}

.input-bar textarea {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text);
  font-size: 14px;
  resize: none;
  outline: none;
  line-height: 1.6;
  font-family: inherit;
  max-height: 120px;
}

.send-btn {
  background: var(--primary);
  border: none;
  color: #fff;
  border-radius: var(--radius-md);
  padding: 10px 24px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  flex: 0 0 auto;
  transition: background var(--dur), box-shadow var(--dur);
  box-shadow: 0 1px 2px rgba(46, 92, 255, 0.3);
}

.send-btn:hover:not(:disabled) {
  background: var(--primary-hover);
  box-shadow: 0 4px 12px rgba(46, 92, 255, 0.25);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-hint {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: var(--text-faint);
  padding: 0 6px;
}

@media (max-width: 860px) {
  .sidebar-toggle { display: block; }
  .sidebar {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 15;
    width: 248px;
    transition: transform var(--dur) var(--ease);
  }
  .sidebar.collapsed {
    transform: translateX(-110%);
    box-shadow: none;
  }
  .chat-main { margin-left: 34px; }
}

@media (max-width: 720px) {
  .chat-page { height: calc(100vh - 100px); }
  .sidebar { flex-basis: 190px; }
  .settings-tip { display: none; }
}
</style>
