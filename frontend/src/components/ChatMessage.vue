<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ChatMessage, SupplierOffer } from '@/api/types'
import { useFavoritesStore } from '@/stores/favorites'
import { useToastStore } from '@/stores/toast'

const props = defineProps<{ msg: ChatMessage }>()
const emit = defineEmits<{ (e: 'retry'): void }>()

const fav = useFavoritesStore()
const toast = useToastStore()

const isUser = computed(() => props.msg.role === 'user')
const expanded = ref(true)
const copied = ref<'ja' | 'en' | ''>('')
// 评论证据展开：topic → boolean（默认收起，点击展开 RAG 命中的评论原文）
const evidenceOpen = ref<Record<string, boolean>>({})
// 定价助手：货源价格带（最低/中位/最高）+ 建议售价（估算）
const priceGuide = computed<{ min: number; mid: number; max: number; suggest: number } | null>(() => {
  const offers: SupplierOffer[] = props.msg.data?.offers ?? []
  const nums = offers
    .map((o) => parseFloat(String(o.price).replace(/[^0-9.]/g, '')))
    .filter((n) => Number.isFinite(n) && n > 0)
  if (!nums.length) return null
  const sorted = [...nums].sort((a, b) => a - b)
  const mid = sorted[Math.floor(sorted.length / 2)]
  return {
    min: sorted[0],
    mid,
    max: sorted[sorted.length - 1],
    // TikTok 常见 3x 定价（含平台佣金/物流/退货损耗），标注估算
    suggest: Math.round(mid * 3),
  }
})

const isError = computed(() => !isUser.value && props.msg.content.includes('出错了'))

const intentLabel = computed(() => {
  const map: Record<string, string> = {
    select_product: '选品分析',
    sourcing_only: '货源匹配',
    listing_only: '上架素材',
    profit: '利润测算',
    qa_ecommerce: '电商引导',
    out_of_scope: '范围外',
    self_intro: '自我介绍',
    switch_supplier: '货源平台切换',
  }
  return props.msg.intent ? map[props.msg.intent] || '' : ''
})

function stageTag(stage: string): string {
  const map: Record<string, string> = {
    crawler: '调用搜索',
    analyzer: 'RAG 分析',
    sourcing: '匹配货源',
    listing: '生成素材',
  }
  return map[stage] || '处理中'
}

function visualClass(label: string): string {
  if (label === '疑似同款') return 'vis-hit'
  if (label === '相似款') return 'vis-sim'
  return 'vis-far'
}

function matchPct(score: number): number {
  return Math.round((score || 0) * 100)
}

/** 图片加载失败 → 占位（不破版） */
function onImgError(e: Event) {
  const el = e.target as HTMLImageElement
  el.style.visibility = 'hidden'
  const holder = el.parentElement
  if (holder) holder.classList.add('img-fallback')
}

/** 复制完整上架素材（日文/英文版） */
async function copyListing(lang: 'ja' | 'en') {
  const l = props.msg.data?.listing
  if (!l) return
  const text =
    `【商品标题】${l.title}\n\n` +
    `【关键词】${(l.keywords || []).join(' / ')}\n` +
    `【话题标签】${(l.hashtags || []).join(' ')}\n\n` +
    `【商品描述】\n${l.description ?? ''}\n` +
    (lang === 'ja' && l.specs_translated
      ? `\n【规格翻译】\n` + Object.entries(l.specs_translated).map(([k, v]) => `${k}: ${v}`).join('\n')
      : '')
  try {
    await navigator.clipboard.writeText(text)
    copied.value = lang
    toast.success(lang === 'ja' ? '日文素材已复制' : '英文素材已复制')
    setTimeout(() => (copied.value = ''), 1600)
  } catch {
    toast.error('复制失败，请手动选择复制')
  }
}

