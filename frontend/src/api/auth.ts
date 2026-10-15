// 认证接口：注册 / 登录 / 当前用户
import { http } from '@/api/client'

export interface AuthUser {
  id: number
  username: string
  email: string
  created_at?: string
}

export interface AuthResult {
  access_token: string
  token_type: string
  user: AuthUser
}

export const authApi = {
  register(username: string, email: string, password: string): Promise<AuthResult> {
    return http.post<AuthResult>('/api/v1/auth/register', { username, email, password })
  },
  login(identifier: string, password: string): Promise<AuthResult> {
    return http.post<AuthResult>('/api/v1/auth/login', { identifier, password })
  },
  me(): Promise<AuthUser> {
    return http.get<AuthUser>('/api/v1/auth/me')
  },
}

// ---- 前端表单校验（与后端一致；后端仍是最终防线）----

const USERNAME_RE = /^[a-zA-Z0-9_]{3,20}$/
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

export function checkUsername(v: string): string | null {
  if (!USERNAME_RE.test(v)) return '用户名需为 3-20 位字母、数字或下划线'
  return null
}

export function checkEmail(v: string): string | null {
  if (!EMAIL_RE.test(v) || v.length > 64) return '邮箱格式不正确'
  return null
}

export function checkPassword(v: string): string | null {
  if (v.length < 8) return '密码至少 8 位'
  if (!/[A-Za-z]/.test(v) || !/[0-9]/.test(v)) return '密码需同时包含字母和数字'
  return null
}
