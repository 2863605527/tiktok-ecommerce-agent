<script setup lang="ts">
import { computed, ref } from 'vue'
import { useSelectionStore } from '@/stores/selection'
import { selectionApi } from '@/api/selection'
import { useToastStore } from '@/stores/toast'
import type { ListingPreview } from '@/api/types'

const store = useSelectionStore()
const toast = useToastStore()
const listing = computed(() => store.result?.listing)
const zipping = ref(false)
const csvBusy = ref(false)

// ---- 导出前预览（人工批准门控：对标 Anthropic merchant 写操作确认）----
const preview = ref<ListingPreview | null>(null)
const previewMode = ref<'zip' | 'csv'>('zip')
const previewBusy = ref(false)

/** 点下载 → 先拉预览 → 弹确认 → 用户确认才真正下载 */
async function askPreview(mode: 'zip' | 'csv') {
  const lp = store.result?.listing_path
  if (!lp) {
    toast.error('还没有素材包文件，请先运行「上架素材」阶段')
    return
  }
  previewMode.value = mode
  previewBusy.value = true
  try {
    preview.value = await selectionApi.previewListing(lp)
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '预览加载失败')
  } finally {
    previewBusy.value = false
  }
}

function cancelPreview() {
  preview.value = null
}

async function confirmDownload() {
  const mode = previewMode.value
  preview.value = null
  if (mode === 'zip') await downloadZip()
  else await downloadCsv()
}

/** 下载上架素材包 ZIP（listing.json + 商品图） */
async function downloadZip() {
  const lp = store.result?.listing_path
  if (!lp) {
    toast.error('还没有素材包文件，请先运行「上架素材」阶段')
    return
  }
  zipping.value = true
  try {
    const blob = await selectionApi.packageListing({
      listing_path: lp,
      image_urls: listing.value?.images ?? [],
    })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    const folder = lp.split('/').pop()?.replace(/\.json$/, '') || 'listing'
    a.download = `${folder}_素材包.zip`
    a.click()
    URL.revokeObjectURL(a.href)
    toast.success('素材包已下载（ZIP）')
  } catch (e) {
    toast.error(e instanceof Error ? e.message : '素材包打包失败')
  } finally {
    zipping.value = false
  }
}

/** 导出 TikTok 批量上架 CSV（卖家中心可导入模板） */
async function downloadCsv() {
  const lp = store.result?.listing_path
  if (!lp) {
    toast.error('还没有素材包文件，请先运行「上架素材」阶段')
    return
  }
  csvBusy.value = true
  try {
    const blob = await selectionApi.downloadListingCsv({
      listing_path: lp,
      image_urls: listing.value?.images ?? [],
    })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    const folder = lp.split('/').pop()?.replace(/\.json$/, '') || 'listing'
    a.download = `${folder}_tiktok上架.csv`
    a.click()
    URL.revokeObjectURL(a.href)
    toast.success('批量上架 CSV 已导出（Excel 可直接打开）')
  } catch (e) {
    toast.error(e instanceof Error ? e.message : 'CSV 导出失败')
  } finally {
    csvBusy.value = false
  }
}
</script>

