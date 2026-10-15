// 轻量 fetch 客户端：统一错误处理与 JSON 解析
// 开发环境经 Vite 代理（/api → http://127.0.0.1:8000），生产同源部署
// 鉴权：自动附加 Bearer token（localStorage），401 时清理会话并跳登录页

const TOKEN_KEY = 'tk-agent:auth:token'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* 存储不可用则忽略 */
  }
}

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

function extractMessage(body: unknown, fallback: string): string {
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>
    // 后端统一错误结构：{ "error": { "code", "message", "detail" } }
    const err = b.error as Record<string, unknown> | undefined
    if (err && typeof err.message === 'string') return err.message
    if (typeof b.message === 'string') return b.message
    if (typeof b.detail === 'string') return b.detail
    if (err && typeof err.detail === 'string') return err.detail
  }
  return fallback
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let resp: Response
  try {
    resp = await fetch(url, { headers, ...init })
  } catch (e) {
    throw new ApiError(0, '无法连接后端服务，请确认 FastAPI 已启动（见 docs/RUN_GUIDE.md）')
  }

  if (resp.status === 401) {
    // 先取后端真实错误信息（登录失败/凭据错误/token 失效各有原因）
    let body: unknown = null
    let message = '登录已过期，请重新登录'
    try {
      body = await resp.json()
      message = extractMessage(body, message)
    } catch {
      /* 非 JSON 错误体 */
    }
    const isAuthCall = url.includes('/auth/login') || url.includes('/auth/register')
    if (isAuthCall) {
      // 登录/注册本身的失败（用户名或密码错误等）：展示后端真实信息，不跳转
      throw new ApiError(401, message, body)
    }
    // 业务接口 token 无效/过期：清理会话并跳转登录页
    setToken(null)
    if (!window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
    throw new ApiError(401, message, body)
  }

  if (!resp.ok) {
    let detail: unknown = null
    let message = `请求失败 (${resp.status})`
    try {
      const body = await resp.json()
      detail = body
      message = extractMessage(body, message)
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new ApiError(resp.status, message, detail)
  }

  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export const http = {
  get: <T>(url: string): Promise<T> => request<T>(url),
  post: <T>(url: string, body: unknown): Promise<T> =>
    request<T>(url, { method: 'POST', body: JSON.stringify(body) }),
  request: <T>(method: string, url: string, body?: unknown): Promise<T> =>
    request<T>(url, {
      method,
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    }),
}
