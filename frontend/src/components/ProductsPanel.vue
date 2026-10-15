<script setup lang="ts">
import { computed, ref } from 'vue'
import { useSelectionStore } from '@/stores/selection'
import type { Product } from '@/api/types'
import { useToastStore } from '@/stores/toast'

const store = useSelectionStore()
const toast = useToastStore()
const products = computed(() => store.result?.products ?? [])

// ---- 竞品对比：勾选 2+ 个 → 对比表格（价格/热度/口碑/链接） ----
const selected = ref<Set<string>>(new Set())
const showCompare = ref(false)

function toggle(p: Product) {
  const key = p.id || p.title
  if (selected.value.has(key)) {
    selected.value.delete(key)
  } else {
    selected.value.add(key)
  }
  // 触发响应式
  selected.value = new Set(selected.value)
}

function clearSel() {
  selected.value = new Set()
  showCompare.value = false
}

function openCompare() {
  const sel = products.value.filter((p) => selected.value.has(p.id || p.title))
  if (sel.length < 2) {
    toast.info('至少勾选 2 个竞品再对比')
    return
  }
  compareItems.value = sel
  showCompare.value = true
}

const compareItems = ref<Product[]>([])

function fmtNum(v: number | null | undefined): string {
  if (v == null) return '—'
  return v.toLocaleString()
}

/** 找最低价高亮 */
function isMinPrice(p: Product): boolean {
  const nums = compareItems.value
    .map((x) => parseFloat(String(x.price).replace(/[^0-9.]/g, '')))
    .filter((n) => Number.isFinite(n) && n > 0)
  const mine = parseFloat(String(p.price).replace(/[^0-9.]/g, ''))
  return nums.length > 0 && Number.isFinite(mine) && mine === Math.min(...nums)
}
</script>

<template>
  <section v-if="products.length" class="panel">
    <h3 class="panel-title">
      ① 竞品采集（{{ products.length }} 个）
      <span class="badge">数据源: {{ store.config && store.config.product_source !== 'sample' ? (store.config.product_source === 'fastmoss' ? 'FastMoss 真实数据' : store.config.product_source + ' 真实数据') : '本地样本' }}</span>
      <span class="compare-actions">
        <button class="mini-btn" :disabled="selected.size === 0" @click="clearSel">
          取消选择（{{ selected.size }}）
        </button>
        <button class="cmp-btn" :disabled="selected.size < 2" @click="openCompare">
          对比所选（{{ selected.size }}）
        </button>
      </span>
    </h3>

    <div class="grid">
      <article v-for="p in products" :key="p.id || p.title" class="product-card"
        :class="{ selected: selected.has(p.id || p.title) }">
        <label class="sel-row">
          <input type="checkbox" class="sel-box" :checked="selected.has(p.id || p.title)"
            @change="toggle(p)" />
          <span class="sel-hint">加入对比</span>
        </label>
        <div class="p-title">{{ p.title }}</div>
        <div class="p-meta">
          <span class="price">{{ p.price }} {{ p.currency }}</span>
          <span v-if="p.sales > 0" class="sales">销量 {{ p.sales.toLocaleString() }}</span>
          <span v-else-if="p.rating || p.reviews_count" class="sales">热度 评分{{ p.rating ?? '—' }} · 评论{{ p.reviews_count ?? 0 }}</span>
          <span v-else class="sales">销量未披露</span>
          <span v-if="p.seller" class="cat">{{ p.seller }}</span>
          <span v-if="p.category" class="cat">{{ p.category }}</span>
          <span v-if="p.lifecycle_stage" class="stage-badge"
            :class="'stage-' + p.lifecycle_stage"
            :title="(p.lifecycle_window || '') + '（置信度 ' + (p.lifecycle_confidence || '低') + '）'">
            {{ p.lifecycle_stage }} {{ p.lifecycle_trend === '上升' ? '↗' : p.lifecycle_trend === '下降' ? '↘' : '→' }}
          </span>
        </div>
        <div v-if="p.reviews?.length" class="reviews">
          <div v-for="(r, i) in p.reviews.slice(0, 3)" :key="i" class="review">
            <span class="stars">{{ '★'.repeat(Math.round(r.rating)) }}<span class="dim-star">{{ '★'.repeat(5 - Math.round(r.rating)) }}</span></span>
            {{ r.content }}
          </div>
        </div>
        <a v-if="p.url" :href="p.url" target="_blank" rel="noreferrer" class="link">查看商品 ↗</a>
      </article>
    </div>

    <!-- 竞品对比表格（勾选 2+ 弹出） -->
    <div v-if="showCompare" class="compare-panel">
      <div class="compare-head">
        <span class="cmp-title">⚖ 竞品对比（{{ compareItems.length }} 个 · 最低价已高亮）</span>
        <button class="mini-btn" @click="showCompare = false">关闭 ✕</button>
      </div>
      <div class="table-wrap">
        <table class="cmp-table">
          <thead>
            <tr>
              <th class="cmp-col">指标</th>
              <th v-for="p in compareItems" :key="p.id || p.title" class="cmp-col">
                {{ (p.title || '').slice(0, 22) }}{{ (p.title || '').length > 22 ? '…' : '' }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="cmp-k">价格</td>
              <td v-for="p in compareItems" :key="p.id || p.title"
                :class="['cmp-v price', { 'min-price': isMinPrice(p) }]">
                {{ p.price }} {{ p.currency }}
              </td>
            </tr>
            <tr>
              <td class="cmp-k">销量</td>
              <td v-for="p in compareItems" :key="p.id || p.title" class="cmp-v">
                {{ p.sales > 0 ? fmtNum(p.sales) : '未披露' }}
              </td>
            </tr>
            <tr>
              <td class="cmp-k">评分</td>
              <td v-for="p in compareItems" :key="p.id || p.title" class="cmp-v">
                {{ p.rating ?? '—' }} <span v-if="p.reviews_count != null" class="dim">({{ p.reviews_count }} 评)</span>
              </td>
            </tr>
            <tr>
              <td class="cmp-k">卖家</td>
              <td v-for="p in compareItems" :key="p.id || p.title" class="cmp-v dim">{{ p.seller ?? '—' }}</td>
            </tr>
            <tr>
              <td class="cmp-k">生命周期</td>
              <td v-for="p in compareItems" :key="p.id || p.title" class="cmp-v">
                <span v-if="p.lifecycle_stage" class="stage-badge" :class="'stage-' + p.lifecycle_stage">
                  {{ p.lifecycle_stage }}
                </span>
                <span v-else class="dim">评论时间不足</span>
              </td>
            </tr>
            <tr>
              <td class="cmp-k">评论摘录</td>
              <td v-for="p in compareItems" :key="p.id || p.title" class="cmp-v dim">
                {{ p.reviews?.[0]?.content?.slice(0, 40) ?? '—' }}
              </td>
            </tr>
            <tr>
              <td class="cmp-k">链接</td>
              <td v-for="p in compareItems" :key="p.id || p.title" class="cmp-v">
                <a v-if="p.url" :href="p.url" target="_blank" rel="noreferrer" class="link">打开 ↗</a>
                <span v-else>—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
}

