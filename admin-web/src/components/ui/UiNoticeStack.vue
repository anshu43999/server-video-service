<script setup lang="ts">
import { ElAlert } from 'element-plus'

export interface NoticeItem { id: string; title: string; message?: string; tone?: 'success' | 'error' | 'info' }
withDefaults(defineProps<{ notices: NoticeItem[] }>(), { notices: () => [] })
defineEmits<{ dismiss: [id: string] }>()
</script>

<template>
  <div class="notice-stack" aria-live="polite" aria-relevant="additions removals">
    <ElAlert v-for="notice in notices" :key="notice.id" class="notice-item" :type="notice.tone ?? 'info'" :title="notice.title" :description="notice.message" show-icon @close="$emit('dismiss', notice.id)" />
  </div>
</template>
