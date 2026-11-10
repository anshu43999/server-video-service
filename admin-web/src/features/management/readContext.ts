import { projectScope } from '../../api/projectScope'
import { useProjectsStore } from '../../stores/projects'
import { useSessionStore } from '../../stores/session'

/** Navigation reuse is bounded by the authoritative identity/scope snapshot. */
export function useManagementReadContext(scope: 'platform' | 'project') {
  const session = useSessionStore(), projects = useProjectsStore()
  return () => JSON.stringify([session.phase, session.logoutUnconfirmed, session.user?.accountId,
    session.user?.role, session.user?.platformRole, session.user?.contractVersion,
    projectScope.enabled, projectScope.generation, projectScope.projectId, scope,
    scope === 'project' ? projects.current : projects.projects])
}
