// 经营测算 + 一键诊断 API 封装
import { http } from './client'
import type { DiagnosticsResult, ProfitResult } from './types'

export interface ProfitRequest {
  selling_price_jpy: number
  cost_cny: number
  shipping_cny?: number
  ads_jpy?: number
  platform_fee_rate?: number
  payment_fee_rate?: number
}

export const businessApi = {
  /** 单件利润测算（售价 JPY + 成本/运费 CNY → 毛利/净利/净利率） */
  estimateProfit(req: ProfitRequest): Promise<ProfitResult> {
    return http.post<ProfitResult>('/api/v1/business/profit', req)
  },

  /** 一键诊断全部真实数据源（SocialCrawl/Milvus/找家纺/LLM） */
  runDiagnostics(): Promise<DiagnosticsResult> {
    return http.get<DiagnosticsResult>('/api/v1/diagnostics')
  },
}
