<script setup lang="ts">
// 图片优化工作台：商品图规格化（白底/比例/压缩）+ 图上文字识别 + 日文翻译
// 单图 + 批量双通道；白底支持 AI 智能抠图（rembg，本地离线）与快速去底
// （KeepAlive name=images：切走再回来处理结果不丢）
import { ref } from 'vue'
import { processImage, processImageBatch } from '@/api/images'
import type { BgMode } from '@/api/images'
import type { ImageProcessBatchResult, ImageProcessResult } from '@/api/types'

defineOptions({ name: 'images' })

const imageUrl = ref('')
const ratio = ref('1:1')
const whiteBg = ref(true)
const bgMode = ref<BgMode>('ai')
const loading = ref(false)
const error = ref('')
const result = ref<ImageProcessResult | null>(null)
// 翻译复制反馈
const copiedJa = ref('')

// 批量
const batchUrls = ref('')
const batchLoading = ref(false)
const batchError = ref('')
const batchResult = ref<ImageProcessBatchResult | null>(null)

const ratioOptions = [
  { value: '1:1', label: '1:1 主图' },
  { value: '3:4', label: '3:4 竖版' },
  { value: '4:3', label: '4:3 横版' },
  { value: '9:16', label: '9:16 短视频封面' },
  { value: '16:9', label: '16:9 详情长图' },
]

const bgModeOptions = [
  { value: 'ai', label: 'AI 智能抠图（推荐，阴影/渐变/灰底都能去）' },
  { value: 'heuristic', label: '快速去底（像素阈值，适合干净浅色底）' },
]

const examples = [
  'https://imgniu.zhaojiafang.com/store/goods/11848/11848_PQN172e7da8a56f2d93f76b1ea14ecce394.jpg',
  'https://imgniu.zhaojiafang.com/store/goods/11848/11848_PQNf5780ff954f7a7e72e912822d60543f0.jpg',
]

function processedUrl(p: string) {
  // 后端静态挂载：output/images/** → /static/images/**
  const idx = p.indexOf('\\images\\')
  if (idx >= 0) return '/static/images/' + p.slice(idx + 8).replace(/\\/g, '/')
  const i2 = p.indexOf('/images/')
  if (i2 >= 0) return '/static/images/' + p.slice(i2 + 8)
  return p
}

function bgUsedLabel(m: string) {
  if (m === 'ai') return 'AI 抠图'
  if (m === 'heuristic') return '快速去底'
  return '未去底'
}

/** 图片加载失败 → 占位（不破版） */
function onImgError(e: Event) {
  const el = e.target as HTMLImageElement
  el.style.visibility = 'hidden'
  const holder = el.closest('.img-card, .batch-thumb') as HTMLElement | null
  if (holder) holder.classList.add('img-fallback')
}

/** 下载单张处理后图 */
function downloadOne(p: string) {
  const a = document.createElement('a')
  a.href = processedUrl(p)
  a.download = p.split(/[\\/]/).pop() || 'processed.jpg'
  a.target = '_blank'
  a.click()
}

/** 批量下载全部成功项（依次触发，浏览器逐个下载） */
function downloadAll() {
  if (!batchResult.value) return
  const urls = batchResult.value.items.filter((i) => !i.error).map((i) => processedUrl(i.processed_path))
  urls.forEach((u, i) => {
    setTimeout(() => {
      const a = document.createElement('a')
      a.href = u
      a.download = `batch_${i + 1}_${u.split('/').pop() || 'img.jpg'}`
      a.target = '_blank'
      a.click()
    }, i * 600)
  })
}

