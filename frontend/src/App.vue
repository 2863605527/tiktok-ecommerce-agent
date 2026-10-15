<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSelectionStore } from '@/stores/selection'
import { useAuthStore } from '@/stores/auth'
import { useFavoritesStore } from '@/stores/favorites'
import ToastHost from '@/components/ToastHost.vue'

const store = useSelectionStore()
const auth = useAuthStore()
const fav = useFavoritesStore()
const router = useRouter()

onMounted(() => {
  store.loadMeta()
  fav.init()
  auth.init()
})

function onLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="app-shell">
    <!-- 全局操作反馈（收藏/复制/导出等） -->
    <ToastHost />
    <header class="topbar">
      <div class="brand">
        <span class="logo">TK</span>
        <div>
          <div class="title">TikTok 跨境选品 Agent</div>
          <div class="subtitle">采集竞品 → RAG 分析 → 货源匹配 → 上架素材</div>
        </div>
      </div>
      <div class="right">
        <!-- 业务导航仅登录后可见；未登录只显示登录入口（企业系统惯例） -->
        <nav v-if="auth.user">
          <RouterLink to="/" class="nav-link">电商助手</RouterLink>
          <RouterLink to="/workbench" class="nav-link">选品工作台</RouterLink>
          <RouterLink to="/images" class="nav-link">图片优化</RouterLink>
          <RouterLink to="/about" class="nav-link">数据源与使用</RouterLink>
        </nav>
        <div v-if="auth.user" class="user-box">
          <span class="user-name">{{ auth.user.username }}</span>
          <button class="logout" title="退出登录" @click="onLogout">退出</button>
        </div>
        <RouterLink v-else to="/login" class="guest-login">登录</RouterLink>
      </div>
    </header>
    <main class="content">
      <!-- KeepAlive：切标签/路由时保留组件状态（跑流程切走再回来，进度不丢） -->
      <RouterView v-slot="{ Component }">
        <KeepAlive :include="['chat', 'workbench', 'images']">
          <component :is="Component" />
        </KeepAlive>
      </RouterView>
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 28px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 10;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: linear-gradient(135deg, #38bdf8, #6366f1);
  color: #fff;
  font-weight: 800;
  font-size: 15px;
}

.title {
  font-size: 16px;
  font-weight: 700;
}

.subtitle {
  font-size: 12px;
  color: var(--text-dim);
}

.right {
  display: flex;
  align-items: center;
  gap: 14px;
}

nav {
  display: flex;
  gap: 8px;
}

.nav-link {
  padding: 8px 16px;
  border-radius: 8px;
  color: var(--text-dim);
  font-size: 14px;
}

.nav-link:hover {
  color: var(--text);
  background: var(--bg-card-hover);
  text-decoration: none;
}

.nav-link.router-link-active {
  color: var(--primary);
  background: var(--primary-bg);
}

.user-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 14px;
  border-left: 1px solid var(--border);
}

.guest-login {
  padding: 8px 20px;
  border-radius: var(--radius-sm);
  background: var(--primary);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  transition: background var(--dur) var(--ease);
}

.guest-login:hover {
  color: #fff;
  opacity: 0.9;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.logout {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-dim);
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.logout:hover {
  color: var(--danger);
  border-color: var(--danger);
}

.content {
  flex: 1;
  padding: 24px 28px 48px;
  max-width: 1240px;
  width: 100%;
  margin: 0 auto;
}
</style>
