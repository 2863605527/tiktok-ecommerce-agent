<script setup lang="ts">
// 全局 Toast 展示层：右上角浮层，自动消失（成功/信息/错误三种样式）
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()

function icon(kind: string): string {
  if (kind === 'success') return '✓'
  if (kind === 'error') return '✕'
  return 'ℹ'
}
</script>

<template>
  <div class="toast-host" aria-live="polite">
    <transition-group name="toast">
      <div v-for="t in toast.items" :key="t.id" class="toast" :class="'toast-' + t.kind">
        <span class="toast-icon">{{ icon(t.kind) }}</span>
        <span class="toast-text">{{ t.text }}</span>
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 3000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 200px;
  max-width: 380px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 10px 14px;
  font-size: 13px;
  color: var(--text);
  box-shadow: var(--shadow);
  pointer-events: auto;
}

.toast-icon {
  flex: 0 0 auto;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 800;
  color: #fff;
}

.toast-success .toast-icon { background: var(--success); }
.toast-info .toast-icon { background: var(--primary); }
.toast-error .toast-icon { background: var(--danger); }

.toast-text {
  flex: 1;
  min-width: 0;
  line-height: 1.5;
  word-break: break-word;
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s var(--ease);
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(24px);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(24px);
}
</style>
