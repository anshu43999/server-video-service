<script setup lang="ts">
import { computed, ref, useAttrs } from 'vue'
import { ElInput, ElInputNumber, ElSwitch, ElUpload, genFileId, type UploadFile, type UploadFiles, type UploadInstance, type UploadRawFile } from 'element-plus'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  modelValue?: string | number | boolean | null
  modelModifiers?: { trim?: boolean; number?: boolean }
  type?: string
  checked?: boolean
  disabled?: boolean
  accept?: string
}>(), { modelValue: undefined, type: 'text', checked: false, disabled: false, modelModifiers: () => ({}) })
const emit = defineEmits<{
  'update:modelValue': [value: string | number | boolean | undefined]
  change: [value: any]
}>()
const attrs = useAttrs()
const upload = ref<UploadInstance>()
const uploadKey = ref(0)
const switchValue = computed(() => typeof props.modelValue === 'boolean' ? props.modelValue : props.checked)

function normalize(value: string | number | boolean | undefined) {
  if (typeof value === 'string' && props.modelModifiers.trim) value = value.trim()
  if (props.modelModifiers.number && value !== '' && typeof value === 'string') value = Number(value)
  return value
}
function update(value: string | number | boolean | undefined) {
  emit('update:modelValue', normalize(value))
}
function fileChanged(_file: UploadFile, files: UploadFiles) {
  emit('change', files.at(-1)?.raw)
}
function fileExceeded(files: File[]) {
  const file = files[0] as UploadRawFile | undefined
  if (!file) return
  file.uid = genFileId()
  upload.value?.clearFiles()
  upload.value?.handleStart(file)
}
function switchChanged(value: string | number | boolean) {
  emit('update:modelValue', Boolean(value))
  emit('change', Boolean(value))
}
function clear() {
  upload.value?.clearFiles()
  uploadKey.value += 1
}
function setRawFile(file: UploadRawFile) {
  upload.value?.clearFiles()
  upload.value?.handleStart(file)
}
defineExpose({ clear, setRawFile })
</script>

<template>
  <ElUpload
    v-if="type === 'file'"
    :key="uploadKey"
    ref="upload"
    v-bind="attrs"
    class="ui-file-upload"
    action="#"
    :accept="accept"
    :auto-upload="false"
    :disabled="disabled"
    :limit="1"
    :show-file-list="false"
    @change="fileChanged"
    @exceed="fileExceeded"
  ><slot name="trigger"><span class="ui-file-trigger">选择文件</span></slot></ElUpload>
  <ElSwitch
    v-else-if="type === 'checkbox'"
    v-bind="attrs"
    class="ui-switch"
    :model-value="switchValue"
    :disabled="disabled"
    @change="switchChanged"
  />
  <ElInputNumber
    v-else-if="type === 'number'"
    v-bind="attrs"
    class="ui-number-input"
    controls-position="right"
    :model-value="typeof modelValue === 'number' ? modelValue : Number(modelValue ?? 0)"
    :disabled="disabled"
    @update:model-value="update"
    @change="value => emit('change', value)"
  />
  <ElInput
    v-else
    v-bind="attrs"
    class="ui-text-input"
    :model-value="modelValue == null ? '' : String(modelValue)"
    :type="type"
    :disabled="disabled"
    @update:model-value="update"
    @change="value => emit('change', value)"
  />
</template>
