// @vitest-environment happy-dom
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useProjectCapabilities } from '../src/features/projects/capabilities'
import { useProjectsStore } from '../src/stores/projects'
import { modelsApi } from '../src/features/models/api'
import { projectModelsApi } from '../src/features/models/projectApi'
import { projectScope } from '../src/api/projectScope'
import { projectNavigationItems } from '../src/app/router'
beforeEach(()=>setActivePinia(createPinia()))
afterEach(()=>{vi.unstubAllGlobals();projectScope.clear();projectScope.enabled=false})
it('reads capabilities rather than platform or legacy role, and fails closed while switching',()=>{
  const projects=useProjectsStore()
  projects.current={projectId:'a',lifecycleState:'ACTIVE',projectRole:'PROJECT_USER',capabilities:['project.read','project.streams.view','project.alerts.read','project.alerts.dispose']} as any
  projects.phase='ready'
  const caps=useProjectCapabilities()
  expect(caps.dispose.value).toBe(true);expect(caps.streams.value).toBe(false);expect(caps.models.value).toBe(false)
  const names=projectNavigationItems(projects.current!.capabilities,false).map(r=>r.name)
  expect(names).toContain('project-models');expect(names).toContain('rules');expect(names).toContain('project-diagnostics');expect(names).not.toContain('models');expect(names).not.toContain('diagnostics')
  projects.phase='choosing';expect(caps.dispose.value).toBe(false)
})
it('pins parameter operations and assignment approvals to a project, version and revision',async()=>{
  projectScope.enable();projectScope.enter('alpha')
  const fetch=vi.fn(async (_path:unknown,_options?:RequestInit)=>new Response('{}'));vi.stubGlobal('fetch',fetch)
  await modelsApi.parameters('helmet','server',undefined,'1.0')
  await modelsApi.resetParameters('helmet','server',3,'1.0')
  await projectModelsApi.save({modelId:'helmet',modelVersion:'1.0',target:'pc',parameterRevision:4,expectedRevision:2,enabled:true})
  expect(fetch.mock.calls[0]?.[0]).toBe('/aiyoloapi/projects/alpha/models/helmet/parameters?platform=server&version=1.0')
  expect(fetch.mock.calls[1]?.[0]).toBe('/aiyoloapi/projects/alpha/models/helmet/parameters?platform=server&version=1.0&expectedRevision=3')
  expect(fetch.mock.calls[2]?.[0]).toBe('/aiyoloapi/projects/alpha/model-assignments')
  expect(JSON.parse(String(fetch.mock.calls[2]?.[1]?.body))).toMatchObject({modelVersion:'1.0',target:'pc',parameterRevision:4,expectedRevision:2})
})