/** 复制翻译结果（单图/批量）：拼接全部日文翻译，一键粘贴到素材/客服话术 */
function copyTranslations(items: Array<{ zh: string; ja?: string } | { translations: Array<{ zh: string; ja?: string }> }>) {
  const pairs: Array<{ zh: string; ja?: string }> = []
  for (const it of items) {
    if ('translations' in it && Array.isArray((it as { translations: unknown[] }).translations)) {
      pairs.push(...(it as { translations: Array<{ zh: string; ja?: string }> }).translations)
    } else {
      pairs.push(it as { zh: string; ja?: string })
    }
  }
  const text = pairs
    .filter((p) => p.ja)
    .map((p) => `${p.zh}：${p.ja}`)
    .join('\n')
  if (!text) return
  navigator.clipboard.writeText(text).then(
    () => {
      copiedJa.value = 'ok'
      setTimeout(() => (copiedJa.value = ''), 1600)
    },
    () => {
      /* 剪贴板不可用时提示手动复制 */
    },
  )
}

async function run() {
  if (!imageUrl.value.trim()) {
    error.value = '请粘贴商品图链接'
    return
  }
  loading.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await processImage(imageUrl.value.trim(), ratio.value, whiteBg.value, bgMode.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function useExample(u: string) {
  imageUrl.value = u
  run()
}

function batchUrlList(): string[] {
  return batchUrls.value
    .split('\n')
    .map((s) => s.trim())
    .filter((s) => s.length >= 8)
}

async function runBatch() {
  const urls = batchUrlList()
  if (!urls.length) {
    batchError.value = '请粘贴至少一个商品图链接（每行一个）'
    return
  }
  batchLoading.value = true
  batchError.value = ''
  batchResult.value = null
  try {
    batchResult.value = await processImageBatch(urls, ratio.value, whiteBg.value, bgMode.value)
  } catch (e) {
    batchError.value = e instanceof Error ? e.message : String(e)
  } finally {
    batchLoading.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h1>商品图片优化</h1>
      <p class="sub">上架最头疼的商品图：白底/比例规格化 + 图上中文文字识别 → 日文翻译 → 上架建议</p>
    </div>

    <div class="panel">
      <div class="form-row">
        <input
          v-model="imageUrl"
          class="url-input"
          placeholder="粘贴商品图链接（TikTok 竞品图 / 找家纺货源图）"
          @keyup.enter="run"
        >
        <select v-model="ratio" class="ratio-select">
          <option v-for="r in ratioOptions" :key="r.value" :value="r.value">{{ r.label }}</option>
        </select>
        <label class="checkbox">
          <input v-model="whiteBg" type="checkbox"> 白底化
        </label>
        <select v-model="bgMode" class="ratio-select" :disabled="!whiteBg">
          <option v-for="m in bgModeOptions" :key="m.value" :value="m.value">{{ m.label }}</option>
        </select>
        <button class="primary" :disabled="loading" @click="run">
          {{ loading ? '处理中…' : '开始处理' }}
        </button>
      </div>

      <div v-if="error" class="error">{{ error }}</div>

      <div class="examples">
        <span class="hint">试试真实货源图：</span>
        <button v-for="(u, i) in examples" :key="i" class="ex" @click="useExample(u)">
          例图 {{ i + 1 }}
        </button>
        <span v-if="whiteBg && bgMode === 'ai'" class="hint">AI 抠图本地运行（u2netp 已内置，离线免费；放置 u2net.onnx 可提精度）</span>
      </div>
    </div>

    <div v-if="loading" class="loading-box">正在下载图片 → 规格化处理 → AI 抠图/去底 → 文字识别 → 日文翻译…</div>

    <div v-if="result" class="result">
      <div class="grid">
        <div class="img-card">
          <div class="card-title">原图</div>
          <img :src="result.original_url" alt="原图" loading="lazy" @error="onImgError">
        </div>
        <div class="img-card">
          <div class="card-title">
            处理后（{{ result.ratio }}{{ result.white_bg ? ' · 白底(' + bgUsedLabel(result.bg_used) + ')' : '' }}）
          </div>
          <img :src="processedUrl(result.processed_path)" alt="处理后" loading="lazy" @error="onImgError">
          <div class="img-actions">
            <button class="mini-btn" @click="downloadOne(result.processed_path)">⬇ 下载处理后图</button>
          </div>
        </div>
      </div>

      <div class="advice-box" :class="result.has_text ? 'warn' : 'ok'">
        <strong>{{ result.has_text ? '⚠ 图上识别到文字' : '✅ 图上无文字' }}</strong>
        <p>{{ result.advice }}</p>
        <span class="meta">
          白底: {{ bgUsedLabel(result.bg_used) }} · OCR: {{ ['rapidocr', 'paddle'].includes(result.ocr_backend)
            ? '本地 OCR（RapidOCR/ONNX，离线免费）' : '不可用（仅规格化处理）' }}
        </span>
      </div>

      <div v-if="result.translations.length" class="text-table">
        <div class="table-head">
          <h3>图上文字 → 日文翻译（可直接作配图文案）</h3>
          <button class="mini-btn" @click="copyTranslations(result.translations)">
            {{ copiedJa ? '✓ 已复制' : '⇩ 复制全部日文' }}
          </button>
        </div>
        <table>
          <thead>
            <tr><th>#</th><th>图上中文</th><th>日文翻译</th></tr>
          </thead>
          <tbody>
            <tr v-for="(t, i) in result.translations" :key="i">
              <td>{{ i + 1 }}</td>
              <td>{{ t.zh }}</td>
              <td class="ja">{{ t.ja || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else-if="result.has_text" class="text-table">
        <h3>图上识别到 {{ result.texts.length }} 条文字（翻译暂不可用，请人工核对）</h3>
        <div v-for="(t, i) in result.texts" :key="i" class="text-line">{{ i + 1 }}. {{ t }}</div>
      </div>
    </div>

    <!-- 批量处理 -->
    <div class="panel batch-panel">
      <h2>批量处理</h2>
      <p class="sub">一次处理 1~20 张：每行一个图片链接，按同一比例/白底设置批量生成（并发 4，单张失败不影响其余）</p>
      <textarea
        v-model="batchUrls"
        class="batch-input"
        rows="4"
        placeholder="https://imgniu.zhaojiafang.com/...\nhttps://imgniu.zhaojiafang.com/..."
      />
      <div class="form-row">
        <button class="primary" :disabled="batchLoading" @click="runBatch">
          {{ batchLoading ? '批量处理中…' : '开始批量处理' }}
        </button>
        <button v-if="batchResult && batchResult.ok" class="btn-ghost" @click="downloadAll">
          ⬇ 下载全部成功项（{{ batchResult.ok }} 张）
        </button>
        <span v-if="batchResult" class="hint">
          成功 {{ batchResult.ok }} / 失败 {{ batchResult.failed }}
        </span>
      </div>
      <div v-if="batchError" class="error">{{ batchError }}</div>

      <div v-if="batchResult" class="batch-grid">
        <div v-if="batchResult.ok && batchResult.items.some((i) => i.translations?.length)" class="batch-copy-all">
          <button class="mini-btn" @click="copyTranslations(batchResult.items)">
            ⇩ 复制全部日文翻译（{{ batchResult.items.reduce((n, i) => n + (i.translations?.length ?? 0), 0) }} 条）
          </button>
        </div>
        <div v-for="(item, i) in batchResult.items" :key="i" class="batch-card" :class="{ failed: item.error }">
          <div class="batch-thumb">
            <img v-if="!item.error" :src="processedUrl(item.processed_path)" alt="处理后" loading="lazy" @error="onImgError">
            <span v-else class="fail-text">失败</span>
          </div>
          <div class="batch-info">
            <div class="batch-status">
              {{ item.error ? item.error : bgUsedLabel(item.bg_used) + ' · ' + (item.has_text ? '图上有字' : '无字') }}
            </div>
            <div class="batch-tr" :title="item.original_url">{{ item.original_url.slice(0, 60) }}…</div>
            <div v-if="item.translations.length" class="batch-tr ja">
              例: {{ item.translations[0].ja }}
            </div>
            <button v-if="!item.error" class="mini-btn" @click="downloadOne(item.processed_path)">
              ⬇ 下载
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  max-width: 960px;
  margin: 0 auto;
}

.page-head h1 {
  font-size: 22px;
  margin: 0 0 6px;
}

.sub {
  color: var(--text-dim);
  font-size: 14px;
  margin: 0 0 20px;
}

.panel {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px;
}

.form-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}

.url-input {
  flex: 1;
  min-width: 280px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 14px;
}

.ratio-select {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  font-size: 14px;
}

.checkbox {
  font-size: 14px;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 4px;
}

.primary {
  background: var(--primary);
  color: #fff;
  border: none;
  border-radius: var(--radius-sm);
  padding: 10px 22px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
  box-shadow: 0 1px 2px rgba(46, 92, 255, 0.3);
}

.primary:hover:not(:disabled) {
  background: var(--primary-hover);
  box-shadow: 0 4px 12px rgba(46, 92, 255, 0.25);
}

.primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error {
  margin-top: 12px;
  color: var(--danger);
  font-size: 13px;
}

.examples {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.hint {
  font-size: 12px;
  color: var(--text-dim);
}

.ex {
  border: 1px dashed var(--border);
  background: transparent;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--primary);
  cursor: pointer;
}

.loading-box {
  margin: 18px 0;
  padding: 16px;
  border-radius: 10px;
  background: var(--primary-bg);
  color: var(--primary);
  font-size: 14px;
  text-align: center;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 18px;
}

.img-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  background: #fff;
}

.card-title {
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}

.img-card img {
  width: 100%;
  display: block;
  aspect-ratio: 1 / 1;
  object-fit: contain;
  background: #fff;
}

.advice-box {
  margin-top: 16px;
  border-radius: 10px;
  padding: 14px 16px;
  border: 1px solid;
  font-size: 14px;
  line-height: 1.6;
}

.advice-box p {
  margin: 6px 0 0;
}

.advice-box.warn {
  border-color: var(--warn);
  background: #fff8e6;
}

.advice-box.ok {
  border-color: var(--success);
  background: #f0fdf4;
}

.meta {
  display: block;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-dim);
}

.text-table {
  margin-top: 20px;
}

.text-table h3 {
  font-size: 15px;
  margin-bottom: 10px;
}

.text-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.text-table th,
.text-table td {
  border: 1px solid var(--border);
  padding: 8px 12px;
  text-align: left;
}

.text-table th {
  background: var(--bg-card);
  font-size: 13px;
}

.ja {
  color: var(--primary);
  font-weight: 500;
}

.text-line {
  padding: 6px 0;
  border-bottom: 1px dashed var(--border);
  font-size: 14px;
}

.batch-panel {
  margin-top: 24px;
}

.batch-panel h2 {
  font-size: 17px;
  margin: 0 0 4px;
}

.batch-input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 13px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  resize: vertical;
  box-sizing: border-box;
  margin: 10px 0;
}

.batch-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.batch-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  background: #fff;
}

.batch-card.failed {
  border-color: var(--danger);
  background: #fff5f5;
}

.batch-thumb {
  aspect-ratio: 1 / 1;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid var(--border);
}

.batch-thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.fail-text {
  color: var(--danger);
  font-size: 13px;
  padding: 12px;
}

.batch-info {
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.5;
}

.batch-status {
  font-weight: 600;
  font-size: 12px;
}

.batch-tr {
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.batch-tr.ja {
  color: var(--primary);
}

.mini-btn {
  margin-top: 6px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-dim);
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 11px;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}

.mini-btn:hover {
  color: var(--primary);
  border-color: var(--primary);
}

.table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.table-head h3 {
  margin: 0;
}

.table-head .mini-btn {
  margin-top: 0;
}

.batch-copy-all {
  margin-bottom: 10px;
  text-align: right;
}

.batch-copy-all .mini-btn {
  margin-top: 0;
}

.img-actions {
  padding: 8px 12px;
  border-top: 1px solid var(--border);
}

.img-card.img-fallback::after,
.batch-thumb.img-fallback::after {
  content: '🖼';
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-faint);
  font-size: 28px;
}
</style>
