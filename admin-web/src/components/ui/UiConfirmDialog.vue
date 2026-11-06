<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElDialog } from 'element-plus'
import { TriangleAlert } from '@lucide/vue'
import UiButton from './UiButton.vue'

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  cancelLabel?: string
  tone?: 'default' | 'danger'
  busy?: boolean
}>(), { confirmLabel: '确认', cancelLabel: '取消', tone: 'default', busy: false })
const emit = defineEmits<{ 'update:open': [value: boolean]; confirm: []; cancel: [] }>()
const cancelButton = ref<{ focus: () => void }>()
const dialog = ref<InstanceType<typeof ElDialog>>()
function close(cancelled: boolean) {
  if (props.busy) return
  emit('update:open', false)
  if (cancelled) emit('cancel')
}

function confirm() {
  if (!props.busy) emit('confirm')
}
function focusCancel() {
  applyAlertDialogSemantics()
  cancelButton.value?.focus()
}
function applyAlertDialogSemantics() {
  const exposed = dialog.value?.dialogContentRef as { $el?: HTMLElement } | HTMLElement | undefined
  const content = exposed instanceof HTMLElement
    ? exposed
    : exposed?.$el ?? document.querySelector<HTMLElement>('.el-dialog.confirm-dialog') ?? undefined
  const container = content?.closest<HTMLElement>('.el-overlay-dialog')
  container?.setAttribute('role', 'alertdialog')
}
watch(() => props.open, (open) => { if (open) applyAlertDialogSemantics() }, { flush: 'post' })

</script>

<template>
  <ElDialog
    ref="dialog"
    class="confirm-dialog"
    :model-value="open"
    :title="title"
    :show-close="!busy"
    :close-on-click-modal="!busy"
    :close-on-press-escape="!busy"
    append-to-body
    destroy-on-close
    @open="applyAlertDialogSemantics"
    @open-auto-focus="focusCancel"
    @keydown.esc.prevent="close(true)"
    @update:model-value="value => { if (!value) close(true) }"
  >
    <div class="confirm-dialog-copy">
      <span class="dialog-symbol" :class="{ danger: tone === 'danger' }" aria-hidden="true"><TriangleAlert :size="21" /></span>
      <p>{{ description }}</p>
    </div>
    <template #footer><div class="confirm-dialog-actions">
      <UiButton ref="cancelButton" class="secondary-button" type="button" :disabled="busy" @click="close(true)">{{ cancelLabel }}</UiButton>
      <UiButton class="primary-button" :class="{ danger: tone === 'danger' }" type="button" :disabled="busy" :loading="busy" @click="confirm">{{ busy ? '处理中…' : confirmLabel }}</UiButton>
    </div></template>
  </ElDialog>
</template>
