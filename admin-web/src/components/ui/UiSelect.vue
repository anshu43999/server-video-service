<script setup lang="ts">
import { computed, useAttrs } from 'vue'
import { ElSelect } from 'element-plus'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  modelValue?: string | number
  value?: string | number
  modelModifiers?: { number?: boolean }
  disabled?: boolean
  placeholder?: string
}>(), { disabled: false, modelModifiers: () => ({}) })
const emit = defineEmits<{
  'update:modelValue': [value: string | number]
  change: [value: string | number]
}>()
const attrs = useAttrs()
function changed(value: string | number) {
  const normalized = props.modelModifiers.number ? Number(value) : value
  emit('update:modelValue', normalized)
  emit('change', normalized)
}
const resolvedValue = computed(() => props.modelValue === undefined ? props.value : props.modelValue)
</script>

<template>
  <ElSelect
    v-bind="attrs"
    class="ui-select"
    :model-value="resolvedValue"
    :disabled="disabled"
    :placeholder="placeholder"
    @change="changed"
  ><slot /></ElSelect>
</template>