<template>
  <section v-if="listing" class="panel">
    <h3 class="panel-title">
      ④ 上架素材包
      <span v-if="store.result?.listing_path" class="badge">已导出: {{ store.result.listing_path }}</span>
      <span class="dl-group">
        <button v-if="store.result?.listing_path" class="zip-btn" :disabled="csvBusy || previewBusy"
          @click="askPreview('csv')">
          {{ csvBusy ? '导出中…' : '⇩ 上架 CSV' }}
        </button>
        <button v-if="store.result?.listing_path" class="zip-btn primary" :disabled="zipping || previewBusy"
          @click="askPreview('zip')">
          {{ zipping ? '打包中…' : '⇩ 下载 ZIP 素材包' }}
        </button>
      </span>
    </h3>

    <div class="listing-body">
      <div class="field">
        <label>上架标题（{{ store.language === 'ja' ? '日本語' : store.language }}）</label>
        <div class="value-title">{{ listing.translated_title || listing.title }}</div>
      </div>

      <div class="field">
        <label>商品描述</label>
        <div class="value">{{ listing.description }}</div>
      </div>

      <div class="field">
        <label>关键词</label>
        <div class="chips">
          <span v-for="k in listing.keywords" :key="k" class="chip">{{ k }}</span>
        </div>
      </div>

      <div class="field">
        <label>标签</label>
        <div class="chips">
          <span v-for="h in listing.hashtags" :key="h" class="chip tag">{{ h }}</span>
        </div>
      </div>

      <div v-if="Object.keys(listing.specs_translated ?? {}).length" class="field">
        <label>规格翻译</label>
        <table class="specs">
          <tbody>
            <tr v-for="(v, k) in listing.specs_translated" :key="k">
              <td>{{ k }}</td>
              <td>{{ v }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="listing.images.length" class="field">
        <label>图片</label>
        <div class="imgs">
          <img v-for="(img, i) in listing.images" :key="i" :src="img" alt="商品图" class="img" />
        </div>
      </div>
    </div>

    <!-- 导出前预览确认（人工批准门控） -->
    <div v-if="preview" class="pv-mask" @click.self="cancelPreview">
      <div class="pv-dialog">
        <div class="pv-head">
          <h4>{{ previewMode === 'zip' ? '下载 ZIP 素材包' : '导出 TikTok 上架 CSV' }} — 确认内容</h4>
          <button class="pv-close" @click="cancelPreview" aria-label="关闭">✕</button>
        </div>
        <div class="pv-body">
          <div class="pv-field">
            <label>上架标题</label>
            <div class="pv-title">{{ preview.translated_title || preview.title || '（空）' }}</div>
          </div>
          <div class="pv-field">
            <label>关键词</label>
            <div class="chips">
              <span v-for="k in preview.keywords" :key="k" class="chip">{{ k }}</span>
            </div>
          </div>
          <div class="pv-field">
            <label>标签</label>
            <div class="chips">
              <span v-for="h in preview.hashtags" :key="h" class="chip tag">{{ h }}</span>
            </div>
          </div>
          <div v-if="preview.specs_translated && Object.keys(preview.specs_translated).length" class="pv-field">
            <label>规格翻译</label>
            <table class="specs">
              <tbody>
                <tr v-for="(v, k) in preview.specs_translated" :key="k">
                  <td>{{ k }}</td>
                  <td>{{ v }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="preview.description" class="pv-field">
            <label>描述摘要</label>
            <div class="value">{{ preview.description }}</div>
          </div>
          <div class="pv-note">下载内容与上面预览一致；导出的 CSV/ZIP 将包含该素材与商品图。</div>
        </div>
        <div class="pv-foot">
          <button class="pv-btn ghost" @click="cancelPreview">取消</button>
          <button class="pv-btn primary" :disabled="zipping || csvBusy" @click="confirmDownload">
            {{ zipping || csvBusy ? '处理中…' : '确认并下载' }}
          </button>
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
  display: flex;
  align-items: center;
  gap: 10px;
}

.zip-btn {
  border: 1px solid var(--primary);
  background: var(--primary-bg);
  color: var(--primary);
  border-radius: var(--radius-sm);
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}

.zip-btn.primary {
  background: var(--primary);
  color: #fff;
}

.dl-group {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.zip-btn:hover:not(:disabled) {
  background: var(--primary);
  color: #fff;
}

.zip-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}

.badge {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-dim);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 2px 8px;
}

.listing-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.field label {
  display: block;
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 6px;
}

.value-title {
  font-size: 15px;
  font-weight: 700;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
}

.value {
  font-size: 13px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.chip {
  background: var(--primary-bg);
  color: var(--primary);
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
}

.chip.tag {
  background: var(--warn-bg);
  color: var(--warn);
}

.specs {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.specs td {
  padding: 6px 10px;
  border: 1px solid var(--border);
}

.specs td:first-child {
  color: var(--text-dim);
  width: 30%;
}

.imgs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.img {
  width: 90px;
  height: 90px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid var(--border);
}

/* ---- 导出前预览弹窗（人工批准门控） ---- */
.pv-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.pv-dialog {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px;
  width: min(560px, 92vw);
  max-height: 82vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.25);
}

.pv-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}

.pv-head h4 {
  font-size: 14px;
  margin: 0;
}

.pv-close {
  border: none;
  background: none;
  font-size: 15px;
  color: var(--text-dim);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
}

.pv-close:hover {
  background: var(--bg-soft);
}

.pv-body {
  padding: 16px 18px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pv-field label {
  display: block;
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 5px;
}

.pv-title {
  font-size: 14px;
  font-weight: 600;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
}

.pv-note {
  font-size: 11px;
  color: var(--text-dim);
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}

.pv-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 18px;
  border-top: 1px solid var(--border);
}

.pv-btn {
  border-radius: 8px;
  padding: 8px 18px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text);
}

.pv-btn.primary {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}

.pv-btn.ghost:hover {
  background: var(--bg-soft);
}

.pv-btn:disabled {
  opacity: 0.6;
  cursor: wait;
}
</style>
