import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from './stores/auth'

const routes = [
  { path: '/', redirect: '/join' },
  { path: '/join', component: () => import('./views/JoinTest.vue') },
  { path: '/attempt/:id', component: () => import('./views/TakeTest.vue'), meta: { auth: true } },
  { path: '/my-results', component: () => import('./views/MyResults.vue'), meta: { auth: true } },
  { path: '/my-results/:id', component: () => import('./views/ResultDetail.vue'), meta: { auth: true } },
  { path: '/admin/tests', component: () => import('./views/admin/TestList.vue'), meta: { auth: true, role: 'teacher' } },
  { path: '/admin/tests/upload', component: () => import('./views/admin/TestUpload.vue'), meta: { auth: true, role: 'teacher' } },
  { path: '/admin/tests/:id', component: () => import('./views/admin/TestDetail.vue'), meta: { auth: true, role: 'teacher' } },
  { path: '/admin/tests/:id/results', component: () => import('./views/admin/TestResults.vue'), meta: { auth: true, role: 'teacher' } },
  { path: '/admin/attempts/:id', component: () => import('./views/admin/AttemptDetail.vue'), meta: { auth: true, role: 'teacher' } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async (to) => {
  if (!to.meta.auth) return true
  const auth = useAuthStore()
  if (!auth.user) await auth.fetchMe()
  if (!auth.user) {
    window.location.href = '/auth/login?next=' + encodeURIComponent(window.location.href)
    return false
  }
  if (to.meta.role && !['teacher', 'admin'].includes(auth.user.role)) {
    return '/join'
  }
  return true
})

export default router
