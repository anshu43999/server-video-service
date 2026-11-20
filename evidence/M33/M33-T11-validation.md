# M33-T11 平台项目、账号与成员管理验收

- 日期：2026-10-12
- 范围：`server-video-service` / `admin-web`，不修改 Android 工程。
- 需求与操作说明：`docs/admin-project-management.md`。
- 完成记录：`harness/records/M33/M33-T11.md`。

## 交付与验收映射

| T11 要求 | 实现 | 实测依据 |
| --- | --- | --- |
| 项目创建编辑 | 必填名称、唯一代码、启用的初始负责人；版本保护编辑 | 真实浏览器 1440px/390px 全流程；后端管理 API |
| 停用、归档、恢复 | 状态对应入口、目标与影响确认；恢复走平台 API | 真实浏览器三种生命周期变更与恢复；停用维护/归档审计专项 |
| 账号创建启停 | 普通账号默认，可显式授予平台管理员；说明全项目影响 | 真实创建/停用/启用；最后管理员/负责人服务端回归 |
| 成员分配、启停移除、角色变更 | 平台选账号，负责人只添加已有账号 ID 的普通成员 | 真实平台与负责人会话；直接 API 提权拒绝；成员撤权立即生效 |
| 负责人移交 | 指定接收人、双方版本校验、原负责人降级；自己移交后清空旧界面 | 真实平台移交与负责人自身移交；事务/版本保护后端回归 |
| 审计查看 | 平台/项目隔离，元数据列表、游标分页、失败重试 | 内存和 SQLite API 测试、浏览器审计分页/失败恢复 |
| 并发与失败恢复 | 409/不确定写入禁止直接重放，保留非密码草稿，刷新后重新编辑 | 单元测试与真实并发版本冲突；503 注入与恢复 |
| 权限边界 | 导航和路由守卫，后端 capability，平台别名不放宽 ProjectScope | 普通用户/负责人 403、跨项目 404；归档成员管理 403 |
| 桌面、窄屏与键盘 | 延续绿色工业后台风格；响应式卡片，Enter 打开、Escape 取消 | 1440px/390px 截图与无溢出断言；既有导航回归 |

主要新增源码为 `admin-web/src/features/management/` 下的四个页面、API 适配、读写恢复组合函数和样式；路由及布局增加平台/项目管理入口。后端 `app/project_management.py` 增加平台项目别名与审计查询，`app/project_auth.py` 补内存平台进入审计读取。

## 测试结果

| 检查 | 结果 | 日志 |
| --- | --- | --- |
| 前端单元 | 14 文件、88 项通过（含 5 项新增管理隔离/恢复测试） | `T11-unit.log` |
| 正式构建与类型检查 | 通过 | `T11-build.log` |
| 预览构建与类型检查 | 通过 | `T11-preview-build.log` |
| 正式构建浏览器全量 | 60 项全部通过，含 6 项新增管理场景 | `T11-browser-regression.log` |
| 管理 API 专项 | 7 项通过，包含内存与 SQLite | `T11-management-api.log` |
| 后端全量 | 549 项：521 通过、28 条件跳过，0 失败/错误 | `T11-backend-regression.log` |
| Harness | 30 项通过；完成后 validate/render 校验 | `T11-harness.log` / 完成记录 |

`management.spec.ts` 的成功流程调用真实 Cookie 鉴权、项目/账号/成员/审计 API；浏览器服务器是隔离的内存 FastAPI 应用，不连接用户的运行服务或生产库。明确注入的 503 是错误恢复测试。既有其他业务回归仍大量使用 fixture，因此“60 项通过”不代表真实媒体、数据库生产部署或 Android 联合验收完成。

本轮测试发现并修复 SQLite 秒精度默认时间与绑定 datetime 格式不同导致审计游标重复翻页的问题；分页测试检查完整遍历、无重复和作用域约束。浏览器回归更新了新增平台导航后的旧数量预期，修正了审计文本断言的 innerText/textContent 空白差异，最终全量通过。

## 视觉证据

- `M33-T11-platform-1440.png` / `M33-T11-platform-390.png`：项目状态、管理操作与显式项目进入。
- `M33-T11-members-1440.png` / `M33-T11-members-390.png`：平台进入项目标识、角色、账号与成员状态、移交操作。
- `M33-T11-confirm-1440.png` / `M33-T11-confirm-390.png`：归档影响说明、目标与版本、取消和确认；截图关闭过渡动画以避免中间透明帧。
- 视觉补验日志：`T11-visual-regression.log`。

全量 60 项通过后仅调整了管理确认按钮的局部配色（深红底白字），并修正截图采集的动画时机；未修改业务逻辑。随后重新通过正式/预览构建及两种宽度的真实账号—项目—成员—生命周期完整流程，最终截图均按此次构建复核。

## 复现

在 `admin-web/`：

```powershell
npm run test -- --reporter=dot
npm run build
npm run build:preview
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE='C:/Program Files/Google/Chrome/Application/chrome.exe'
npm run test:e2e:production -- --workers=2
```

在服务端工程目录：

```powershell
$env:DATABASE_URL=''
$env:TEMP=(Resolve-Path -LiteralPath '.test-db').Path
$env:TMP=$env:TEMP
& './.venv/Scripts/python.exe' -m unittest discover -s tests -p 'test_*.py' -q
python -m unittest discover -s harness/tests -p 'test_*.py'
python harness/harness.py validate
python harness/harness.py render
```

## 边界与遗留风险

- 仅关闭 T11，未提前完成 T12 全业务能力矩阵、T13 报表导出/审计检索性能、T16 整体多角色验收或 T18 跨端联合验收。
- 审计目前只返回安全元数据、目标与版本，不返回原始 `changeSummary`。高级检索、详细安全变更展示、留存与大数据性能由 T13 承接；项目/账号列表仍是既有完整列表接口，未声明大规模目录已压测。
- 新审计 SQL 查询已在 SQLite 和隔离内存服务验证；本轮没有单独运行 PostgreSQL 外部实例验收。全量 28 项条件跳过不算通过。
- 服务端权限变更的前端清屏仍遵循 T10 的事件触发和 15 秒核验周期；服务端每次请求实时授权。取消请求不回滚服务器已提交的写入，必须核验后再操作。
- 已启用的维护/审计页不意味着停用/归档后的所有历史业务页已实现，其他页面继续遵循 T10 的保守暂停策略。
- 未部署、未执行生产迁移、未提交或推送 Git；保留原有未提交工作。构建/测试有既有 npm 配置、Starlette/Pydantic 弃用提示，未导致失败。
