<script setup lang="ts">
import { computed } from 'vue'
import { ElProgress } from 'element-plus'

const props = defineProps<{ value?: number | null; label: string }>()
const percentage = computed(() => Math.max(0, Math.min(100, Number(props.value ?? 0))))
</script>

<template>
  <ElProgress class="ui-progress" :class="{ 'is-indeterminate': value == null }" :percentage="percentage" :show-text="false" :aria-label="label" :aria-valuenow="value == null ? undefined : percentage" :aria-valuetext="value == null ? '处理中，进度未知' : `${percentage}%`" />
</template>