/** 导出选品评估报告（Markdown 下载） */
function exportReport() {
  const d = props.msg.data
  if (!d?.report) return
  const r = d.report
  const lines: string[] = [
    '# 选品评估报告',
    '',
    `> 导出时间：${new Date().toLocaleString('zh-CN')}`,
    '',
    '## 结论',
    '',
    r.summary || '',
    '',
    r.suggestion ? `> 💡 ${r.suggestion}\n` : '',
  ]
  if (r.pros?.length) lines.push('## 优势', '', ...r.pros.map((x) => `- ${x}`), '')
  if (r.cons?.length) lines.push('## 风险与不足', '', ...r.cons.map((x) => `- ${x}`), '')
  if (r.market_hot) lines.push('## 市场热度', '', r.market_hot, '')
  if (r.competition) lines.push('## 竞争情况', '', r.competition, '')
  if (r.keywords?.length) lines.push('## 关键词', '', (r.keywords || []).join(' / '), '')
  if (r.insights?.length) {
    lines.push('## 评论洞察（RAG）', '')
    for (const ins of r.insights) {
      lines.push(`- **${ins.topic}**（${ins.sentiment === 'negative' ? '负面' : '正面'} ${ins.mentions}条）`)
      if (ins.evidence?.length) lines.push(`  > ${ins.evidence.slice(0, 2).join('；')}`)
    }
    lines.push('')
  }
  if (d.offers?.length) {
    lines.push('## 货源（找家纺网）', '')
    for (const o of d.offers) {
      lines.push(`- **${o.title}** · ${o.price} · ${o.supplier_name}${o.url ? ` · ${o.url}` : ''}`)
    }
    lines.push('')
  }
  if (d.products?.length) {
    lines.push('## 竞品', '')
    for (const p of d.products) {
      lines.push(`- **${p.title}** · ${p.price} ${p.currency ?? ''}${p.url ? ` · ${p.url}` : ''}`)
    }
  }
  const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `选品评估_${new Date().toISOString().slice(0, 10)}.md`
  a.click()
  URL.revokeObjectURL(a.href)
  toast.success('评估报告已导出（Markdown）')
}

/** 收藏：竞品 / 货源 / 素材 */
function favProduct(p: { title: string; price?: string; url?: string; images?: string[]; sales?: number }) {
  fav.add({
    kind: 'product',
    title: p.title,
    price: p.price,
    url: p.url,
    images: p.images,
    extra: (p.sales ?? 0) > 0 ? `销量 ${p.sales}` : '销量未披露',
  })
  toast.success('已收藏竞品')
}
function favOffer(o: { title: string; price?: string; url?: string; images?: string[]; supplier_name?: string; match_score?: number }) {
  fav.add({
    kind: 'offer',
    title: o.title,
    price: o.price,
    url: o.url,
    images: o.images,
    extra: `${o.supplier_name ?? ''} · 匹配 ${matchPct(o.match_score ?? 0)}%`,
  })
  toast.success('已收藏货源')
}

function toggleEvidence(topic: string) {
  evidenceOpen.value[topic] = !evidenceOpen.value[topic]
}

// ---- 推荐评分卡（第三轮） ----
const scoreLevel = computed(() => {
  const total = props.msg.data?.score?.total ?? 0
  if (total >= 80) return 'strong'
  if (total >= 65) return 'good'
  if (total >= 50) return 'mid'
  return 'low'
})
const scoreDims = computed(() => {
  const dims = props.msg.data?.score?.dims
  if (!dims) return []
  return [
    dims.heat, dims.demand, dims.supply, dims.listing,
  ].filter(Boolean)
})
const scoreReasons = computed(() => {
  const dims = props.msg.data?.score?.dims
  if (!dims) return []
  const reasons: string[] = []
  for (const key of ['heat', 'demand', 'supply', 'listing'] as const) {
    const d = dims[key]
    if (d?.reasons) reasons.push(...d.reasons.slice(0, 2))
  }
  return reasons.slice(0, 6)
})

