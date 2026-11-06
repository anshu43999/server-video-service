<script setup lang="ts">
import { computed, ref, useAttrs } from 'vue'
import { ElButton } from 'element-plus'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  type?: 'button' | 'submit' | 'reset'
  disabled?: boolean
  loading?: boolean
}>(), { type: 'submit', disabled: false, loading: false })
const attrs = useAttrs()
const button = ref<InstanceType<typeof ElButton>>()
const tone = computed(() => {
  const classes = String(attrs.class ?? '')
  if (classes.includes('danger')) return 'danger'
  if (classes.includes('primary-button')) return 'primary'
  return 'default'
})
function focus() { (button.value?.$el as HTMLButtonElement | undefined)?.focus() }
defineExpose({ focus })
</script>

<template>
  <ElButton
    ref="button"
    v-bind="attrs"
    :native-type="type"
    :type="tone"
    :disabled="disabled"
    :loading="loading"
  ><slot /></ElButton>
</template>
