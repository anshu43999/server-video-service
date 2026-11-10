<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { streamsApi } from '../streams/api'
import { AdminPreview, type PreviewStatus } from '../streams/preview'
import type { StreamItem } from '../streams/types'
import { canPreview, streamStatus } from './presenters'
import { useVisibleElement } from '../../api/useVisibleElement'
const props = defineProps<{ stream: StreamItem }>()
const frame = ref(''), status = ref<PreviewStatus>('idle'), failedImage = ref(false)
const element = ref<HTMLElement>(), visible = useVisibleElement(element)
const runtime = computed(() => streamStatus(props.stream))
const preview = new AdminPreview({ waitForFrameLoad: true, onFrame: url => { frame.value = url }, onStatus: value => { status.value = value } })
let connection = 0
function reconnect() {
  failedImage.value = false
  if (canPreview(props.stream)) preview.start(streamsApi.previewUrl(props.stream.stream_id, ++connection))
  else preview.stop()
}
function imageError() { preview.frameFailed() }
watch(visible, value => preview.setVisible(value), { immediate: true })
watch([() => props.stream.stream_id, () => canPreview(props.stream)], reconnect, { immediate: true })
onBeforeUnmount(() => preview.stop())
</script>
<template>
  <article ref="element" class="board-tile">
    <header><strong>{{ stream.display_name || stream.stream_id }}</strong><span :class="`stream-tone-${runtime.key}`">{{ runtime.label }}</span></header>
    <div class="board-picture">
      <img v-if="frame && !failedImage" :src="frame" :alt="`${stream.display_name || stream.stream_id} 现场画面`" @load="preview.frameLoaded()" @error="imageError" />
      <div v-else class="board-preview-state"><span>{{ failedImage || status === 'error' ? '现场预览不可用' : !canPreview(stream) ? runtime.label : '等待现场画面' }}</span></div>
    </div>
    <footer><span>{{ stream.stream_id }} · {{ stream.received_fps == null ? 'FPS 不可用' : `${stream.received_fps.toFixed(1)} FPS` }}</span><UiButton v-if="canPreview(stream) && (failedImage || status === 'error' || status === 'waiting')" type="button" @click="reconnect">重连预览</UiButton></footer>
  </article>
</template>