function fmtJpy(v: number | undefined | null): string {
  if (v == null || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat('ja-JP').format(Math.round(v)) + ' JPY'
}

async function copyKeywords() {
  const top = props.msg.data?.keyword_insights?.top
  if (!top?.length) return
  const text = top.map((k) => k.word).join(' / ')
  try {
    await navigator.clipboard.writeText(text)
    toast.success('关键词已复制（' + top.length + ' 个）')
  } catch {
    toast.error('复制失败，请手动选择复制')
  }
}
</script>

<template>
  <div class="row" :class="isUser ? 'row-user' : 'row-ai'">
    <div class="avatar" :class="isUser ? 'avatar-user' : 'avatar-ai'">
      {{ isUser ? '我' : 'AI' }}
    </div>
    <div class="bubble-wrap">
      <div class="bubble" :class="isUser ? 'bubble-user' : 'bubble-ai'">
        <div v-if="intentLabel && !isUser" class="intent-tag">{{ intentLabel }}</div>

        <!-- 深度思考过程（大模型 agent 式）：思考中实时展开，完成后可折叠 -->
        <div v-if="msg.steps && msg.steps.length" class="think-box">
          <button class="think-header" @click="expanded = !expanded">
            <span v-if="msg.thinking" class="spinner"></span>
            <span class="think-title">
              {{ msg.thinking ? '深度思考中…' : `已思考（用时${msg.thinkingSeconds ?? 0}秒）` }}
            </span>
            <span class="think-chevron">{{ expanded ? '▾' : '▸' }}</span>
          </button>
          <div v-if="expanded" class="think-steps">
            <div v-for="(s, i) in msg.steps" :key="i" class="think-step">
              <span class="step-tag">{{ stageTag(s.stage) }}</span>
              <span class="step-text">{{ s.text }}</span>
            </div>
          </div>
        </div>

        <!-- 思考中且无步骤（快速分支） -->
        <div v-else-if="msg.thinking" class="think-box">
          <div class="think-header">
            <span class="spinner"></span>
            <span class="think-title">深度思考中…</span>
          </div>
        </div>

        <!-- 最终答复：大模型式输出（生成中带打字光标） -->
        <pre v-if="msg.content" class="text" :class="{ 'text-error': isError }">
{{ msg.content }}<span v-if="msg.thinking && !msg.content" class="typing-cursor"></span>
        </pre>
        <div v-else-if="msg.thinking" class="typing-line">
          <span class="typing-cursor"></span>
        </div>

        <!-- 失败重试：点击重新发送同一条消息 -->
        <button v-if="isError && !msg.loading" class="retry-btn" @click="emit('retry')">
          ↻ 重试
        </button>
      </div>

      <!-- 结构化结果卡片 -->
      <div v-if="msg.data && !msg.thinking" class="cards">
        <!-- 竞品列表（含商品图） -->
        <div v-if="msg.data.products && msg.data.products.length" class="card">
          <div class="card-title">
            真实竞品（{{ msg.data.products.length }}）
            <button class="mini-btn" title="一键收藏全部竞品"
              @click="msg.data.products.slice(0, 5).forEach(favProduct)">
              收藏全部
            </button>
          </div>
          <div v-for="p in msg.data.products.slice(0, 5)" :key="p.id" class="prod-item">
            <div class="img-holder">
              <img v-if="p.images && p.images.length" :src="p.images[0]" class="prod-img" alt="商品图"
                loading="lazy" @error="onImgError" />
            </div>
            <div class="prod-main">
              <div class="prod-title">{{ p.title }}</div>
              <div class="prod-meta">
                <span class="price-tag">{{ p.price }} {{ p.currency }}</span>
                <span v-if="p.sales > 0" class="sales-tag">销量 {{ p.sales }}</span>
                <span v-else-if="p.rating || p.reviews_count" class="sales-tag">
                  评分{{ p.rating ?? '—' }} · 评论{{ p.reviews_count ?? 0 }}
                </span>
                <span v-else class="sales-tag dim-tag">销量未披露</span>
                <span v-if="p.lifecycle_stage" class="stage-badge"
                  :class="'stage-' + p.lifecycle_stage"
                  :title="(p.lifecycle_window || '') + '（置信度 ' + (p.lifecycle_confidence || '低') + '）'">
                  {{ p.lifecycle_stage }}
                </span>
              </div>
              <div class="prod-actions">
                <a v-if="p.url" :href="p.url" target="_blank" rel="noopener" class="prod-link">查看商品 →</a>
                <button class="fav-btn" :class="{ on: fav.has(p.title) }"
                  @click="favProduct(p)">
                  {{ fav.has(p.title) ? '★ 已收藏' : '☆ 收藏' }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 推荐评分卡（第三轮：量化决策） -->
        <div v-if="msg.data.score" class="card score-card">
          <div class="score-head">
            <span class="score-total" :class="'lv-' + scoreLevel">{{ msg.data.score.total }}</span>
            <div class="score-main">
              <div class="score-level">{{ msg.data.score.level }}</div>
              <div class="score-verdict">{{ msg.data.score.verdict }}</div>
            </div>
          </div>
          <div class="score-dims">
            <div v-for="dim in scoreDims" :key="dim.label" class="score-dim">
              <div class="dim-top">
                <span class="dim-label">{{ dim.label }}</span>
                <span class="dim-val">{{ dim.score }}/{{ dim.max }}</span>
              </div>
              <div class="dim-track">
                <span class="dim-fill" :style="{ width: (dim.score / dim.max) * 100 + '%' }"></span>
              </div>
            </div>
            <!-- 进场时机（生命周期旁路参考） -->
            <div v-if="msg.data.score.timing" class="score-dim timing-dim">
              <div class="dim-top">
                <span class="dim-label">{{ msg.data.score.timing.label }}</span>
                <span class="dim-val">{{ msg.data.score.timing.score }}<span class="dim-max">/{{ msg.data.score.timing.max }}</span></span>
              </div>
              <div class="dim-track">
                <span class="dim-fill" :style="{ width: (msg.data.score.timing.score / msg.data.score.timing.max) * 100 + '%' }"></span>
              </div>
              <div class="dim-note">旁路参考 · 基于竞品生命周期</div>
            </div>
          </div>
          <div class="score-reasons">
            <div v-for="(r, i) in scoreReasons" :key="i" class="score-reason">· {{ r }}</div>
          </div>
        </div>

        <!-- 市场价位分布（真实竞品价格聚合） -->
        <div v-if="msg.data.market_overview && msg.data.market_overview.sample_count > 0" class="card">
          <div class="card-title">
            市场价位分布（{{ msg.data.market_overview.sample_count }} 个竞品样本）
          </div>
          <div class="band-list">
            <div v-for="b in msg.data.market_overview.bands" :key="b.label" class="band-row">
              <span class="band-label">{{ b.label }}</span>
              <span class="band-track">
                <span class="band-fill" :style="{ width: Math.max(4, b.share * 100) + '%' }"></span>
              </span>
              <span class="band-count">{{ b.count }}</span>
            </div>
          </div>
          <div class="market-stats">
            <span>均价 {{ fmtJpy(msg.data.market_overview.avg_price) }}</span>
            <span>中位价 {{ fmtJpy(msg.data.market_overview.median_price) }}</span>
            <span v-if="msg.data.market_overview.note" class="dim-tag">{{ msg.data.market_overview.note }}</span>
          </div>
        </div>

        <!-- 关键词建议（报告/评论/竞品标题真实聚合） -->
        <div v-if="msg.data.keyword_insights && msg.data.keyword_insights.top.length" class="card">
          <div class="card-title">
            搜索关键词建议（上架/选品通用）
            <button class="mini-btn" @click="copyKeywords">复制全部</button>
          </div>
          <div class="kw-list">
            <span v-for="k in msg.data.keyword_insights.top.slice(0, 10)" :key="k.word" class="chip chip-pos"
              :title="k.source">
              {{ k.word }}
            </span>
          </div>
          <div v-if="msg.data.keyword_insights.note" class="kw-note">{{ msg.data.keyword_insights.note }}</div>
        </div>

        <!-- 分析报告 -->
        <div v-if="msg.data.report" class="card">
          <div class="card-title">
            选品评估
            <button class="mini-btn" title="导出评估报告（Markdown）" @click="exportReport">
              ⇩ 导出报告
            </button>
          </div>
          <div class="report-line">{{ msg.data.report.summary }}</div>
          <div v-if="msg.data.report.suggestion" class="report-line suggestion">
            💡 {{ msg.data.report.suggestion }}
          </div>
          <!-- 评论情感占比条 + 证据展开（点击展开 RAG 命中的真实评论原文） -->
          <div v-if="msg.data.report.insights && msg.data.report.insights.length" class="sentiment">
            <div class="sentiment-bar">
              <div
                v-for="ins in msg.data.report.insights.slice(0, 4)"
                :key="ins.topic"
                class="sentiment-row"
              >
                <button class="sent-topic-btn" :title="evidenceOpen[ins.topic] ? '收起评论证据' : '点击查看评论证据'"
                  @click="toggleEvidence(ins.topic)">
                  <span class="sent-topic">{{ ins.topic }}</span>
                  <span class="ev-chevron">{{ evidenceOpen[ins.topic] ? '▾' : '▸' }}</span>
                </button>
                <span class="sent-track">
                  <span
                    class="sent-fill"
                    :class="ins.sentiment === 'negative' ? 'fill-neg' : 'fill-pos'"
                    :style="{ width: Math.min(100, Math.max(8, (ins.mentions / 10) * 100)) + '%' }"
                  ></span>
                </span>
                <span class="sent-count" :class="ins.sentiment === 'negative' ? 'neg' : 'pos'">
                  {{ ins.mentions }} 条{{ ins.sentiment === 'negative' ? '·负面' : '·正面' }}
                </span>
              </div>
            </div>
            <!-- 证据原文（RAG 命中的真实评论） -->
            <div v-if="evidenceOpen[Object.keys(evidenceOpen).find((k) => evidenceOpen[k]) ?? '']"
              class="evidence-panel">
              <div v-for="(ins, i) in msg.data.report.insights.filter((x) => evidenceOpen[x.topic])" :key="i"
                class="evidence-block">
                <div class="ev-title">📄 {{ ins.topic }}（{{ ins.severity }}）</div>
                <div v-for="(e, j) in ins.evidence" :key="j" class="ev-line">“{{ e }}”</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 货源列表（含图片 + 详情超链接，点击跳转找家纺网） -->
        <div v-if="msg.data.offers && msg.data.offers.length" class="card">
          <div class="card-title">
            找家纺网真实货源（{{ msg.data.offers.length }}，均一件代发 · 按图相似度优先）
          </div>
          <!-- 定价助手：货源价格带 + 建议售价（估算，成本×3 覆盖佣金物流） -->
          <div v-if="priceGuide" class="price-guide">
            <span class="pg-label">💰 货源价格带</span>
            <span class="pg-range">¥{{ priceGuide.min }} ~ ¥{{ priceGuide.max }}</span>
            <span class="pg-mid">中位 ¥{{ priceGuide.mid }}</span>
            <span class="pg-suggest">建议售价 ≈ ¥{{ priceGuide.suggest }}（含佣金/物流，估算）</span>
          </div>
          <div class="offer-table">
            <div v-for="o in msg.data.offers" :key="o.title + o.supplier_name" class="offer-row">
              <div class="img-holder">
                <a v-if="o.images && o.images.length" :href="o.url || '#'" target="_blank" rel="noopener">
                  <img :src="o.images[0]" class="offer-img" alt="货源图" loading="lazy" @error="onImgError" />
                </a>
              </div>
              <div class="offer-left">
                <a v-if="o.url" :href="o.url" target="_blank" rel="noopener" class="offer-title-link">
                  {{ o.title }} ↗
                </a>
                <div v-else class="offer-title">{{ o.title }}</div>
                <div class="offer-supplier">{{ o.supplier_name }}</div>
                <div v-if="o.score_breakdown && o.score_breakdown.visual_label" class="offer-visual"
                  :class="visualClass(String(o.score_breakdown.visual_label))">
                  👁 {{ o.score_breakdown.visual_label }} · 匹配
                  <span class="match-track">
                    <span class="match-fill" :style="{ width: matchPct(o.match_score) + '%' }"></span>
                  </span>
                  {{ matchPct(o.match_score) }}%
                </div>
              </div>
              <div class="offer-right">
                <div class="offer-price">{{ o.price }}</div>
                <div class="offer-actions">
                  <a v-if="o.url" :href="o.url" target="_blank" rel="noopener" class="offer-go">查看 →</a>
                  <button class="fav-btn" :class="{ on: fav.has(o.title) }" @click="favOffer(o)">
                    {{ fav.has(o.title) ? '★' : '☆' }}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 上架素材 -->
        <div v-if="msg.data.listing" class="card">
          <div class="card-title">
            上架素材
            <span class="copy-group">
              <button class="mini-btn" @click="copyListing('ja')">
                {{ copied === 'ja' ? '✓ 已复制' : '复制日文' }}
              </button>
              <button class="mini-btn" @click="copyListing('en')">
                {{ copied === 'en' ? '✓ 已复制' : '复制英文' }}
              </button>
              <button class="mini-btn" :class="{ on: fav.has(msg.data.listing.title) }"
                @click="fav.addListing(msg.data.listing); toast.success('已收藏上架素材')">
                {{ fav.has(msg.data.listing.title) ? '★ 已收藏' : '☆ 收藏' }}
              </button>
            </span>
          </div>
          <div class="listing-title">{{ msg.data.listing.title }}</div>
          <div v-if="msg.data.listing.keywords" class="listing-kws">
            <span v-for="k in msg.data.listing.keywords.slice(0, 6)" :key="k" class="chip chip-pos">{{ k }}</span>
          </div>
          <div v-if="msg.data.listing.description" class="report-line">{{ msg.data.listing.description }}</div>
          <div v-if="msg.data.listing_path" class="listing-path">📄 {{ msg.data.listing_path }}</div>
        </div>

        <!-- 利润测算卡（聊天说"算下利润"自动估算） -->
        <div v-if="msg.data.profit" class="card profit-card">
          <div class="card-title">单件利润测算（估算）</div>
          <div class="profit-grid">
            <div class="p-cell"><span class="p-k">售价</span><span class="p-v">{{ fmtJpy(msg.data.profit.selling_price_jpy) }}</span></div>
            <div class="p-cell"><span class="p-k">进价折</span><span class="p-v">{{ fmtJpy(msg.data.profit.cost_jpy) }}</span></div>
            <div class="p-cell"><span class="p-k">运费折</span><span class="p-v">{{ fmtJpy(msg.data.profit.shipping_jpy) }}</span></div>
            <div class="p-cell"><span class="p-k">佣金+支付</span><span class="p-v">{{ fmtJpy(msg.data.profit.platform_fee_jpy + msg.data.profit.payment_fee_jpy) }}</span></div>
            <div class="p-cell p-net" :class="msg.data.profit.net_profit_jpy >= 0 ? 'p-pos' : 'p-neg'">
              <span class="p-k">净利</span>
              <span class="p-v">{{ fmtJpy(msg.data.profit.net_profit_jpy) }}
                <small>（{{ (msg.data.profit.net_margin * 100).toFixed(1) }}%）</small>
              </span>
            </div>
            <div v-if="msg.data.profit.break_even_units" class="p-cell p-full">
              <span class="p-k">广告回本</span><span class="p-v">约 {{ msg.data.profit.break_even_units }} 件</span>
            </div>
          </div>
          <div class="profit-note">{{ msg.data.profit.note }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.row-user {
  flex-direction: row-reverse;
}

.avatar {
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
}

.avatar-ai {
  background: var(--brand-grad);
  color: #fff;
  box-shadow: 0 2px 8px rgba(46, 92, 255, 0.25);
}

.avatar-user {
  background: var(--bg-card-hover);
  color: var(--text-dim);
  border: 1px solid var(--border);
}

.bubble-wrap {
  max-width: 78%;
  min-width: 0;
}

.bubble {
  padding: 13px 17px;
  border-radius: 16px;
  font-size: 14px;
  line-height: 1.7;
  box-shadow: var(--shadow-sm);
}

.bubble-user {
  background: var(--brand-grad);
  color: #fff;
  border-top-right-radius: 5px;
}

.bubble-ai {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-top-left-radius: 5px;
}

.text {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-family: inherit;
}

.text-error {
  color: var(--danger);
}

.typing-line {
  min-height: 20px;
  display: flex;
  align-items: center;
}

.intent-tag {
  display: inline-block;
  font-size: 11px;
  color: var(--primary);
  background: var(--primary-bg);
  border-radius: 6px;
  padding: 2px 8px;
  margin-bottom: 6px;
  font-weight: 600;
}

/* ---- 深度思考过程面板 ---- */
.think-box {
  margin-bottom: 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.think-header {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  color: var(--text-dim);
}

.think-title {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
}

.think-chevron {
  font-size: 12px;
  color: var(--text-dim);
}

.spinner {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--primary-bg);
  border-top-color: var(--primary);
  animation: spin 0.8s linear infinite;
  flex: 0 0 auto;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.think-steps {
  padding: 2px 0 8px;
}

.think-step {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 4px 12px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-dim);
}

.step-tag {
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-bg);
  border-radius: 6px;
  padding: 1px 8px;
  margin-top: 1px;
}

.step-text {
  word-break: break-word;
}

/* ---- 结果卡片 ---- */
.cards {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 8px;
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 13px 15px;
  box-shadow: var(--shadow-sm);
}

.card-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-dim);
  margin-bottom: 8px;
}

