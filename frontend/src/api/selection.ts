// 后端 API 封装：选品流水线（同步 + SSE 流式）/ 品类列表 / 运行配置 / 历史结果库 / 素材包
import { http } from './client'
import type {
  Category,
  RuntimeConfig,
  SelectionRequest,
  SelectionResponse,
  SelectionStreamEvent,
  ListingPreview,
} from './types'

export interface SavedSelection {
  id: number
  product: string
  region: string
  category: string
  language: string
  status: string
  created_at: string
  result: SelectionResponse
}

export interface ListingPackageReq {
  listing_path: string
  image_urls: string[]
}

async function* readSelectionSSE(resp: Response): AsyncGenerator<SelectionStreamEvent> {
  if (!resp.ok || !resp.body) {
    throw new Error(`选品流式请求失败 (${resp.status})`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const line = frame.trim()
      if (!line.startsWith('data: ')) continue
      try {
        yield JSON.parse(line.slice(6)) as SelectionStreamEvent
      } catch {
        /* 忽略无法解析的帧 */
      }
    }
  }
}

export const selectionApi = {
  run(req: SelectionRequest): Promise<SelectionResponse> {
    return http.post<SelectionResponse>('/api/v1/selections', req)
  },

  /** SSE 流式：阶段进度 → 完成事件（工作台实时反馈） */
  async *runStream(req: SelectionRequest): AsyncGenerator<SelectionStreamEvent> {
    let resp: Response
    try {
      resp = await fetch('/api/v1/selections/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      })
    } catch {
      throw new Error('无法连接后端服务，请确认 FastAPI 已启动（见 docs/RUN_GUIDE.md）')
    }
    for await (const ev of readSelectionSSE(resp)) {
      yield ev
    }
  },

  listCategories(): Promise<Category[]> {
    return http.get<Category[]>('/api/v1/categories')
  },

  runtimeConfig(): Promise<RuntimeConfig> {
    return http.get<RuntimeConfig>('/api/v1/config')
  },

  health(): Promise<{ status: string }> {
    return http.get<{ status: string }>('/health')
  },

  // ---- 选品结果历史库（按用户隔离，跨设备持久化） ----

  listHistory(): Promise<SavedSelection[]> {
    return http.get<SavedSelection[]>('/api/v1/selections/history')
  },

  deleteHistory(id: number): Promise<{ ok: boolean }> {
    return http.request<{ ok: boolean }>('DELETE', `/api/v1/selections/history/${id}`)
  },

  // ---- 素材包 ZIP 下载 ----

  /** 导出前预览素材内容（人工批准门控：先看再下载） */
  previewListing(listingPath: string): Promise<ListingPreview> {
    return http.get<ListingPreview>(
      `/api/v1/listings/preview?listing_path=${encodeURIComponent(listingPath)}`,
    )
  },

  /** 下载 ZIP 流（listing.json + 商品图），返回 Blob */
  async packageListing(req: ListingPackageReq): Promise<Blob> {
    return this._downloadBlob('/api/v1/listings/package', req)
  },

  /** 下载 TikTok 批量上架 CSV（UTF-8 BOM，Excel 直接打开），返回 Blob */
  async downloadListingCsv(req: ListingPackageReq): Promise<Blob> {
    return this._downloadBlob('/api/v1/listings/csv', req)
  },

  async _downloadBlob(path: string, body: unknown): Promise<Blob> {
    const token = localStorage.getItem('tk-agent:auth:token')
    const resp = await fetch(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => null)
      throw new Error(err?.detail ?? `下载失败 (${resp.status})`)
    }
    return resp.blob()
  },
}
