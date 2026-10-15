// 我的选品收藏库：聊天/工作台结果一键收藏（按用户隔离 localStorage）+ CSV 导出
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import type { Product, SupplierOffer, ListingPackage } from '@/api/types'

export interface FavoriteItem {
  id: string
  kind: 'product' | 'offer' | 'listing'
  title: string
  price?: string
  url?: string
  images?: string[]
  extra?: string
  createdAt: number
}

const LS_PREFIX = 'tk-agent:favorites:'

function lsKey(): string {
  const auth = useAuthStore()
  return LS_PREFIX + (auth.user?.username ?? 'guest')
}

function load(): FavoriteItem[] {
  try {
    const raw = localStorage.getItem(lsKey())
    const list = raw ? (JSON.parse(raw) as FavoriteItem[]) : []
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

function persist(list: FavoriteItem[]) {
  try {
    localStorage.setItem(lsKey(), JSON.stringify(list))
  } catch {
    /* 忽略 */
  }
}

export function csvEscape(v: unknown): string {
  const s = String(v ?? '')
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

export const useFavoritesStore = defineStore('favorites', () => {
  const items = ref<FavoriteItem[]>([])

  const count = computed(() => items.value.length)

  function init() {
    items.value = load()
  }

  function _fingerprint(title: string): string {
    return title.trim().slice(0, 60)
  }

  function has(title: string): boolean {
    const fp = _fingerprint(title)
    return items.value.some((f) => _fingerprint(f.title) === fp)
  }

  function add(item: Omit<FavoriteItem, 'id' | 'createdAt'>): void {
    if (has(item.title)) return
    items.value.unshift({ ...item, id: `fav-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, createdAt: Date.now() })
    persist(items.value)
  }

  function remove(id: string): void {
    items.value = items.value.filter((f) => f.id !== id)
    persist(items.value)
  }

  function clear(): void {
    items.value = []
    persist(items.value)
  }

  function addProduct(p: Product): void {
    add({
      kind: 'product',
      title: p.title,
      price: `${p.price} ${p.currency ?? ''}`.trim(),
      url: p.url,
      images: p.images,
      extra: p.sales > 0 ? `销量 ${p.sales}` : '销量未披露',
    })
  }

  function addOffer(o: SupplierOffer): void {
    add({
      kind: 'offer',
      title: o.title,
      price: o.price,
      url: o.url,
      images: o.images,
      extra: `${o.supplier_name} · 匹配 ${(o.match_score * 100).toFixed(0)}%`,
    })
  }

  function addListing(l: ListingPackage): void {
    add({
      kind: 'listing',
      title: l.title,
      url: '',
      extra: `关键词 ${l.keywords?.length ?? 0} 个 · 话题 ${l.hashtags?.length ?? 0} 个`,
    })
  }

  /** 导出 CSV（竞品/货源/素材三列式，可直接进表格/交接运营） */
  function exportCSV(): string {
    const header = ['类型', '标题', '价格', '补充', '链接']
    const rows = items.value.map((f) => [
      f.kind === 'product' ? '竞品' : f.kind === 'offer' ? '货源' : '上架素材',
      f.title,
      f.price ?? '',
      f.extra ?? '',
      f.url ?? '',
    ])
    return [header, ...rows].map((r) => r.map(csvEscape).join(',')).join('\n')
  }

  return { items, count, init, add, addProduct, addOffer, addListing, remove, clear, has, exportCSV }
})
