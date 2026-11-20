# M32-T09 总览与数据看板迁移验收

日期：2026-10-09

## 交付

`/admin-next/overview` 和 `/admin-next/dashboard` 已从迁移占位页切换为 Vue 页面，并使用既有真实接口：`GET /dashboard/stats`、`GET /streams`、`GET /alerts` 与鉴权 MJPEG 诊断预览。各数据源独立呈现加载、空值和失败状态，不用 Mock 或旧周期结果回退。

- 总览提供周期指标、趋势、告警类别、实时流状态和最新告警；新建视频流进入实际创建表单，最新事件可按真实 eventId 打开告警详情。
- 看板补充服务器 CPU、系统/进程内存、磁盘、GPU、分级处置、复核用量/结论/失败原因与四路视频墙。空库显示零值或暂无数据；资源缺失显示不可用；没有对照数据的复核前后误报率明确显示暂无基线。
- 现场流状态以持久启用和 `runtime_available` 为边界，不用历史帧数把停用流标为在线；流地址不会回显。视频墙最多订阅前四路，停用/未运行流不发起诊断预览，画面使用 `object-fit: contain`。
- today、7d、30d 分别展示 2 小时、每日和 5 日分桶。快速切换会取消旧请求并拒绝迟到结果；10 秒轮询不会重建现有媒体连接，离页取消请求、停止轮询、终止 MJPEG reader 并释放 Blob URL。
- 大屏模式优先使用 Fullscreen API，拒绝时保留同等 CSS 大屏；Escape、退出按钮和离页均恢复页面滚动。焦点保持在大屏内，退出后返回触发按钮。
- 桌面、1920 大屏和 390px 窄屏已做浏览器几何重叠检查；同时修复关闭状态移动侧栏阴影残留。

实现：`admin-web/src/features/dashboard/`、`admin-web/src/app/router.ts`、`admin-web/src/features/{alerts,streams}/`、`admin-web/src/styles/base.css`。

## 自动化结果

| 验证 | 结果 |
|---|---|
| Vue / TypeScript 单元测试 | 12 个文件，62 项通过 |
| Playwright 全量 | 39 项通过，其中看板 7 项 |
| 服务端管理后台回归 `test_admin_*.py` | 77 项通过 |
| 统计服务 `test_dashboard_stats.py` | 3 项通过 |
| 正式构建 / 预览构建 | 通过 |

浏览器覆盖真实字段映射、零值/null、独立 503、恢复刷新、周期竞态、深链、停用流、四路上限、媒体轮询复用、离页释放、全屏拒绝/Escape、桌面/窄屏/大屏无溢出和无重叠。统计 API 单测校验范围与必要字段，拒绝不完整或非有限数值。

视觉证据：`M32-T09-dashboard-desktop.png`、`M32-T09-dashboard-screen.png`、`M32-T09-dashboard-mobile.png`、`M32-T09-overview-empty.png`。

## 验收边界

视频墙使用现有同源鉴权 MJPEG 诊断通道；生产 WHEP/LL-HLS 播放能力仍由视频流页面按既有协议呈现。本任务不增加统计维度、服务器分页、多模型编排或复核对照基线。M32-T10 最终入口切换、回退演练及功能对等总验收尚待执行，默认生产后台仍保持旧版。
