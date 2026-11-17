// 图片优化 API（POST /api/v1/images/process | /process/batch）
import { http } from '@/api/client'
import type { ImageProcessBatchResult, ImageProcessResult } from '@/api/types'

export type BgMode = 'ai' | 'heuristic'

/** 翻译方向：中→日 / 中→英 / 英→中 / 日→中 */
export type TransPair = 'zh2ja' | 'zh2en' | 'en2zh' | 'ja2zh'

export async function processImage(
  imageUrl: string,
  ratio = '1:1',
  whiteBg = true,
  bgMode: BgMode = 'ai',
  replaceText = false,
  transPair: TransPair = 'zh2ja',
): Promise<ImageProcessResult> {
  return http.post<ImageProcessResult>('/api/v1/images/process', {
    image_url: imageUrl,
    ratio,
    white_bg: whiteBg,
    bg_mode: bgMode,
    replace_text: replaceText,
    trans_pair: transPair,
  })
}

export async function processImageBatch(
  imageUrls: string[],
  ratio = '1:1',
  whiteBg = true,
  bgMode: BgMode = 'ai',
  replaceText = false,
  transPair: TransPair = 'zh2ja',
): Promise<ImageProcessBatchResult> {
  return http.post<ImageProcessBatchResult>('/api/v1/images/process/batch', {
    image_urls: imageUrls,
    ratio,
    white_bg: whiteBg,
    bg_mode: bgMode,
    replace_text: replaceText,
    trans_pair: transPair,
  })
}
