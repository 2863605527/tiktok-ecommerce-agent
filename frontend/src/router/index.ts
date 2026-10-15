import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '@/api/client'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { title: '登录 · 电商助手' },
    },
    {
      path: '/',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { title: '电商助手（聊天）', requiresAuth: true },
    },
    {
      path: '/workbench',
      name: 'workbench',
      component: () => import('@/views/WorkbenchView.vue'),
      meta: { title: '选品工作台', requiresAuth: true },
    },
    {
      path: '/images',
      name: 'images',
      component: () => import('@/views/ImageStudioView.vue'),
      meta: { title: '商品图片优化', requiresAuth: true },
    },
    {
      path: '/about',
      name: 'about',
      component: () => import('@/views/AboutView.vue'),
      meta: { title: '数据源与使用说明', requiresAuth: true },
    },
  ],
})

// 路由守卫：业务页需要登录；已登录访问 /login 跳回首页
router.beforeEach((to) => {
  const authed = !!getToken()
  if (to.meta.requiresAuth && !authed) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && authed) {
    return { name: 'chat' }
  }
  return true
})

router.afterEach((to) => {
  const title = to.meta.title as string | undefined
  document.title = title ? `${title} · TikTok 跨境选品 Agent` : 'TikTok 跨境选品 Agent'
})

export default router
