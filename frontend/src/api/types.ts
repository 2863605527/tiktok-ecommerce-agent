// 与后端 API 对齐的类型定义（src/tiktok_ecommerce/models/*）

export interface Category {
  name: string
  display_name: string
  description: string
}

export interface RuntimeConfig {
  product_source: string
  supplier_source: string
  rag_backend: string
  fastmoss_region: string
  has_fastmoss_key: boolean
  fastmoss_key_masked: string
  has_socialcrawl_key: boolean
  socialcrawl_key_masked: string
  has_tikhub_key: boolean
  tikhub_key_masked: string
  jiafang_base_url: string
  llm_model: string
  embedding_model: string
}

// ---- 图片优化（POST /api/v1/images/process | /process/batch） ----

export interface ImageProcessResult {
  original_url: string
  processed_path: string
  processed_name: string
  ratio: string
  white_bg: boolean
  bg_used: 'ai' | 'heuristic' | 'none'
  ocr_backend: string
  has_text: boolean
  texts: string[]
  translations: { zh: string; ja: string }[]
  advice: string
}

export interface ImageProcessBatchResult {
  ok: number
  failed: number
  items: Array<ImageProcessResult & { error?: string }>
}

export interface ReviewInsight {
  topic: string
  sentiment: 'positive' | 'negative'
  mentions: number
  severity: string
  evidence: string[]
}

export interface SelectionReport {
  summary: string
  pros: string[]
  cons: string[]
  market_hot: string
  competition: string
  risks: string[]
  suggestion: string
  keywords: string[]
  insights: ReviewInsight[]
}

export interface SupplierOffer {
  title: string
  price: string
  min_order: string
  delivery: string
  supplier_name: string
  url: string
  images?: string[]
  match_score: number
  score_breakdown: Record<string, number | string>
}

export interface ListingPackage {
  title: string
  keywords: string[]
  description: string
  translated_title: string
  hashtags: string[]
  specs_translated: Record<string, string>
  images: string[]
}

/** 导出前预览（人工批准门控：先看内容再下载） */
export interface ListingPreview {
  listing_path: string
  title: string
  translated_title: string
  keywords: string[]
  hashtags: string[]
  description: string
  specs_translated: Record<string, string>
  has_images: boolean
}

export interface Product {
  id: string
  title: string
  price: string
  currency: string
  url: string
  sales: number
  rating?: number | null
  reviews_count?: number | null
  seller?: string
  brand?: string
  availability?: string
  category: string
  images?: string[]
  description?: string
  reviews?: Review[]
  /** 生命周期阶段（后端规则引擎基于真实评论时间序列判断，可空=数据不足） */
  lifecycle_stage?: string
  lifecycle_trend?: string
  lifecycle_confidence?: string
  lifecycle_window?: string
}

export interface Review {
  content: string
  rating: number
  helpful_count: number
  author?: string | null
}

export interface SelectionRequest {
  product: string
  region: string
  category: string
  language: string
  stages?: string[]
  image_dir?: string | null
}

export interface SelectionResponse {
  products: Product[]
  report: SelectionReport | null
  offers: SupplierOffer[]
  listing: ListingPackage | null
  listing_path: string
  error: string | null
  // 第三轮：决策增强
  score?: ScoreResult | null
  market_overview?: MarketOverview | null
  keyword_insights?: KeywordInsights | null
}

// ---- 决策增强（第三轮） ----

export interface ScoreDim {
  score: number
  max: number
  label: string
  reasons: string[]
}

export interface ScoreResult {
  total: number
  level: '强烈推荐' | '推荐' | '观望' | '谨慎'
  verdict: string
  dims: {
    heat: ScoreDim
    demand: ScoreDim
    supply: ScoreDim
    listing: ScoreDim
  }
  /** 进场时机（生命周期旁路参考，不计入总分） */
  timing?: ScoreDim & { note?: string }
}

export interface PriceBand {
  label: string
  count: number
  share: number
}

export interface MarketOverview {
  bands: PriceBand[]
  avg_price: number
  median_price: number
  min_price: number
  max_price: number
  sample_count: number
  note: string
}

export interface KeywordItem {
  word: string
  count: number
  source: string
}

export interface KeywordInsights {
  top: KeywordItem[]
  note: string
}

export interface ProfitResult {
  selling_price_jpy: number
  cost_jpy: number
  shipping_jpy: number
  gross_profit_jpy: number
  platform_fee_jpy: number
  payment_fee_jpy: number
  ads_jpy: number
  net_profit_jpy: number
  net_margin: number
  break_even_units: number | null
  fx_used: number
  platform_fee_rate: number
  payment_fee_rate: number
  note: string
}

export interface DiagnosticItem {
  name: string
  ok: boolean
  detail: string
}

export interface DiagnosticsResult {
  summary: string
  all_ok: boolean
  items: DiagnosticItem[]
  checked_at: string
}

export type StageKey = 'crawler' | 'analyzer' | 'sourcing' | 'listing'

// ---- 聊天模式（POST /api/v1/chat） ----

export type ChatIntent =
  | 'select_product'
  | 'sourcing_only'
  | 'listing_only'
  | 'listing_context'
  | 'sourcing_context'
  | 'profit'
  | 'qa_ecommerce'
  | 'out_of_scope'

export interface ChatRequest {
  message: string
  region: string
  category: string
  language: string
  conversation_id?: string
}

export interface ChatData {
  products?: Product[]
  report?: SelectionReport | null
  offers?: SupplierOffer[]
  listing?: ListingPackage | null
  listing_path?: string
  // 第三轮：决策增强 + 利润卡
  score?: ScoreResult | null
  market_overview?: MarketOverview | null
  keyword_insights?: KeywordInsights | null
  profit?: ProfitResult | null
}

export interface ChatResponse {
  reply: string
  intent: ChatIntent
  needs_product: boolean
  data: ChatData | null
}

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  intent?: ChatIntent
  needsProduct?: boolean
  data?: ChatData | null
  loading?: boolean
  /** 深度思考模式：展示"思考过程步骤"（大模型 agent 式），完成后折叠 */
  thinking?: boolean
  /** 思考步骤：阶段 + 说明（来自 SSE status 事件） */
  steps?: { stage: string; text: string }[]
  /** 思考/处理用时（秒），完成后展示"已思考（用时Xs）" */
  thinkingSeconds?: number
}

// ---- 流式（SSE）事件（POST /api/v1/chat/stream） ----

export type StreamEvent =
  | { type: 'status'; stage: string; text: string }
  | { type: 'delta'; text: string }
  | { type: 'done'; reply: string; intent: ChatIntent; needs_product: boolean; data: ChatData | null }
  | { type: 'error'; text: string }

// ---- 选品工作台流式事件（POST /api/v1/selections/stream） ----

export type SelectionStreamEvent =
  | { type: 'status'; stage: string; text: string }
  | { type: 'done'; result: SelectionResponse }
  | { type: 'error'; text: string }

