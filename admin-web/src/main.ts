import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { installUiComponents } from './components/ui/plugin'
import { installSessionGuard, router } from './app/router'
import { connectSessionToApi, useSessionStore } from './stores/session'
import { useProjectsStore } from './stores/projects'
import { projectScope } from './api/projectScope'
import { installProjectMonitor } from './app/projectMonitor'
import 'element-plus/dist/index.css'
import './styles/tokens.css'
import './styles/base.css'
import './styles/element-plus.css'
import './styles/projects.css'

async function bootstrap() {
  const app = createApp(App)
  const pinia = createPinia()
  app.use(pinia)
  installUiComponents(app)
  const session = useSessionStore(pinia)
  connectSessionToApi(session)
  projectScope.enable()
  const projects = useProjectsStore(pinia)
  installSessionGuard(router, session)
  await session.restore()
  app.use(router).mount('#app')
  installProjectMonitor(router, session, projects)
}

void bootstrap()
