<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSessionStore } from '../../stores/session'

const session = useSessionStore()
const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')
const heading = computed(() => session.setupRequired ? '创建首个管理员' : '登录管理后台')

function safeRedirect(value: unknown) {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : '/overview'
}

async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await session.submit(username.value, password.value)
    password.value = ''
    await router.replace(safeRedirect(route.query.redirect))
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '登录失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-identity" aria-label="产品标识">
      <span class="brand-mark" aria-hidden="true">⌘</span>
      <div><strong>智慧巡检平台</strong><span>AI 移动巡检 · 运维管理台</span></div>
    </section>
    <form class="auth-form" @submit.prevent="submit">
      <p class="eyebrow">ACCOUNT SESSION</p>
      <h1>{{ heading }}</h1>
      <p class="auth-intro">使用服务器账号建立受保护的管理会话。</p>
      <label><span>账号</span><UiInput v-model.trim="username" name="username" autocomplete="username" minlength="3" maxlength="128" required autofocus /></label>
      <label><span>密码</span><UiInput v-model="password" name="password" type="password" :autocomplete="session.setupRequired ? 'new-password' : 'current-password'" minlength="8" maxlength="256" required /></label>
      <p v-if="session.setupRequired" class="setup-note">此账号将成为首个管理员。初始化完成后，入口不会再次开放。</p>
      <div class="auth-message" aria-live="polite">{{ error || session.message }}</div>
      <UiButton type="submit" :disabled="busy">{{ busy ? '正在验证…' : (session.setupRequired ? '创建并登录' : '登录') }}</UiButton>
    </form>
  </main>
</template>
