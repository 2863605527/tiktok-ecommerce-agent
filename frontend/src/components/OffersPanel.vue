<script setup lang="ts">
import { computed } from 'vue'
import { useSelectionStore } from '@/stores/selection'

const store = useSelectionStore()
const offers = computed(() => store.result?.offers ?? [])

function pct(score: number): string {
  return `${Math.round(score * 100)}%`
}
</script>

<template>
  <section v-if="offers.length" class="panel">
    <h3 class="panel-title">
      ③ 货源匹配（{{ offers.length }} 条）
      <span class="badge">数据源: {{ store.config?.supplier_source === 'jiafang' ? '找家纺网 真实数据' : '本地样本' }}</span>
    </h3>
    <div class="table-wrap">
      <table class="offers">
        <thead>
          <tr>
            <th>匹配度</th>
            <th>货源</th>
            <th>价格</th>
            <th>供货条件</th>
            <th>商家</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in offers" :key="o.title">
            <td>
              <div class="score">
                <span class="score-num">{{ pct(o.match_score) }}</span>
                <div class="bar">
                  <div class="bar-fill" :style="{ width: pct(o.match_score), background: o.match_score >= 0.6 ? 'var(--success)' : o.match_score >= 0.4 ? 'var(--warn)' : 'var(--danger)' }"></div>
                </div>
              </div>
            </td>
            <td class="title-cell">{{ o.title }}</td>
            <td class="price">{{ o.price }}</td>
            <td class="cond">
              <span v-if="o.min_order" class="cond-item">{{ o.min_order }}</span>
              <span v-if="o.delivery" class="cond-item">{{ o.delivery }}</span>
            </td>
            <td class="supplier">{{ o.supplier_name }}</td>
          </tr>
        </tbody>
      </table>
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

.badge {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-dim);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 2px 8px;
}

.table-wrap {
  overflow-x: auto;
}

.offers {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.offers th {
  text-align: left;
  color: var(--text-dim);
  font-weight: 600;
  font-size: 12px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.offers td {
  padding: 10px;
  border-bottom: 1px solid rgba(51, 65, 85, 0.5);
  vertical-align: middle;
}

.score {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 120px;
}

.score-num {
  font-weight: 700;
  font-size: 13px;
  min-width: 40px;
}

.bar {
  flex: 1;
  height: 6px;
  background: var(--bg);
  border-radius: 3px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 3px;
}

.title-cell {
  min-width: 260px;
  line-height: 1.5;
}

.price {
  color: var(--primary);
  font-weight: 700;
  white-space: nowrap;
}

.cond {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.cond-item {
  font-size: 11px;
  color: var(--success);
  border: 1px solid var(--success);
  border-radius: 4px;
  padding: 1px 6px;
  white-space: nowrap;
}

.supplier {
  color: var(--text-dim);
  font-size: 12px;
  max-width: 220px;
}
</style>
