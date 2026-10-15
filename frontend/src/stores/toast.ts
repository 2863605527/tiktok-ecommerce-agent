// 全局 Toast 通知：收藏成功 / 复制成功 / 导出成功 / 操作失败等统一反馈
import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ToastKind = 'success' | 'info' | 'error'

export interface ToastItem {
  id: number
  kind: ToastKind
  text: string
}

let seq = 0

export const useToastStore = defineStore('toast', () => {
  const items = ref<ToastItem[]>([])

  function _push(kind: ToastKind, text: string, ttl = 2600) {
    const id = ++seq
    items.value.push({ id, kind, text })
    // 最多保留 3 条，先进先出
    if (items.value.length > 3) items.value.shift()
    setTimeout(() => remove(id), ttl)
  }

  function success(text: string) {
    _push('success', text)
  }

  function info(text: string) {
    _push('info', text)
  }

  function error(text: string) {
    _push('error', text, 4200)
  }

  function remove(id: number) {
    items.value = items.value.filter((t) => t.id !== id)
  }

  return { items, success, info, error, remove }
})