/* 图片占位（加载失败不破版） */
.img-holder {
  flex: 0 0 auto;
  border-radius: var(--radius-sm);
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--bg-soft);
  position: relative;
}

.img-holder:empty {
  width: 56px;
  height: 56px;
  background:
    linear-gradient(var(--bg-soft), var(--bg-soft)),
    repeating-linear-gradient(45deg, #e3e8f2 0 8px, transparent 8px 16px);
}

.img-holder.img-fallback {
  background: var(--bg-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: var(--text-faint);
}

.img-holder.img-fallback::after {
  content: '🖼';
}

.prod-item {
  display: flex;
  gap: 11px;
  padding: 9px 0;
  border-bottom: 1px dashed var(--border);
  align-items: flex-start;
}

.prod-item:last-child { border-bottom: none; }

.prod-img {
  width: 64px;
  height: 64px;
  object-fit: cover;
  display: block;
}

.prod-main {
  min-width: 0;
  flex: 1;
}

.prod-title {
  font-size: 13px;
  line-height: 1.5;
}

.prod-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  margin-top: 3px;
  flex-wrap: wrap;
}

.price-tag {
  color: var(--primary);
  font-weight: 700;
  font-size: 13px;
}

.sales-tag {
  background: var(--bg-soft);
  color: var(--text-dim);
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 11px;
}

.dim-tag { color: var(--text-faint); }

/* 生命周期阶段徽章（与工作台 ProductsPanel 同款浅色） */
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

.prod-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
}

