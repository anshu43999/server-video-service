# 管理后台 UI 组件库规范

## 选型与版本

管理后台统一使用 Element Plus `2.14.7`，版本在 `admin-web/package.json` 和 `package-lock.json` 中精确锁定。它与现有 Vue 3、TypeScript、Vite 技术栈直接兼容，中文后台控件完整，表单、表格、弹窗和无障碍基础能力成熟。

Element Plus 不是业务页面的直接依赖。项目以 `admin-web/src/components/ui/` 作为稳定适配层，业务页面只使用 `UiButton`、`UiInput`、`UiSelect`、`UiTag`、`UiDialog`、`UiConfirmDialog`、`UiDataTable`、`UiStatePanel` 和 `UiNoticeStack`。这样可以集中处理主题、交互兼容和未来组件库升级。

## 组件边界

| 项目组件 | 底层实现 | 约定 |
|---|---|---|
| `UiButton` | `ElButton` | 统一 `button/submit/reset`、loading、disabled；图标继续使用 Lucide |
| `UiInput` | `ElInput` / `ElInputNumber` / `ElSwitch` / `ElUpload` | 文本、密码、搜索、文本域、数字、开关和文件选择统一；兼容 label、键盘和自动化 |
| `UiSelect` / `UiOption` | `ElSelect` / `ElOption` | 下拉和选项不保留原生兼容分支；同时兼容 `v-model` 与受控 `:value` |
| `UiTag` | `ElTag` | 用于通用状态、用途和分类标签；告警严重度等领域状态可保留专用样式 |
| `UiDialog` | `ElDialog` | 普通编辑和详情弹窗，统一遮罩、Esc、滚动和窄屏尺寸 |
| `UiConfirmDialog` | `ElDialog` | 危险或需要明确授权的动作；使用具名 `alertdialog`，取消优先聚焦，busy 时不可关闭 |
| `UiDataTable` | `ElTable` / `ElTableColumn` | 通用结构化数据表；复杂业务工作台可保留专用列表布局 |
| `UiProgress` | `ElProgress` | 支持真实百分比与不确定进度，不用 `0%` 冒充未知状态 |
| `UiTabs` / `UiCollapse` / `UiPagination` | `ElTabs` / `ElCollapse` / `ElPagination` | 统一页签、折叠面板和分页交互 |
| `UiStatePanel` | `ElSkeleton` / `ElEmpty` / `ElResult` | 统一 loading、empty、error 与重试，不伪造业务数据 |
| `UiNoticeStack` | `ElAlert` | 统一异步操作通知队列、关闭行为和 `aria-live` |

文件选择由 `ElUpload` 提供，`UiInput` 暴露 `clear()` 与受控文件注入能力；上传进度、取消、Cookie 与错误处理仍由项目 API Client 负责。视频、WebSocket、MJPEG 和下载行为不交给 UI 组件库。

## 使用规则

1. 业务页面禁止直接从 `element-plus` 导入组件；新增通用控件先扩展 `components/ui`。
2. 颜色、字体、间距、圆角和状态色来自 `styles/tokens.css`，Element Plus 变量映射集中在 `styles/element-plus.css`。
3. 控件文案和领域状态以服务端事实为准；组件库不能把失败、排队或未知状态显示为成功。
4. 图标统一使用 `@lucide/vue`，不在业务页面手写 SVG。
5. 新控件必须覆盖 disabled、loading、错误、键盘、窄屏和长中文文案；危险操作必须经过 `UiConfirmDialog`。

示例：

```vue
<label>
  模型名称
  <UiInput v-model="form.name" maxlength="100" />
</label>
<UiButton class="primary-button" :disabled="busy" :loading="busy">保存</UiButton>
```

## 主题与构建

主题保留现场巡检后台的绿色主色、克制的工业运维密度和清晰状态层级，不使用 Element Plus 默认蓝色视觉。`ElConfigProvider` 在应用根部提供中文 locale；组件采用显式导入，不执行 `app.use(ElementPlus)` 全量注册。

当前仍加载 Element Plus 完整 Theme Chalk CSS，以降低首次统一控件时的样式缺失风险；样式约 422 KB（gzip 约 60 KB）。Element Plus 逻辑拆分为独立 vendor chunk，避免业务入口超过 500 KB；后续若继续优化 CSS，应逐组件引入样式并完整复跑九菜单、弹窗、表格和窄屏视觉回归。

## 迁移边界

- 已迁移九个菜单、登录页、模型子工作区及公共弹窗中的按钮、表单、选择、开关、文件、进度、页签、折叠、分页和反馈控件。
- 业务源码不保留原生 `select`、`option`、`input`、`textarea`、`progress`、`button`、`details`、`summary` 或 `dialog` 控件实现；无障碍语义由 Element Plus 组件输出。
- 告警列表、视频工作台和数据看板的专用布局不是通用表格替换目标。
- 本轮不改变 API、鉴权、上传、媒体、WebSocket、规则能力或多模型推理契约。
