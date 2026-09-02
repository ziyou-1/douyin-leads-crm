import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ROLES, getDefaultRoute } from '@/constants/roles'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    redirect: () => getDefaultRoute(useUserStore().role),
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/Dashboard.vue'),
        meta: { title: '仪表盘', icon: 'Odometer', requiresAuth: true, blockRoles: [ROLES.CUSTOMER_SERVICE_ADMIN] },
      },
      {
        path: 'monitor',
        name: 'Monitor',
        component: () => import('@/views/monitor/MonitorList.vue'),
        meta: { title: '监控管理', icon: 'Monitor', requiresAuth: true },
      },
      {
        path: 'leads',
        name: 'Leads',
        component: () => import('@/views/leads/LeadList.vue'),
        meta: { title: '线索管理', icon: 'User', requiresAuth: true, blockRoles: [ROLES.CUSTOMER_SERVICE_ADMIN] },
      },
      {
        path: 'chat',
        name: 'Chat',
        component: () => import('@/views/chat/ChatView.vue'),
        meta: { title: '聊天', icon: 'ChatDotRound', requiresAuth: true, blockRoles: [ROLES.CUSTOMER_SERVICE_ADMIN] },
      },
      {
        path: 'users',
        name: 'Users',
        component: () => import('@/views/users/UserList.vue'),
        meta: { title: '用户管理', icon: 'UserFilled', requiresAuth: true, roles: [ROLES.ADMIN, ROLES.CUSTOMER_SERVICE_ADMIN] },
      },
      {
        path: 'douyin-accounts',
        name: 'DouyinAccounts',
        component: () => import('@/views/accounts/DouyinAccountList.vue'),
        meta: { title: '抖音账号', icon: 'ChatLineRound', requiresAuth: true, roles: [ROLES.ADMIN] },
      },
      {
        path: 'alerts',
        name: 'Alerts',
        component: () => import('@/views/alerts/AlertList.vue'),
        meta: { title: '告警中心', icon: 'Bell', requiresAuth: true, blockRoles: [ROLES.CUSTOMER_SERVICE_ADMIN] },
      },
      {
        path: 'system-config',
        name: 'SystemConfig',
        component: () => import('@/views/system/ConfigManagement.vue'),
        meta: { title: '参数配置', icon: 'Setting', requiresAuth: true, roles: [ROLES.ADMIN] },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/404.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Navigation guard
router.beforeEach((to, _from, next) => {
  const userStore = useUserStore()
  const requiresAuth = to.matched.some((record) => record.meta.requiresAuth !== false)

  if (requiresAuth && !userStore.isLoggedIn) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  if (to.path === '/login' && userStore.isLoggedIn) {
    next(getDefaultRoute(userStore.role))
    return
  }

  // Role check
  const requiredRoles = to.meta.roles as string[] | undefined
  const blockRoles = to.meta.blockRoles as string[] | undefined
  const userRole = userStore.role

  if (blockRoles && blockRoles.includes(userRole)) {
    next('/404')
    return
  }

  if (requiredRoles && requiredRoles.length > 0) {
    if (!requiredRoles.includes(userRole)) {
      next('/404')
      return
    }
  }

  next()
})

export default router
