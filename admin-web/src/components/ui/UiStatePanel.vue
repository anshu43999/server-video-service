<script setup lang="ts">
import { computed } from 'vue'
import { ElEmpty, ElResult, ElSkeleton, ElSkeletonItem } from 'element-plus'
import { RotateCw } from '@lucide/vue'
import UiButton from './UiButton.vue'

export type ViewState = 'loading' | 'empty' | 'error'
const props = withDefaults(defineProps<{ state: ViewState; title?: string; message?: string; retryLabel?: string }>(), { retryLabel: '重新加载' })
defineEmits<{ retry: [] }>()

const defaults = {
  loading: { title: '正在加载', message: '正在读取服务端数据，请稍候。' },
  empty: { title: '暂无数据', message: '当前条件下没有可显示的记录。' },
  error: { title: '数据不可用', message: '请求未能完成，请检查连接后重试。' },
}
const copy = computed(() => ({ title: props.title ?? defaults[props.state].title, message: props.message ?? defaults[props.state].message }))
</script>

<template>
  <section class="state-panel" :class="`is-${state}`" :aria-live="state === 'loading' ? 'polite' : 'assertive'" :aria-busy="state === 'loading'">
    <ElSkeleton v-if="state === 'loading'" animated class="state-loading"><template #template><ElSkeletonItem variant="circle" /><div><h3>{{ copy.title }}</h3><p>{{ copy.message }}</p></div></template></ElSkeleton>
    <ElEmpty v-else-if="state === 'empty'" :image-size="56"><template #description><div><h3>{{ copy.title }}</h3><p>{{ copy.message }}</p></div></template></ElEmpty>
    <ElResult v-else icon="error" :title="copy.title" :sub-title="copy.message"><template #extra><UiButton class="secondary-button" type="button" @click="$emit('retry')"><RotateCw :size="16" aria-hidden="true" />{{ retryLabel }}</UiButton></template></ElResult>
  </section>
</template>
