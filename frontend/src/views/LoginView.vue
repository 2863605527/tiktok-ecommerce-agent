<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { checkEmail, checkPassword, checkUsername } from '@/api/auth'

const router = useRouter()
const auth = useAuthStore()

const mode = ref<'login' | 'register'>('login')
const identifier = ref('')
const username = ref('')
const email = ref('')
const password = ref('')
const confirm = ref('')
const errorMsg = ref('')
const busy = ref(false)

const formError = ref('')

function validate(): string | null {
  if (mode.value === 'register') {
    if (checkUsername(username.value)) return checkUsername(username.value)!
    if (checkEmail(email.value)) return checkEmail(email.value)!
    if (checkPassword(password.value)) return checkPassword(password.value)!
    if (password.value !== confirm.value) return '两次输入的密码不一致'
  } else {
    if (!identifier.value.trim()) return '请输入用户名或邮箱'
    if (!password.value) return '请输入密码'
  }
  return null
}

async function onSubmit() {
  formError.value = validate() ?? ''
  if (formError.value) return
  busy.value = true
  errorMsg.value = ''
  try {
    if (mode.value === 'register') {
      await auth.register(username.value, email.value, password.value)
    } else {
      await auth.login(identifier.value, password.value)
    }
    router.push('/')
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : '操作失败，请稍后重试'
  } finally {
    busy.value = false
  }
}

function switchMode(m: 'login' | 'register') {
  mode.value = m
  errorMsg.value = ''
  formError.value = ''
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="brand">TikTok 跨境选品 Agent</h1>
      <p class="sub">采集竞品 → RAG 分析 → 货源匹配 → 上架素材</p>

      <div class="tabs">
        <button :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</button>
        <button :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</button>
      </div>

      <form class="form" @submit.prevent="onSubmit">
        <template v-if="mode === 'register'">
          <label class="field">
            <span>用户名</span>
            <input v-model="username" maxlength="20" placeholder="3-20 位字母/数字/下划线"
              autocomplete="username" />
          </label>
          <label class="field">
            <span>邮箱</span>
            <input v-model="email" maxlength="64" type="email" placeholder="you@example.com"
              autocomplete="email" />
          </label>
        </template>
        <template v-else>
          <label class="field">
            <span>用户名或邮箱</span>
            <input v-model="identifier" maxlength="64" placeholder="请输入用户名或邮箱"
              autocomplete="username" />
          </label>
        </template>
        <label class="field">
          <span>密码</span>
          <input v-model="password" type="password" placeholder="至少 8 位，含字母和数字"
            autocomplete="current-password" />
        </label>
        <label v-if="mode === 'register'" class="field">
          <span>确认密码</span>
          <input v-model="confirm" type="password" placeholder="再次输入密码"
            autocomplete="new-password" />
        </label>

        <p v-if="formError" class="err">{{ formError }}</p>
        <p v-if="errorMsg" class="err">{{ errorMsg }}</p>

        <button class="submit" type="submit" :disabled="busy">
          {{ busy ? '处理中…' : mode === 'login' ? '登录' : '注册并登录' }}
        </button>
      </form>

      <p class="hint">登录账号有格式验证（用户名/邮箱/密码强度），注册即登录。</p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #eff6ff, #f5f3ff);
  padding: 24px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: var(--shadow);
  padding: 32px 28px;
}

.brand {
  font-size: 20px;
  margin: 0 0 4px;
  text-align: center;
  color: var(--text);
}

.sub {
  text-align: center;
  color: var(--text-dim);
  font-size: 12px;
  margin: 0 0 22px;
}

.tabs {
  display: flex;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 4px;
  margin-bottom: 18px;
}

.tabs button {
  flex: 1;
  border: none;
  background: transparent;
  padding: 9px 0;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  color: var(--text-dim);
}

.tabs button.active {
  background: linear-gradient(135deg, #2563eb, #6366f1);
  color: #fff;
  font-weight: 600;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field span {
  font-size: 12px;
  color: var(--text-dim);
}

.field input {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 14px;
  color: var(--text);
  background: #fff;
  outline: none;
  transition: border-color 0.15s;
}

.field input:focus {
  border-color: var(--primary);
}

.err {
  color: var(--danger);
  font-size: 12px;
  margin: 0;
}

.submit {
  margin-top: 6px;
  background: linear-gradient(135deg, #2563eb, #6366f1);
  border: none;
  color: #fff;
  border-radius: 10px;
  padding: 12px 0;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
}

.submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.hint {
  text-align: center;
  color: var(--border);
  font-size: 11px;
  margin: 18px 0 0;
}
</style>
