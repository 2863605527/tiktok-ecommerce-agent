<script setup lang="ts">
// 选品工作台（KeepAlive name=workbench：切走再回来流水线进度不丢）
defineOptions({ name: 'workbench' })
import { onMounted, ref } from 'vue'
import { useSelectionStore } from '@/stores/selection'
import { selectionApi, type SavedSelection } from '@/api/selection'
import { useToastStore } from '@/stores/toast'
import CategoryPicker from '@/components/CategoryPicker.vue'
import StageSelector from '@/components/StageSelector.vue'
import StatusBar from '@/components/StatusBar.vue'
import ProductsPanel from '@/components/ProductsPanel.vue'
import ReportPanel from '@/components/ReportPanel.vue'
import OffersPanel from '@/components/OffersPanel.vue'
import ListingPanel from '@/components/ListingPanel.vue'
import type { StageKey } from '@/api/types'
import type { ProfitResult } from '@/api/types'
import { businessApi } from '@/api/business'

const store = useSelectionStore()
const toast = useToastStore()

// ---- 经营测算：单件利润（售价 JPY + 成本/运费 CNY） ----
const profitInput = ref({
  selling: '',
  cost: '',
  shipping: '',
  ads: '',
})
const profitResult = ref<ProfitResult | null>(null)
const profitBusy = ref(false)

/** 一键代入当前结果：竞品最低售价 → 售价，货源最低价 → 进价 */
function fillProfitFromResult() {
  const r = store.result
  if (!r) {
    toast.info('还没有选品结果，先跑一次流水线再代入')
    return
  }
  const prices = (r.products ?? [])
    .map((p) => parseFloat(String(p.price).replace(/[^0-9.]/g, '')))
    .filter((n) => Number.isFinite(n) && n > 0)
  const offers = (r.offers ?? [])
    .map((o) => parseFloat(String(o.price).replace(/[^0-9.]/g, '')))
    .filter((n) => Number.isFinite(n) && n > 0)
  if (prices.length) profitInput.value.selling = String(Math.min(...prices))
  if (offers.length) profitInput.value.cost = String(Math.min(...offers))
  toast.success('已代入当前竞品最低售价与货源最低进价')
}

async function calcProfit() {
  const selling = parseFloat(profitInput.value.selling)
  const cost = parseFloat(profitInput.value.cost)
  if (!Number.isFinite(selling) || selling <= 0 || !Number.isFinite(cost) || cost < 0) {
    toast.error('售价（JPY）必填，成本（CNY）必填')
    return
  }
  profitBusy.value = true
  try {
    profitResult.value = await businessApi.estimateProfit({
      selling_price_jpy: selling,
      cost_cny: cost,
      shipping_cny: parseFloat(profitInput.value.shipping) || 0,
      ads_jpy: parseFloat(profitInput.value.ads) || 0,
    })
    toast.success('利润测算完成')
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '测算失败')
  } finally {
    profitBusy.value = false
  }
}

function fmtJpy(v: number | undefined | null): string {
  if (v == null || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat('ja-JP').format(Math.round(v)) + ' JPY'
}

// 历史结果库（按用户隔离，跨设备持久化）
const history = ref<SavedSelection[]>([])
const historyLoading = ref(false)

/** 批量商品输入：每行一个商品，串行逐个分析 */
async function runBatch() {
  const items = store.product.split('\n').map((s) => s.trim()).filter((s) => s.length)
  if (!items.length || store.running) return
  if (items.length > 1) {
    toast.info(`批量选品：共 ${items.length} 个商品，逐个分析中…`)
  }
  await store.runBatch(items)
  if (items.length > 1) toast.success(`批量分析完成（${items.length} 个商品）`)
  refreshHistory()
}

async function refreshHistory() {
  historyLoading.value = true
  try {
    history.value = await selectionApi.listHistory()
  } catch {
    history.value = []
  } finally {
    historyLoading.value = false
  }
}

/** 回放历史结果 */
function replayHistory(rec: SavedSelection) {
  store.replay(rec.result, rec.product)
  toast.info(`已载入历史结果：${rec.product}`)
}

/** 删除历史记录（防误触） */
async function deleteHistory(rec: SavedSelection) {
  if (!window.confirm(`确定删除「${rec.product}」这条历史结果吗？`)) return
  try {
    await selectionApi.deleteHistory(rec.id)
    toast.success('历史记录已删除')
    refreshHistory()
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '删除失败')
  }
}

