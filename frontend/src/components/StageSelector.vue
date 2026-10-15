<script setup lang="ts">
import { computed } from 'vue'
import { useSelectionStore } from '@/stores/selection'
import type { StageKey } from '@/api/types'

const store = useSelectionStore()

const STAGE_LABELS: Record<StageKey, { label: string; hint: string }> = {
  crawler: { label: '采集竞品', hint: '搜索竞品并入库向量库' },
  analyzer: { label: '商品分析', hint: '评论 RAG 痛点聚类' },
  sourcing: { label: '货源匹配', hint: '找家纺网六维打分' },
  listing: { label: '上架素材', hint: '日语文案+CSV 导出' },
}

const allSelected = computed(() => store.stages.length === 4)
</script>

<template>
  <div class="stage-selector">
    <label v-for="(meta, key) in STAGE_LABELS" :key="key" class="stage">
      <input
        type="checkbox"
        :checked="store.stages.includes(key)"
        @change="store.toggleStage(key)"
      />
      <span class="box">
        <span class="label">{{ meta.label }}</span>
        <span class="hint">{{ meta.hint }}</span>
      </span>
    </label>
    <button
      v-if="!allSelected"
      type="button"
      class="reset"
      @click="store.stages = ['crawler', 'analyzer', 'sourcing', 'listing']"
    >
      恢复全部
    </button>
  </div>
</template>

<style scoped>
.stage-selector {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.stage {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 12px;
  cursor: pointer;
  transition: border-color 0.15s;
}

.stage:has(input:checked) {
  border-color: var(--primary);
  background: var(--primary-bg);
}

.stage input {
  width: 16px;
  height: 16px;
  accent-color: var(--primary);
}

.label {
  font-size: 13px;
  font-weight: 600;
}

.hint {
  display: block;
  font-size: 11px;
  color: var(--text-dim);
}

.reset {
  background: none;
  border: 1px dashed var(--border);
  color: var(--text-dim);
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
}

.reset:hover {
  color: var(--primary);
  border-color: var(--primary);
}
</style>
