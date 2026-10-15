<script setup lang="ts">
import { computed } from 'vue'
import { useSelectionStore } from '@/stores/selection'
import { useToastStore } from '@/stores/toast'

const store = useSelectionStore()
const toast = useToastStore()
const report = computed(() => store.result?.report)

const scoreLevel = computed(() => {
  const total = store.result?.score?.total ?? 0
  if (total >= 80) return 'strong'
  if (total >= 65) return 'good'
  if (total >= 50) return 'mid'
  return 'low'
})
const scoreDims = computed(() => {
  const dims = store.result?.score?.dims
  if (!dims) return []
  return [dims.heat, dims.demand, dims.supply, dims.listing].filter(Boolean)
})

function fmtJpy(v: number | undefined | null): string {
  if (v == null || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat('ja-JP').format(Math.round(v)) + ' JPY'
}

async function copyKeywords() {
  const top = store.result?.keyword_insights?.top
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
  <section v-if="report" class="panel">
    <h3 class="panel-title">② 选品评估（评论 RAG 分析）</h3>

    <!-- 推荐评分卡（第三轮：量化决策） -->
    <div v-if="store.result?.score" class="score-card">
      <div class="score-head">
        <span class="score-total" :class="'lv-' + scoreLevel">{{ store.result.score.total }}</span>
        <div class="score-main">
          <div class="score-level">{{ store.result.score.level }}</div>
          <div class="score-verdict">{{ store.result.score.verdict }}</div>
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
      </div>
    </div>

    <!-- 市场价位分布（真实竞品价格聚合） -->
    <div v-if="store.result?.market_overview && store.result.market_overview.sample_count > 0" class="market-box">
      <h4>市场价位分布（{{ store.result.market_overview.sample_count }} 个竞品样本）</h4>
      <div class="band-list">
        <div v-for="b in store.result.market_overview.bands" :key="b.label" class="band-row">
          <span class="band-label">{{ b.label }}</span>
          <span class="band-track">
            <span class="band-fill" :style="{ width: Math.max(4, b.share * 100) + '%' }"></span>
          </span>
          <span class="band-count">{{ b.count }}</span>
        </div>
      </div>
      <div class="market-stats">
        <span>均价 {{ fmtJpy(store.result.market_overview.avg_price) }}</span>
        <span>中位价 {{ fmtJpy(store.result.market_overview.median_price) }}</span>
        <span v-if="store.result.market_overview.note" class="dim">{{ store.result.market_overview.note }}</span>
      </div>
    </div>

    <!-- 关键词建议（报告/评论/竞品标题聚合） -->
    <div v-if="store.result?.keyword_insights && store.result.keyword_insights.top.length" class="market-box">
      <h4>搜索关键词建议
        <button class="mini-btn" title="复制全部关键词" @click="copyKeywords">复制全部</button>
      </h4>
      <div class="keywords">
        <span v-for="k in store.result.keyword_insights.top.slice(0, 10)" :key="k.word" class="kw"
          :title="k.source">{{ k.word }}</span>
      </div>
      <p v-if="store.result.keyword_insights.note" class="dim">{{ store.result.keyword_insights.note }}</p>
    </div>

    <div class="summary">
      <span class="hot">热度 {{ report.market_hot }}</span>
      <span class="sugg">{{ report.suggestion }}</span>
    </div>

    <div class="grid">
      <div class="block">
        <h4>👍 优点</h4>
        <ul>
          <li v-for="(p, i) in report.pros" :key="i">{{ p }}</li>
        </ul>
      </div>
      <div class="block">
        <h4>⚠️ 缺点 / 风险</h4>
        <ul>
          <li v-for="(c, i) in report.cons" :key="i">{{ c }}</li>
          <li v-for="(r, i) in report.risks" :key="'r' + i" class="risk">{{ r }}</li>
        </ul>
      </div>
      <div class="block wide">
        <h4>🔑 核心关键词</h4>
        <div class="keywords">
          <span v-for="k in report.keywords" :key="k" class="kw">{{ k }}</span>
        </div>
        <p class="competition">{{ report.competition }}</p>
      </div>
    </div>

    <div v-if="report.insights.length" class="insights">
      <h4>评论洞察（聚类 + 证据引用）</h4>
      <!-- 正/负情感占比条：一眼看评论口碑 -->
      <div class="sentiment-bar">
        <div v-for="ins in report.insights.slice(0, 4)" :key="'s' + ins.topic" class="sentiment-row">
          <span class="sent-topic">{{ ins.topic }}</span>
          <span class="sent-track">
            <span class="sent-fill" :class="ins.sentiment === 'negative' ? 'fill-neg' : 'fill-pos'"
              :style="{ width: Math.min(100, Math.max(8, (ins.mentions / 10) * 100)) + '%' }"></span>
          </span>
          <span class="sent-count" :class="ins.sentiment === 'negative' ? 'neg' : 'pos'">
            {{ ins.mentions }} 条{{ ins.sentiment === 'negative' ? '·负面' : '·正面' }}
          </span>
        </div>
      </div>
      <div class="insight-list">
        <div v-for="ins in report.insights" :key="ins.topic" class="insight">
          <div class="ins-head">
            <span class="emoji">{{ ins.sentiment === 'positive' ? '👍' : '⚠️' }}</span>
            <span class="topic">{{ ins.topic }}</span>
            <span class="meta">提及 {{ ins.mentions }} 次 · 严重度 {{ ins.severity }}</span>
          </div>
          <div class="evidence">
            <div v-for="(ev, i) in ins.evidence.slice(0, 2)" :key="i" class="ev">
              “{{ ev }}”
            </div>
          </div>
        </div>
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
  margin-bottom: 12px;
}

/* ---- 推荐评分卡 ---- */
.score-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-left: 4px solid var(--primary);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
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
.score-level { font-size: 15px; font-weight: 800; color: var(--text); }
.score-verdict { font-size: 12px; color: var(--text-dim); line-height: 1.5; }

.score-dims {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.score-dim { display: flex; flex-direction: column; gap: 3px; }
.dim-top { display: flex; justify-content: space-between; font-size: 11px; }
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

/* ---- 市场价位分布 + 关键词 ---- */
.market-box {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 12px;
}

.market-box h4 {
  font-size: 13px;
  margin-bottom: 8px;
  color: var(--text-dim);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.mini-btn {
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-dim);
  border-radius: var(--radius-sm);
  padding: 2px 10px;
  font-size: 11px;
  cursor: pointer;
}

.mini-btn:hover {
  color: var(--primary);
  border-color: var(--primary);
}

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
  gap: 12px;
  margin-top: 8px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-dim);
  flex-wrap: wrap;
}