function histTime(ts: string): string {
  try {
    return new Date(ts.replace(' ', 'T')).toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return ts
  }
}

onMounted(refreshHistory)

// 已勾选且已完成的阶段（进度轨道打勾）
function isStageDone(stage: string): boolean {
  const order: StageKey[] = ['crawler', 'analyzer', 'sourcing', 'listing']
  const idx = order.indexOf(stage as StageKey)
  if (idx < 0) return false
  const cur = order.indexOf((store.stage ?? 'crawler') as StageKey)
  return idx < cur
}

const REGIONS = [
  { value: 'JP', label: '日本 JP（主推）' },
  { value: 'US', label: '美国 US' },
  { value: 'UK', label: '欧洲 UK' },
  { value: 'SG', label: '新加坡 SG' },
]

const LANGUAGES = [
  { value: 'ja', label: '日本語（默认·日本站）' },
  { value: 'en', label: 'English 英语' },
  { value: 'es', label: 'Español 西语' },
  { value: 'fr', label: 'Français 法语' },
  { value: 'de', label: 'Deutsch 德语' },
  { value: 'ko', label: '한국어 韩语' },
]
</script>

<template>
  <div class="workbench">
    <!-- 数据源状态 -->
    <StatusBar />

    <!-- ① 品类选择 -->
    <section class="card">
      <h2><span class="step">1</span> 选择品类</h2>
      <p class="hint">主推「床上用品」，其余品类为扩展体系（分析/货源按品类注入不同领域知识）</p>
      <CategoryPicker />
    </section>

    <!-- ② 阶段选择 -->
    <section class="card">
      <h2><span class="step">2</span> 选择流程阶段</h2>
      <p class="hint">只勾选需要的阶段，流水线自动裁剪（如只跑「分析」可跳过采集）</p>
      <StageSelector />
    </section>

    <!-- ③ 参数与运行 -->
    <section class="card">
      <h2><span class="step">3</span> 输入商品信息</h2>
      <p class="hint">支持批量：每行一个商品（如 牛奶绒床笠 换行 法兰绒四件套），串行逐个分析</p>
      <div class="form">
        <label class="full">
          <span>商品关键词 / 链接（多行 = 批量）</span>
          <textarea v-model="store.product" rows="2" maxlength="600"
            placeholder="例：純棉 ボックスシーツ 1.8m&#10;例：法兰绒床笠（批量时每行一个）" />
        </label>
        <label>
          <span>目标市场</span>
          <select v-model="store.region">
            <option v-for="r in REGIONS" :key="r.value" :value="r.value">{{ r.label }}</option>
          </select>
        </label>
        <label>
          <span>上架文案语言</span>
          <select v-model="store.language">
            <option v-for="l in LANGUAGES" :key="l.value" :value="l.value">{{ l.label }}</option>
          </select>
        </label>
        <div class="run-wrap">
          <button class="run-btn" :disabled="store.running || !store.product.trim()" @click="runBatch">
            {{ store.running ? '运行中…' : '运行流水线' }}
          </button>
        </div>
      </div>

      <!-- 运行进度（SSE 实时推送各阶段） -->
      <div v-if="store.running" class="progress-box">
        <div class="progress-stage">
          <span class="progress-spinner"></span>
          <span class="progress-text">{{ store.stageText }}</span>
        </div>
        <div class="progress-track">
          <div
            v-for="(label, key) in store.STAGE_LABEL"
            :key="key"
            class="progress-step"
            :class="{ active: store.stage === key, done: isStageDone(key) }"
          >
            <span class="step-dot">{{ store.stage === key ? '●' : isStageDone(key) ? '✓' : '○' }}</span>
            <span>{{ label }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 错误提示 -->
    <div v-if="store.error" class="error-banner">
      {{ store.error }}
    </div>

    <!-- 结果 -->
    <div v-if="store.hasResult" class="results">
      <ProductsPanel />
      <ReportPanel />
      <OffersPanel />
      <ListingPanel />
    </div>

    <!-- 空状态引导 -->
    <div v-else-if="!store.error" class="empty">
      <div class="empty-icon">🔍</div>
      <p>输入关键词后点击「运行流水线」。</p>
      <p class="dim">流程：采集竞品 → 评论入库向量库 → RAG 痛点聚类 → 找家纺网货源六维匹配 → 生成日文上架素材</p>
    </div>

    <!-- 选品历史库（企业级：跨设备持久化，按用户隔离） -->
    <section class="card">
      <h2>
        <span class="step">5</span> 选品历史（自动存档）
        <button class="mini-btn" :disabled="historyLoading" @click="refreshHistory">刷新</button>
      </h2>
      <p class="hint">每次运行自动存入结果库；可回放完整结果或删除。登录同一账号跨设备可见。</p>
      <div v-if="historyLoading" class="hist-hint">加载中…</div>
      <div v-else-if="!history.length" class="hist-hint">暂无历史结果，运行一次流水线后自动存档</div>
      <div v-else class="hist-list">
        <div v-for="rec in history.slice(0, 30)" :key="rec.id" class="hist-item">
          <div class="hist-main">
            <div class="hist-title">{{ rec.product }}</div>
            <div class="hist-meta">
              <span class="hist-time">{{ histTime(rec.created_at) }}</span>
              <span class="hist-badge" :class="rec.status === 'ok' ? 'ok' : 'err'">
                {{ rec.status === 'ok' ? '成功' : '失败' }}
              </span>
              <span class="hist-counts">
                {{ rec.result?.products?.length ?? 0 }} 竞品 · {{ rec.result?.offers?.length ?? 0 }} 货源
              </span>
            </div>
          </div>
          <div class="hist-actions">
            <button class="mini-btn" title="回放完整结果" @click="replayHistory(rec)">回放</button>
            <button class="mini-btn danger" title="删除该条历史" @click="deleteHistory(rec)">删除</button>
          </div>
        </div>
      </div>
    </section>

    <!-- 经营测算：单件利润（真实卖家最关心：能不能赚钱） -->
    <section class="card">
      <h2>
        <span class="step">6</span> 利润测算（单件）
        <button class="mini-btn" title="用当前选品结果的竞品最低售价 + 货源最低进价填充"
          @click="fillProfitFromResult">
          一键代入当前结果
        </button>
      </h2>
      <p class="hint">售价单位 JPY；进价/运费单位 CNY（汇率与平台费率可配，见 .env FX_CNY_JPY）。</p>
      <div class="profit-form">
        <label><span>售价（JPY）</span>
          <input v-model="profitInput.selling" type="number" min="0" placeholder="如 3500" />
        </label>
        <label><span>进价（CNY）</span>
          <input v-model="profitInput.cost" type="number" min="0" placeholder="如 85" />
        </label>
        <label><span>运费（CNY，可选）</span>
          <input v-model="profitInput.shipping" type="number" min="0" placeholder="如 40" />
        </label>
        <label><span>单件广告（JPY，可选）</span>
          <input v-model="profitInput.ads" type="number" min="0" placeholder="如 500" />
        </label>
        <div class="profit-run">
          <button class="run-btn small" :disabled="profitBusy" @click="calcProfit">
            {{ profitBusy ? '测算中…' : '测算利润' }}
          </button>
        </div>
      </div>

      <div v-if="profitResult" class="profit-result" :class="profitResult.net_profit_jpy >= 0 ? 'ok' : 'bad'">
        <div class="pr-grid">
          <div class="pr-cell"><span class="pr-k">售价</span><span class="pr-v">{{ fmtJpy(profitResult.selling_price_jpy) }}</span></div>
          <div class="pr-cell"><span class="pr-k">总成本(进价+运费)</span><span class="pr-v">{{ fmtJpy(profitResult.cost_jpy + profitResult.shipping_jpy) }}</span></div>
          <div class="pr-cell"><span class="pr-k">毛利</span><span class="pr-v">{{ fmtJpy(profitResult.gross_profit_jpy) }}</span></div>
          <div class="pr-cell"><span class="pr-k">佣金+支付费</span><span class="pr-v">{{ fmtJpy(profitResult.platform_fee_jpy + profitResult.payment_fee_jpy) }}</span></div>
          <div class="pr-cell pr-net"><span class="pr-k">净利</span>
            <span class="pr-v">{{ fmtJpy(profitResult.net_profit_jpy) }}（{{ (profitResult.net_margin * 100).toFixed(1) }}%）</span>
          </div>
          <div class="pr-cell"><span class="pr-k">广告回本</span>
            <span class="pr-v">{{ profitResult.break_even_units ? `约 ${profitResult.break_even_units} 件` : '—' }}</span>
          </div>
        </div>
        <div class="pr-note">{{ profitResult.note }}</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.workbench {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 20px;
}

.card h2 {
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: var(--primary-bg);
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
}

.hint {
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 14px;
}

.form {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: 12px;
  align-items: end;
}

.form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--text-dim);
}

