<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Image, ImageOff, LoaderCircle } from '@lucide/vue'
import { isApiError } from '../../api/errors'
import { projectScope } from '../../api/projectScope'
import { useVisibleElement } from '../../api/useVisibleElement'
import { alertsApi } from './api'
import { evidenceRequests } from './evidenceRequests'
import { alertTitle, hasEvidence } from './presenters'
import type { AlertEvent } from './types'
import EvidenceImage from './EvidenceImage.vue'

const props = defineProps<{ event: AlertEvent }>()
const element = ref<HTMLElement>(), visible = useVisibleElement(element)
const phase = ref<'idle' | 'loading' | 'ready' | 'empty' | 'error'>('idle'), url = ref('')
const identity = computed(() => JSON.stringify([props.event.projectId, props.event.eventId, props.event.evidence]))
let controller: AbortController | undefined, disposed = false
function release() {
  controller?.abort(); controller = undefined
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = ''; phase.value = 'idle'
}
function fail() { release(); phase.value = 'error' }
async function load() {
  release()
  if (disposed || !visible.value) return
  if (!hasEvidence(props.event)) { phase.value = 'empty'; return }
  const reader = new AbortController(), key = identity.value, generation = projectScope.generation, eventId = props.event.eventId
  controller = reader; phase.value = 'loading'
  try {
    const blob = await evidenceRequests.run(signal => alertsApi.evidence(eventId, signal), reader.signal)
    if (disposed || reader.signal.aborted || key !== identity.value || generation !== projectScope.generation) return
    if (!blob.size) { phase.value = 'empty'; return }
    url.value = URL.createObjectURL(blob); phase.value = 'ready'
  } catch (error) {
    if (disposed || reader.signal.aborted || (isApiError(error) && error.kind === 'cancelled')) return
    phase.value = isApiError(error) && error.status === 404 ? 'empty' : 'error'
  }
}
watch([visible, identity], () => { void load() }, { immediate: true })
const unregister = projectScope.onClear(() => { disposed = true; release() })
onBeforeUnmount(() => { disposed = true; unregister(); release() })
</script>

<template>
  <span ref="element" class="evidence-indicator" :class="{ available: phase === 'ready' }">
    <EvidenceImage v-if="phase === 'ready'" :src="url" :event="event" :alt="`${alertTitle(event)}证据缩略图`" @error="fail" />
    <LoaderCircle v-else-if="phase === 'loading'" class="spinning" :size="18" aria-hidden="true" />
    <ImageOff v-else-if="phase === 'empty' || !hasEvidence(event)" :size="18" aria-hidden="true" />
    <Image v-else :size="18" aria-hidden="true" />
    <small>{{ phase === 'ready' ? '有证据' : phase === 'loading' ? '读取中' : phase === 'empty' || !hasEvidence(event) ? '无证据' : phase === 'error' ? '读取失败' : '待显示时读取' }}</small>
  </span>
</template>