.prod-link {
  display: inline-block;
  font-size: 11px;
  color: var(--primary);
  text-decoration: none;
  font-weight: 600;
}

.prod-link:hover {
  text-decoration: underline;
}

/* 收藏按钮 */
.fav-btn {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-dim);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}

.fav-btn:hover {
  border-color: var(--warn);
  color: var(--warn);
}

.fav-btn.on {
  border-color: var(--warn);
  background: var(--warn-bg);
  color: var(--warn);
}

.mini-btn {
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-dim);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}

.mini-btn:hover {
  color: var(--primary);
  border-color: var(--primary);
}

.mini-btn.on {
  color: var(--warn);
  border-color: var(--warn);
}

/* 失败重试 */
.retry-btn {
  margin-top: 10px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-dim);
  border-radius: var(--radius-sm);
  padding: 6px 16px;
  font-size: 12px;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}

.retry-btn:hover {
  color: var(--primary);
  border-color: var(--primary);
}

/* 评论证据展开 */
.sent-topic-btn {
  flex: 0 0 92px;
  display: flex;
  align-items: center;
  gap: 2px;
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
  font-family: inherit;
  text-align: left;
}

.ev-chevron {
  font-size: 10px;
  color: var(--text-faint);
}

.evidence-panel {
  margin-top: 8px;
  border-top: 1px dashed var(--border);
  padding-top: 8px;
}

