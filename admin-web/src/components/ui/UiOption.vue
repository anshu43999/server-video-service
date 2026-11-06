<script setup lang="ts">
import { computed, useSlots, type VNode } from 'vue'
import { ElOption } from 'element-plus'

const props = defineProps<{ value: string | number; label?: string; disabled?: boolean }>()
const slots = useSlots()
function slotText(nodes: VNode[]): string {
  return nodes.map(node => Array.isArray(node.children)
    ? slotText(node.children as VNode[])
    : typeof node.children === 'string' ? node.children : '').join('')
}
const resolvedLabel = computed(() => props.label ?? (slotText(slots.default?.() ?? []).trim() || String(props.value)))
</script>

<template>
  <ElOption :value="value" :label="resolvedLabel" :disabled="disabled"><slot /></ElOption>
</template>