.form label.full {
  grid-column: 1 / -1;
}

.form input,
.form select,
.form textarea {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 10px 12px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
}

.form input:focus,
.form select:focus,
.form textarea:focus {
  outline: none;
  border-color: var(--primary);
}

.run-wrap {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
}

.run-btn {
  background: var(--primary);
  border: none;
  color: #fff;
  border-radius: var(--radius-md);
  padding: 12px 36px;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: background var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
  box-shadow: 0 1px 2px rgba(46, 92, 255, 0.3);
}

.run-btn:hover:not(:disabled) {
  background: var(--primary-hover);
  box-shadow: 0 4px 12px rgba(46, 92, 255, 0.25);
}

.run-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-banner {
  background: var(--danger-bg);
  color: var(--danger);
  border: 1px solid var(--danger);
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 13px;
}

/* ---- 运行进度（SSE 实时） ---- */
.progress-box {
  margin-top: 14px;
  background: var(--primary-bg);
  border: 1px solid rgba(37, 99, 235, 0.2);
  border-radius: 10px;
  padding: 12px 14px;
}

.progress-stage {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--primary);
}

.progress-spinner {
  width: 13px;
  height: 13px;
  border-radius: 50%;
  border: 2px solid rgba(37, 99, 235, 0.2);
  border-top-color: var(--primary);
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.progress-track {
  display: flex;
  gap: 10px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.progress-step {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-dim);
}

.progress-step.active {
  color: var(--primary);
  font-weight: 700;
}

.progress-step.done {
  color: var(--success);
}

.step-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  font-size: 11px;
}