.evidence-block {
  margin-bottom: 8px;
}

.ev-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-dim);
  margin-bottom: 4px;
}

.ev-line {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text);
  background: var(--bg);
  border-left: 3px solid var(--primary);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  padding: 6px 10px;
  margin-bottom: 4px;
}

/* 定价助手 */
.price-guide {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  background: var(--success-bg);
  border: 1px solid var(--success);
  border-radius: var(--radius-sm);
  padding: 7px 12px;
  font-size: 12px;
  margin-bottom: 8px;
}

.pg-label {
  font-weight: 700;
  color: var(--success);
}

.pg-range {
  font-weight: 700;
  color: var(--text);
}

.pg-mid {
  color: var(--text-dim);
}

.pg-suggest {
  margin-left: auto;
  color: var(--success);
  font-weight: 600;
}

.copy-group {
  display: flex;
  gap: 4px;
}

.report-line {
  font-size: 13px;
  line-height: 1.6;
  margin-bottom: 4px;
}

.suggestion {
  color: var(--primary);
}

/* 评论情感占比条 */
.sentiment-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
}

.sentiment-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.sent-topic {
  flex: 0 0 92px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-dim);
}

.sent-track {
  flex: 1;
  height: 6px;
  background: var(--bg-soft);
  border-radius: 999px;
  overflow: hidden;
}

