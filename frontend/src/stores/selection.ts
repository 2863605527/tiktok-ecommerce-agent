// Pinia store：选品工作台全局状态（输入项 / 运行状态 / 结果 / 运行配置）
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { selectionApi } from '@/api/selection'
import { ApiError } from '@/api/client'
import type {
  Category,
  RuntimeConfig,
  SelectionResponse,
  StageKey,
} from '@/api/types'

const ALL_STAGES: StageKey[] = ['crawler', 'analyzer', 'sourcing', 'listing']

// 阶段 → 步骤文案（工作台进度展示）
const STAGE_LABEL: Record<StageKey, string> = {
  crawler: '采集竞品',
  analyzer: '商品分析',
  sourcing: '货源匹配',
  listing: '上架素材',
}

export const useSelectionStore = defineStore('selection', () => {
  // ---- 输入项 ----
  const product = ref('純棉 ボックスシーツ 1.8m')
  const region = ref('JP')
  const language = ref('ja')
  const category = ref('bedding')
  const stages = ref<StageKey[]>(ALL_STAGES)

  // ---- 元数据 ----
  const categories = ref<Category[]>([])
  const config = ref<RuntimeConfig | null>(null)
  const categoriesLoaded = ref(false)
  const configLoaded = ref(false)

  // ---- 运行状态 ----
  const running = ref(false)
  const result = ref<SelectionResponse | null>(null)
  const error = ref('')
  // 流式进度：当前阶段 + 实时文案
  const stage = ref<StageKey | null>(null)
  const stageText = ref('')

  const hasResult = computed(() => result.value !== null)

  // ---- 动作 ----
  async function loadMeta() {
    if (categoriesLoaded.value) return
    try {
      const [cats, cfg] = await Promise.all([
        selectionApi.listCategories(),
        selectionApi.runtimeConfig(),
      ])
      categories.value = cats
      config.value = cfg
      categoriesLoaded.value = true
      configLoaded.value = true
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : '加载品类/配置失败'
    }
  }

  function toggleStage(key: StageKey) {
    stages.value = stages.value.includes(key)
      ? stages.value.filter((s) => s !== key)
      : [...stages.value, key]
  }

  async function run() {
    running.value = true
    error.value = ''
    result.value = null
    stage.value = null
    stageText.value = '准备启动流水线…'
    try {
      const events = selectionApi.runStream({
        product: product.value.trim(),
        region: region.value,
        category: category.value,
        language: language.value,
        stages: stages.value.length === ALL_STAGES.length ? undefined : stages.value,
      })
      for await (const ev of events) {
        if (ev.type === 'status') {
          stage.value = ev.stage as StageKey
          stageText.value = ev.text
        } else if (ev.type === 'done') {
          result.value = ev.result
          if (ev.result.error) error.value = ev.result.error
        } else if (ev.type === 'error') {
          error.value = ev.text
        }
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : '运行流水线失败'
    } finally {
      running.value = false
      stage.value = null
      stageText.value = ''
    }
  }

  /** 批量选品：逐个商品串行运行（互不干扰，任何失败即中止并保留错误） */
  async function runBatch(items: string[]) {
    const list = items.map((s) => s.trim()).filter((s) => s.length > 0)
    if (!list.length || running.value) return
    for (const item of list) {
      product.value = item
      await run()
      if (error.value) break
    }
  }

  /** 回放历史结果：把某条历史记录载入当前结果面板 */
  function replay(res: SelectionResponse | null, p?: string) {
    result.value = res
    error.value = res?.error ?? ''
    stage.value = null
    stageText.value = ''
    if (p) product.value = p
  }

  return {
    product, region, language, category, stages,
    categories, config, categoriesLoaded, configLoaded,
    running, result, error, hasResult, stage, stageText, STAGE_LABEL,
    loadMeta, toggleStage, run, runBatch, replay,
  }
})
