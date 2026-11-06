<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from 'vue'
import UiNoticeStack from '../../components/ui/UiNoticeStack.vue'
import { useProjectsStore } from '../../stores/projects'
import { alertTitle, alertSourceSummary } from './presenters'
import { useAlertsStore } from './store'
import { AlertSync } from './sync'

const projects = useProjectsStore()
const store = useAlertsStore()
const sync = new AlertSync(store)
const enabled = computed(() => projects.phase === 'ready'
  && projects.current?.lifecycleState === 'ACTIVE'
  && projects.current.capabilities.includes('project.alerts.read'))
const notices = computed(() => store.notifications.map((event) => ({
  id: event.eventId, title: `新告警：${alertTitle(event)}`,
  message: `来源：${alertSourceSummary(event)}。请在事件处置中查看证据并处理。`,
  tone: 'info' as const,
})))
watch(() => [enabled.value, projects.epoch], () => {
  sync.stop()
  if (enabled.value) void sync.start()
}, { immediate: true })
onBeforeUnmount(() => sync.stop())
</script>

<template>
  <UiNoticeStack v-if="enabled && notices.length" class="project-alert-notices" :notices="notices" @dismiss="store.dismissNotification" />
</template>

<style scoped>
/* Persistent alerts occupy layout space, never cover titles or action notices. */
.project-alert-notices { position: static; width: auto; margin: 16px 28px 0; }
@media (max-width: 600px) { .project-alert-notices { margin: 16px 20px 0; } }
</style>
