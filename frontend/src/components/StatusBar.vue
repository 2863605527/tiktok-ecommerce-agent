<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useSelectionStore } from '@/stores/selection'

const store = useSelectionStore()
const router = useRouter()

type Status = 'ok' | 'warn' | 'off'

const sourceMeta: Record<string, { label: string; status: Status }> = {
  sample: { label: '样本(离线)', status: 'warn' },
  socialcrawl: { label: 'SocialCrawl', status: 'ok' },
  tikhub: { label: 'TikHub', status: 'warn' },
  fastmoss: { label: 'FastMoss', status: 'warn' },
  jiafang: { label: '找家纺网', status: 'ok' },
  direct: { label: '直连(RPA)', status: 'warn' },
  milvus: { label: 'Milvus', status: 'ok' },
  ragflow: { label: 'RAGFlow', status: 'warn' },
  memory: { label: '内存库', status: 'warn' },
}

function statusOf(value: string): Status {
  return sourceMeta[value]?.status ?? 'warn'
}

function labelOf(key: string, value: string): string {
  return `${key}: ${sourceMeta[value]?.label ?? value}`
}

const items = computed(() => {
  const c = store.config
  if (!c) return []
  const out = [
    { label: labelOf('商品', c.product_source), status: statusOf(c.product_source) },
    { label: labelOf('货源', c.supplier_source), status: statusOf(c.supplier_source) },
    { label: labelOf('检索', c.rag_backend), status: statusOf(c.rag_backend) },
  ]
  // 商品数据源连接状态（真实展示）
  if (c.product_source === 'socialcrawl') {
    out.push({
      label: c.has_socialcrawl_key ? 'SocialCrawl 已连接' : 'SocialCrawl 未配置 Key',
      status: c.has_socialcrawl_key ? 'ok' : 'warn',
    })
  } else if (c.product_source === 'tikhub') {
    out.push({
      label: c.has_tikhub_key ? 'TikHub 已连接' : 'TikHub 未配置 Key',
      status: c.has_tikhub_key ? 'ok' : 'warn',
    })
  }
  return out
})
</script>

<template>
  <div v-if="store.config" class="status-bar">
    <button
      v-for="item in items"
      :key="item.label"
      class="tag"
      :class="item.status"
      title="查看数据源详情"
      @click="router.push('/about')"
    >
      <span class="dot" :class="item.status"></span>
      {{ item.label }}
    </button>
    <span class="dim">区域 {{ store.config.fastmoss_region }} · 模型 {{ store.config.llm_model }}</span>
  </div>
</template>

<style scoped>
.status-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.tag {
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 3px 12px;
  font-size: 12px;
  background: var(--bg-card);
  color: var(--text-dim);
  cursor: pointer;
  transition: all var(--dur) var(--ease);
  box-shadow: var(--shadow-sm);
}

.tag:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
}

.tag.ok { color: var(--success); }
.tag.warn { color: var(--warn); }

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: 0 0 auto;
}

.dot.ok {
  background: var(--success);
  box-shadow: 0 0 0 3px var(--success-bg);
}

.dot.warn {
  background: var(--warn);
  box-shadow: 0 0 0 3px var(--warn-bg);
}

.dim {
  font-size: 12px;
  color: var(--text-faint);
  margin-left: 4px;
}
</style>
