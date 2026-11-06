<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../../stores/session'

const session = useSessionStore()
const router = useRouter()
const busy = ref(false)
async function logout() {
  busy.value = true
  try { await session.logout(); await router.replace('/login') } catch { /* Store exposes the unconfirmed state. */ }
  finally { busy.value = false }
}
</script>

<template>
  <main class="restricted-page">
    <section>
      <p class="eyebrow">ACCESS BOUNDARY</p>
      <h1>需要管理员权限</h1>
      <p>账号 <strong>{{ session.user?.username }}</strong> 已登录，但新版管理后台仅向管理员开放。</p>
      <p v-if="session.logoutUnconfirmed" class="auth-message" aria-live="polite">{{ session.message }}</p>
      <UiButton type="button" :disabled="busy" @click="logout">{{ busy ? '正在退出…' : '退出账号' }}</UiButton>
    </section>
  </main>
</template>
