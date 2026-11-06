<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AlertEvent } from './types'
import { containImage, evidenceBoxes } from './evidenceOverlay'

const props = defineProps<{ src: string; alt: string; event: AlertEvent }>()
const emit = defineEmits<{ error: [] }>()
const image = ref<HTMLImageElement>()
const loaded = ref(false)
const viewport = ref<ReturnType<typeof containImage>>()
const boxes = computed(() => loaded.value ? evidenceBoxes(props.event) : [])
let observer: ResizeObserver | undefined
function measure() {
  const element = image.value
  viewport.value = element && loaded.value
    ? containImage(element.clientWidth, element.clientHeight, element.naturalWidth, element.naturalHeight) : undefined
}
function onLoad() { loaded.value = true; measure() }
function onError() { loaded.value = false; viewport.value = undefined; emit('error') }
watch([() => props.src, () => props.event.projectId, () => props.event.eventId], () => {
  loaded.value = false; viewport.value = undefined
}, { flush: 'sync' })
onMounted(() => {
  observer = new ResizeObserver(measure)
  if (image.value) observer.observe(image.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <span class="evidence-image">
    <img ref="image" :src="src" :alt="alt" @load="onLoad" @error="onError" />
    <span v-if="viewport && boxes.length" class="evidence-annotations" aria-hidden="true"
      :style="{ left: `${viewport.x}px`, top: `${viewport.y}px`, width: `${viewport.width}px`, height: `${viewport.height}px` }">
      <span v-for="(box, index) in boxes" :key="index" class="evidence-box"
        :style="{ left: `${box.left * 100}%`, top: `${box.top * 100}%`, width: `${(box.right - box.left) * 100}%`, height: `${(box.bottom - box.top) * 100}%` }">
        <span class="evidence-box-label">{{ box.label }} {{ Math.round(box.confidence * 100) }}%</span>
      </span>
    </span>
  </span>
</template>

<style scoped>
.evidence-image { display: block; position: relative; width: 100%; height: 100%; min-width: 0; overflow: hidden; }
.evidence-image img { display: block; width: 100%; height: 100%; object-fit: contain; }
.evidence-annotations { position: absolute; pointer-events: none; overflow: hidden; }
.evidence-box { position: absolute; box-sizing: border-box; border: 2px solid #ffbe2d; }
.evidence-box-label { position: absolute; top: 0; left: 0; max-width: 220px; padding: 2px 4px; overflow: hidden; color: #fff; background: #1d2730; font-size: 12px; line-height: 1.3; white-space: nowrap; text-overflow: ellipsis; }
</style>
