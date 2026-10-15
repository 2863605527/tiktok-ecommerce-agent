// 认证状态 store：token 持久化（localStorage）+ 用户信息 + 登录/注册/退出
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi, type AuthUser } from '@/api/auth'
import { getToken, setToken } from '@/api/client'

const USER_KEY = 'tk-agent:auth:user'

function loadUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as AuthUser) : null
  } catch {
    return null
  }
}

function saveUser(user: AuthUser | null) {
  try {
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
    else localStorage.removeItem(USER_KEY)
  } catch {
    /* 忽略 */
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getToken())
  const user = ref<AuthUser | null>(loadUser())
  const loading = ref(false)
  const initialized = ref(false)

  const isAuthenticated = () => !!token.value

  async function login(identifier: string, password: string) {
    loading.value = true
    try {
      const res = await authApi.login(identifier.trim(), password)
      token.value = res.access_token
      user.value = res.user
      setToken(res.access_token)
      saveUser(res.user)
      return res.user
    } finally {
      loading.value = false
    }
  }

  async function register(username: string, email: string, password: string) {
    loading.value = true
    try {
      const res = await authApi.register(username.trim(), email.trim(), password)
      token.value = res.access_token
      user.value = res.user
      setToken(res.access_token)
      saveUser(res.user)
      return res.user
    } finally {
      loading.value = false
    }
  }

  function logout() {
    token.value = null
    user.value = null
    setToken(null)
    saveUser(null)
  }

  /** 刷新页面后用 localStorage 用户 + token 恢复会话（token 无效时静默登出）。 */
  async function init() {
    if (initialized.value) return
    initialized.value = true
    if (!token.value) {
      // 无 token 但残留 user → 一并清掉
      if (user.value) { user.value = null; saveUser(null) }
      return
    }
    // 刷新后以本地 user 为准（避免等待网络）；token 无效时 me() 抛 401 → client 跳登录
    if (!user.value) {
      try {
        user.value = await authApi.me()
        saveUser(user.value)
      } catch {
        /* 401 已在 client.ts 处理 */
      }
    }
  }

  return { token, user, loading, initialized, isAuthenticated, login, register, logout, init }
})
