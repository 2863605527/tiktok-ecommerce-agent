// 图片优化 API（POST /api/v1/images/process | /process/batch）
import { http } from '@/api/client'
import type { ImageProcessBatchResult, ImageProcessResult } from '@/api/types'

export type BgMode = 'ai' | 'heuristic'

export async function processImage(
  imageUrl: string,
  ratio = '1:1',
  whiteBg = true,
  bgMode: BgMode = 'ai',
): Promise<ImageProcessResult> {
  return http.post<ImageProcessResult>('/api/v1/images/process', {
    image_url: imageUrl,
    ratio,
    white_bg: whiteBg,
    bg_mode: bgMode,
  })
}

export async function processImageBatch(
  imageUrls: string[],
  ratio = '1:1',
  whiteBg = true,
  bgMode: BgMode = 'ai',
): Promise<ImageProcessBatchResult> {
  return http.post<ImageProcessBatchResult>('/api/v1/images/process/batch', {
    image_urls: imageUrls,
    ratio,
    white_bg: whiteBg,
    bg_mode: bgMode,
  })
}
