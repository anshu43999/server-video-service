export const fixtureProjectId = 'fixture-project'
export const fixtureUser = (role = 'admin') => ({ accountId: `fixture-${role}`, username: 'test-admin', role, platformRole: role === 'admin' ? 'PLATFORM_ADMIN' : 'NORMAL_USER', contractVersion: 'm33-v1' })
export const fixtureProject = { projectId: fixtureProjectId, projectCode: 'fixture', displayName: '验收项目', lifecycleState: 'ACTIVE', revision: 1, membershipRevision: null, projectRole: null, platformEntry: true, capabilities: ['project.read', 'project.streams.view', 'project.alerts.read', 'project.rules.manage', 'project.settings.manage', 'project.streams.manage', 'project.models.assign', 'project.alerts.dispose', 'project.exports.create', 'project.audit.read'] }
export const fixtureProjects = (role = 'admin') => ({ contractVersion: 'm33-v1', projects: role === 'admin' ? [fixtureProject] : [] })
export const unscopedPath = (path: string) => path.replace(`/projects/${fixtureProjectId}`, '')
