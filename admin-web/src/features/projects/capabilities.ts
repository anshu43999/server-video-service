import { computed } from 'vue'
import { useProjectsStore } from '../../stores/projects'

/** UI affordances only. Every request is independently authorized by the server. */
export function useProjectCapabilities() {
  const projects = useProjectsStore()
  const can = (capability: string) => projects.phase === 'ready' && Boolean(projects.current?.capabilities.includes(capability))
  return {
    can,
    active: computed(() => projects.current?.lifecycleState === 'ACTIVE'),
    streams: computed(() => can('project.streams.manage')),
    dispose: computed(() => can('project.alerts.dispose')),
    exports: computed(() => can('project.exports.create')),
    rules: computed(() => can('project.rules.manage')),
    models: computed(() => can('project.models.assign')),
    settings: computed(() => can('project.settings.manage')),
    audit: computed(() => can('project.audit.read')),
  }
}
