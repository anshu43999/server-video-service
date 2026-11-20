# M32-T06 视频流管理迁移验收

日期：2026-10-09

## 交付

`/admin-next/streams` 从迁移占位页面切换为 Vue 视频流工作台。布局沿用现有工业运维风格，使用工程内设计令牌；列表、现场画面、配置、诊断和检测结果分区，390px 窄屏按纵向工作流排列。

- 列表读取真实配置，支持名称/ID/来源类型搜索和运行状态筛选；空库与接口失败显式呈现，刷新失败时标记现有数据可能过期。
- 创建、显示名称、置信度、处理帧率、画面叠加、YOLO 开关、启停、模型绑定和确认删除使用既有 API。设置保存执行原生字段校验；操作失败保留服务端状态。
- 模型选项只使用后端 `serverBindable` 投影并按模型 ID 去重，不允许选择弃用或端侧模型；原始来源地址从响应映射中去除，创建字段按密码输入且关闭后清空；错误层补充 RTSP/RTSPS 凭据脱敏。
- 运行指标每 5 秒读取服务端；未保存设置不被刷新覆盖。切换流时取消旧播放请求并校验响应归属，阻止旧响应覆盖新详情。
- MJPEG 使用同源 Cookie 鉴权的可取消 fetch，解析后端 multipart 的 Content-Length 帧，保持 `object-fit: contain`。帧 Blob URL 在新图像加载后释放；切换流、停用、卸载释放流与 URL，重新启用和手动重连使用新连接参数。
- 检测 WebSocket 复用公共退避/终止状态处理；切换流、关闭 YOLO、离页释放连接。展示类别、置信度、跟踪主体和框坐标；WHEP/LL-HLS 状态与 RTSP 输出诊断地址保持原契约。

实现：`admin-web/src/features/streams/{types.ts,api.ts,mjpeg.ts,StreamsView.vue}`、`admin-web/src/app/router.ts`、`admin-web/src/api/errors.ts`。

## 自动化结果

| 验证 | 结果 |
|---|---|
| TypeScript / Vue 类型检查 | 通过，正式与预览构建均执行 |
| Vitest | 9 个文件，48 项通过 |
| Playwright 全量 | 14 项通过，其中视频流 7 项 |
| 服务端视频流回归 `test_stream*.py` | 32 项通过 |
| 输出协议 `test_output.py` | 3 项通过 |
| 检测 WebSocket `test_detections_ws.py` | 5 项通过 |
| 构建托管 `test_admin_frontend_hosting.py` | 7 项通过 |
| 正式构建 / 预览构建 | 通过 |

浏览器覆盖桌面与 390x844、创建/保存/模型绑定、三态列表、失败回滚、删除取消与确认、启停新连接、轮询保留未保存设置、延迟播放响应、预览失败重试、检测消息及离页关闭订阅。MJPEG 单测覆盖跨网络块解析、加载后释放旧帧、主动 abort、同源路径限制。

旧检测 WS 测试曾匿名订阅并启动本机历史流，导致鉴权失败和 RTSP 超时。测试现以独立内存流配置和临时账号会话执行；保留匿名拒绝与 4404 验证，没有改动服务端鉴权或业务接口。

## 真实 RTSP 验收

隔离链路：本机 `sucai1.mp4` → FFmpeg H.264 → MediaMTX `127.0.0.1:18556/probe` → 实际 FastAPI 流 API / OpenCV 拉流 → 浏览器 Vue 正式预览构建。

验收服务器只监听 `127.0.0.1:18086`，使用空临时模型目录和内存账号/配置，不读取项目 `.env`、不访问生产数据库。账号密码运行时随机生成且不记录。最终结果见 `M32-T06-real-rtsp.json`：

- 首帧解码为 1920x1080。
- 三次停用/启用均恢复画面与接收帧，取样计数 30、39、30；每次建立新预览连接。
- 参数保存值为 confidence=0.41、max_fps=12，与服务端一致。
- 离页后活动视频订阅归零；临时流经真实删除 API 删除；浏览器 pageerror 为 0。
- 最终截图已复查，现场画面正常显示；桌面与窄屏无横向溢出。

复现材料：`M32-T06-mediamtx.yml`、`M32-T06-probe-server.py`、`admin-web/scripts/probe-real-stream.mjs`。浏览器测试通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指向本机缓存 Chromium 1234。

## 验收边界

本轮真实 RTSP 验证使用原始帧，隔离环境没有安装业务模型或启用输出 MediaMTX 发布。真实 YOLO 推理、生产 WHEP/LL-HLS 性能与生产部署不是本次前端迁移的新能力声明；模型绑定与检测消息由既有服务端回归和浏览器契约验证。M32-T07 至 T10 尚待推进，默认后台仍为旧版，最终入口切换须完成全部功能对等验收。

视觉证据：`M32-T06-streams-desktop.png`、`M32-T06-streams-mobile.png`、`M32-T06-real-rtsp-desktop.png`。
