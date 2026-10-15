<script setup lang="ts">
import { useSelectionStore } from '@/stores/selection'

const store = useSelectionStore()
</script>

<template>
  <div class="picker">
    <button
      v-for="c in store.categories"
      :key="c.name"
      type="button"
      class="cat-btn"
      :class="{ active: store.category === c.name }"
      @click="store.category = c.name"
    >
      <span class="name">{{ c.display_name }}</span>
      <span class="desc">{{ c.description }}</span>
    </button>
  </div>
</template>

<style scoped>
.picker {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.cat-btn {
  flex: 1 1 180px;
  max-width: 260px;
  text-align: left;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.cat-btn:hover {
  border-color: var(--primary);
}

.cat-btn.active {
  border-color: var(--primary);
  background: var(--primary-bg);
}

.name {
  display: block;
  font-weight: 700;
  font-size: 14px;
  color: var(--text);
}

.desc {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-dim);
}
</style>