.sent-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  transition: width 0.5s var(--ease);
}

.fill-pos { background: var(--success); }
.fill-neg { background: var(--danger); }

.sent-count {
  flex: 0 0 auto;
  font-weight: 600;
}

.pos { color: var(--success); }
.neg { color: var(--danger); }

.offer-table {
  display: flex;
  flex-direction: column;
}

.offer-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--border);
  align-items: center;
}

.offer-row:last-child { border-bottom: none; }

.offer-img {
  width: 52px;
  height: 52px;
  object-fit: cover;
  display: block;
}

.offer-left {
  flex: 1;
  min-width: 0;
}

.offer-title { font-size: 13px; line-height: 1.5; }

.offer-title-link {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text);
  text-decoration: none;
  word-break: break-word;
}

.offer-title-link:hover {
  color: var(--primary);
  text-decoration: underline;
}

.offer-supplier { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
.offer-visual { font-size: 11px; margin-top: 4px; }
.vis-hit { color: var(--success); }
.vis-sim { color: var(--warn); }
.vis-far { color: var(--text-dim); }

/* 匹配度进度条 */
.match-track {
  display: inline-block;
  width: 46px;
  height: 5px;
  background: var(--bg-soft);
  border-radius: 999px;
  overflow: hidden;
  vertical-align: middle;
  margin: 0 3px;
}

.match-fill {
  display: block;
  height: 100%;
  background: currentColor;
  border-radius: 999px;
}

.offer-right {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.offer-price {
  font-weight: 700;
  color: var(--success);
  font-size: 14px;
}

.offer-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.offer-go {
  font-size: 11px;
  color: var(--primary);
  text-decoration: none;
  font-weight: 600;
}

.offer-go:hover {
  text-decoration: underline;
}

.listing-title { font-size: 14px; font-weight: 700; margin-bottom: 8px; }
.listing-kws { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.listing-path { font-size: 11px; color: var(--text-dim); margin-top: 8px; word-break: break-all; }

/* ---- 推荐评分卡 ---- */
.score-card {
  border-left: 4px solid var(--primary);
}

.score-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 10px;
}

.score-total {
  flex: 0 0 58px;
  width: 58px;
  height: 58px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 800;
  color: #fff;
}

.score-total.lv-strong { background: linear-gradient(135deg, #1f9d64, #2ec27b); }
.score-total.lv-good { background: linear-gradient(135deg, #2e5cff, #4a7dff); }
.score-total.lv-mid { background: linear-gradient(135deg, #e8a23a, #f0b95c); }
.score-total.lv-low { background: linear-gradient(135deg, #d9534f, #ef6b66); }

.score-main { min-width: 0; }

.score-level {
  font-size: 15px;
  font-weight: 800;
  color: var(--text);
}

.score-verdict {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.5;
}

.score-dims {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
}

.score-dim {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.timing-dim {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--border);
}
.dim-note {
  font-size: 11px;
  color: var(--text-dim);
}
.dim-max {
  font-size: 11px;
  color: var(--text-dim);
}

.dim-top {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
}

.dim-label { color: var(--text-dim); font-weight: 600; }
.dim-val { color: var(--text); font-weight: 700; }

.dim-track {
  height: 6px;
  background: var(--bg-soft);
  border-radius: 999px;
  overflow: hidden;
}

.dim-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--brand-grad);
  transition: width 0.5s var(--ease);
}

.score-reasons {
  border-top: 1px dashed var(--border);
  padding-top: 6px;
}

.score-reason {
  font-size: 11px;
  color: var(--text-dim);
  line-height: 1.6;
}

/* ---- 市场价位分布 ---- */
.band-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.band-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.band-label {
  flex: 0 0 120px;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.band-track {
  flex: 1;
  height: 8px;
  background: var(--bg-soft);
  border-radius: 999px;
  overflow: hidden;
}

.band-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #2e5cff, #7aa2ff);
}

.band-count {
  flex: 0 0 20px;
  text-align: right;
  font-weight: 700;
  color: var(--text);
}

.market-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-dim);
  flex-wrap: wrap;
}

/* ---- 关键词建议 ---- */
.kw-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.kw-note {
  font-size: 11px;
  color: var(--text-faint);
  margin-top: 6px;
}

.chip {
  display: inline-block;
  font-size: 11px;
  border-radius: 999px;
  padding: 2px 10px;
  font-weight: 600;
}

.chip-pos {
  background: var(--primary-bg);
  color: var(--primary);
}

/* ---- 利润测算卡 ---- */
.profit-card {
  border-left: 4px solid var(--success);
}

.profit-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 8px;
}

.p-cell {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 7px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.p-full { grid-column: 1 / -1; }

.p-k {
  font-size: 11px;
  color: var(--text-dim);
}

.p-v {
  font-size: 14px;
  font-weight: 800;
  color: var(--text);
}

.p-net .p-v { font-size: 16px; }
.p-pos .p-v { color: var(--success); }
.p-neg .p-v { color: var(--danger); }

.p-v small { font-size: 11px; font-weight: 600; }

.profit-note {
  font-size: 11px;
  color: var(--text-faint);
  line-height: 1.6;
}

@media (max-width: 720px) {
  .bubble-wrap { max-width: 88%; }
  .profit-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