.results {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty {
  text-align: center;
  padding: 48px 0;
  color: var(--text-dim);
}

.empty-icon {
  font-size: 36px;
  margin-bottom: 12px;
}

.empty .dim {
  font-size: 12px;
  margin-top: 6px;
  color: var(--border);
}

/* ---- 选品历史 ---- */
.mini-btn {
  margin-left: auto;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-dim);
  border-radius: var(--radius-sm);
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}

.mini-btn:hover:not(:disabled) {
  color: var(--primary);
  border-color: var(--primary);
}

.mini-btn.danger:hover:not(:disabled) {
  color: var(--danger);
  border-color: var(--danger);
}

.mini-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.hist-hint {
  font-size: 12px;
  color: var(--text-dim);
  padding: 12px 0;
}

.hist-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hist-item {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
}

.hist-main {
  flex: 1;
  min-width: 0;
}

.hist-title {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hist-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 3px;
  flex-wrap: wrap;
}

.hist-badge {
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 10px;
  font-weight: 700;
}

.hist-badge.ok {
  background: var(--success-bg);
  color: var(--success);
}

.hist-badge.err {
  background: var(--danger-bg);
  color: var(--danger);
}

.hist-counts {
  color: var(--text-faint);
}

.hist-actions {
  display: flex;
  gap: 6px;
  flex: 0 0 auto;
}

/* ---- 利润测算 ---- */
.profit-form {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  align-items: end;
}

.profit-form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--text-dim);
}

.profit-form input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 10px 12px;
  font-size: 14px;
  font-family: inherit;
}

.profit-form input:focus {
  outline: none;
  border-color: var(--primary);
}

.profit-run {
  display: flex;
  justify-content: flex-end;
}

.run-btn.small {
  padding: 10px 22px;
  font-size: 13px;
}

.profit-result {
  margin-top: 14px;
  border-radius: 10px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  background: var(--bg);
}

.profit-result.ok {
  border-left: 4px solid var(--success);
}

.profit-result.bad {
  border-left: 4px solid var(--danger);
}

.pr-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.pr-cell {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.pr-k {
  font-size: 11px;
  color: var(--text-dim);
}

.pr-v {
  font-size: 14px;
  font-weight: 800;
  color: var(--text);
}

.profit-result.ok .pr-net .pr-v {
  color: var(--success);
}

.profit-result.bad .pr-net .pr-v {
  color: var(--danger);
}

.pr-note {
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-faint);
  line-height: 1.6;
}

@media (max-width: 720px) {
  .form {
    grid-template-columns: 1fr;
  }
  .profit-form {
    grid-template-columns: 1fr 1fr;
  }
  .pr-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
