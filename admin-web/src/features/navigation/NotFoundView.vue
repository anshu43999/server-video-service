<script setup lang="ts">
import { RouterLink } from 'vue-router'
import UiStatePanel from '../../components/ui/UiStatePanel.vue'
</script>

<template>
  <section aria-label="页面不存在">
    <UiStatePanel state="empty" title="无法打开此页面" message="当前地址没有对应的管理页面，请从导航选择菜单或返回总览。" />
    <RouterLink class="secondary-button" :to="{ name: 'overview' }">返回总览</RouterLink>
  </section>
</template>
