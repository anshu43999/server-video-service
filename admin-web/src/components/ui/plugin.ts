import type { App } from 'vue'
import UiButton from './UiButton.vue'
import UiInput from './UiInput.vue'
import UiOption from './UiOption.vue'
import UiProgress from './UiProgress.vue'
import UiSelect from './UiSelect.vue'
import UiTag from './UiTag.vue'
import UiCollapse from './UiCollapse.vue'
import UiTabs from './UiTabs.vue'
import UiPagination from './UiPagination.vue'

export function installUiComponents(app: App) {
  app.component('UiButton', UiButton)
  app.component('UiInput', UiInput)
  app.component('UiOption', UiOption)
  app.component('UiProgress', UiProgress)
  app.component('UiSelect', UiSelect)
  app.component('UiTag', UiTag)
  app.component('UiCollapse', UiCollapse)
  app.component('UiTabs', UiTabs)
  app.component('UiPagination', UiPagination)
}
