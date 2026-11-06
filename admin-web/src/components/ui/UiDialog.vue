<script setup lang="ts">
import { ElDialog } from 'element-plus'
const props = defineProps<{ open: boolean; title: string; busy?: boolean }>()
const emit = defineEmits<{ 'update:open': [open: boolean] }>()
function update(open: boolean) { if (!props.busy || open) emit('update:open', open) }
</script>
<template>
  <ElDialog
    class="model-dialog model-workspace ui-dialog"
    :model-value="open"
    :title="title"
    :show-close="!busy"
    :close-on-click-modal="!busy"
    :close-on-press-escape="!busy"
    append-to-body
    destroy-on-close
    @update:model-value="update"
  ><slot v-if="open" /></ElDialog>
</template>