.market-stats .dim {
  font-weight: 400;
  color: var(--text-faint);
}

.summary {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.hot {
  color: var(--warn);
  font-size: 13px;
}

.sugg {
  color: var(--success);
  font-size: 13px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}

.block {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
}

.block h4 {
  font-size: 13px;
  margin-bottom: 8px;
  color: var(--text-dim);
}

.block ul {
  padding-left: 18px;
  font-size: 13px;
}

.block li {
  margin-bottom: 4px;
}

.risk {
  color: var(--danger);
}

.keywords {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.kw {
  background: var(--primary-bg);
  color: var(--primary);
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
}

.competition {
  font-size: 12px;
  color: var(--text-dim);
}

.insights {
  margin-top: 16px;
  border-top: 1px dashed var(--border);
  padding-top: 12px;
}

.insights h4 {
  font-size: 13px;
  margin-bottom: 10px;
}

.insight-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.insight {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
}

.ins-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.emoji {
  font-size: 16px;
}

.topic {
  font-weight: 700;
  font-size: 13px;
}

.meta {
  font-size: 11px;
  color: var(--text-dim);
}

.evidence {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ev {
  font-size: 12px;
  color: var(--text-dim);
  border-left: 2px solid var(--border);
  padding-left: 10px;
  line-height: 1.5;
}

/* 正/负情感占比条 */
.sentiment-bar {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-bottom: 14px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
}

.sentiment-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.sent-topic {
  flex: 0 0 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-dim);
}

.sent-track {
  flex: 1;
  height: 7px;
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
</style>
