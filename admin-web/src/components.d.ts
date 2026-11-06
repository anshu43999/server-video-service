import type UiButton from './components/ui/UiButton.vue'
import type UiInput from './components/ui/UiInput.vue'
import type UiOption from './components/ui/UiOption.vue'
import type UiProgress from './components/ui/UiProgress.vue'
import type UiSelect from './components/ui/UiSelect.vue'
import type UiTag from './components/ui/UiTag.vue'
import type UiCollapse from './components/ui/UiCollapse.vue'
import type UiTabs from './components/ui/UiTabs.vue'
import type UiPagination from './components/ui/UiPagination.vue'

declare module 'vue' {
  export interface GlobalComponents {
    UiButton: typeof UiButton
    UiInput: typeof UiInput
    UiOption: typeof UiOption
    UiProgress: typeof UiProgress
    UiSelect: typeof UiSelect
    UiTag: typeof UiTag
    UiCollapse: typeof UiCollapse
    UiTabs: typeof UiTabs
    UiPagination: typeof UiPagination
  }
}

export {}