.panel-title {
  font-size: 15px;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.badge {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-dim);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 2px 8px;
}

.compare-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
  align-items: center;
}

.mini-btn {
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-dim);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 11px;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}

.mini-btn:hover:not(:disabled) {
  color: var(--primary);
  border-color: var(--primary);
}

.mini-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.cmp-btn {
  border: 1px solid var(--primary);
  background: var(--primary-bg);
  color: var(--primary);
  border-radius: 6px;
  padding: 4px 12px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}

.cmp-btn:hover:not(:disabled) {
  background: var(--primary);
  color: #fff;
}

.cmp-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.product-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: all var(--dur) var(--ease);
}

.product-card.selected {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-bg);
}

.sel-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-dim);
  cursor: pointer;
  align-self: flex-start;
}

.sel-box {
  accent-color: var(--primary);
  cursor: pointer;
}

.sel-hint {
  user-select: none;
}

.p-title {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.p-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
}

.price {
  color: var(--primary);
  font-weight: 700;
}

.sales {
  color: var(--text-dim);
}

.cat {
  color: var(--warn);
  font-size: 11px;
  border: 1px solid var(--warn);
  border-radius: 4px;
  padding: 0 6px;
}

/* 生命周期阶段徽章（浅色主题） */
.stage-badge {
  font-size: 11px;
  font-weight: 600;
  border-radius: 10px;
  padding: 1px 8px;
  display: inline-block;
  white-space: nowrap;
}
.stage-萌芽期 { background: #e8f5e9; color: #2e7d32; border: 1px solid #a5d6a7; }
.stage-成长期 { background: #e3f2fd; color: #1565c0; border: 1px solid #90caf9; }
.stage-爆款期 { background: #fff8e1; color: #b26a00; border: 1px solid #ffe082; }
.stage-衰退期 { background: #fbe9e7; color: #c62828; border: 1px solid #ef9a9a; }

.reviews {
  border-top: 1px dashed var(--border);
  padding-top: 8px;
  font-size: 12px;
  color: var(--text-dim);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.review {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stars {
  color: var(--warn);
  margin-right: 6px;
}

.dim-star {
  color: var(--border);
}

.link {
  font-size: 12px;
  align-self: flex-start;
}

/* ---- 对比表格 ---- */
.compare-panel {
  margin-top: 14px;
  border: 1px solid var(--primary);
  border-radius: var(--radius);
  overflow: hidden;
}

.compare-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--primary-bg);
  padding: 8px 14px;
}

.cmp-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--primary);
}

.table-wrap {
  overflow-x: auto;
}

.cmp-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.cmp-table th,
.cmp-table td {
  padding: 9px 12px;
  border: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
  min-width: 120px;
}

.cmp-table thead th {
  background: var(--bg-soft);
  font-weight: 600;
  color: var(--text-dim);
  word-break: break-word;
}

.cmp-k {
  background: var(--bg-soft);
  font-weight: 700;
  color: var(--text-dim);
  white-space: nowrap;
  min-width: 60px;
}

.cmp-v {
  word-break: break-word;
}

.dim {
  color: var(--text-faint);
}

.min-price {
  color: var(--success);
  font-weight: 800;
}

.min-price::after {
  content: ' ✓最低';
  font-size: 10px;
  font-weight: 600;
  color: var(--success);
}
</style>
