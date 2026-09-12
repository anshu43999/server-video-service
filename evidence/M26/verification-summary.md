# M26 功能验证记录

日期：2026-09-08。仅验证模型上传、处理与分发功能；不验证业务识别精度或 App 设备安装。

## 真实环境与结果

- 后台：Windows Python 3.13，Ultralytics 8.4.138；PT 使用后台自身环境完成试推理。
- 移动端导出：现有 WSL2 Ubuntu，Python 3.12.3、Ultralytics 8.4.123、torch 2.12.1+cpu、litert-torch 0.9.3、ai-edge-litert 2.1.6、ai-edge-quantizer 0.8.0、litert-converter 0.3.1。
- 经真实 HTTP 上传项目已有 COCO PT，模型 ID `uploaded-02f1f4d17030499281daa395652e2924`，版本 `2026.09.08`，保留 80 类原始标签。
- PT 验证任务 `14ffe170768545a5a38aeca7ce13723a` 完成。
- 移动端任务 `c571978fef8b49769da7251d77215e7c` 完成；总任务时间 27.44 秒，其中导出器报告 14.9 秒。640 INT8 TFLite 为 3,085,717 字节，实际张量验证与预热通过。
- PT、TFLite、Manifest 经真实下载 API 获取，大小与 SHA-256 全部匹配；详情见 `real-conversion.json`。
- 创建独立验证流，按流绑定上传模型，通过 WebSocket 输入本地 Ultralytics bus.jpg，结构化检测旁路返回 5 个目标（bus 与 person）；随后删除本次临时验证流，不改其他视频流或新流默认模型。
- 转换设置已保存在忽略目录的本机配置中：WSL Ubuntu、原有虚拟环境、640、coco8.yaml、1800 秒，自动转换默认关闭。

## 页面验证

- 浏览器验证 Demo 状态下写操作禁用、连接真实服务、保存配置、环境检测排队、失败任务重试成功、已完成双端任务展示。
- 初次后台在 Codex 沙箱中执行 WSL 失败；保留失败任务，改为沙箱外本机验证服务后，该任务在页面重试成功（第 2 次）。这不是虚拟环境缺失。
- 桌面默认视口和 390×844 窄屏检查通过；新增处理面板窄屏宽度与 scrollWidth 均为 343px，无横向溢出。控制台没有 JavaScript error。
- Live 列表不使用 Mock 空目录回退，占位模型不允许激活或绑定。轮询仅在状态变化时更新任务 DOM，避免干扰操作焦点。

## 自动化验证

- 新增转换执行器与接口测试 14 项均通过，覆盖配置、任务快照、队列、超时、停止取消、目录互斥、重启恢复、上传鉴权、大小/格式限制、损坏 PT、哈希变化、占位模型拒绝、双端登记、转换失败与重试。
- 完整服务端测试 301 项：299 通过，2 项既有失败，0 error、0 skip。原始报告见 `server-regression.json` 与 `.log`。
- 既有失败 1：`test_admin_page_does_not_render_registry_paths_or_tokens` 禁止脚本文本包含 `X-Admin-Token`，与此前已有的 AI 复核鉴权请求头冲突。本次未修改 `app/static/app.js`。
- 既有失败 2：`test_compose_runs_pinned_mediamtx_with_restart_and_healthcheck` 要求 `service_healthy`，而现有 compose 明确采用 `service_started` 配合 publisher 重连。本次未修改 compose。
- 首轮全量测试与真实验证服务并行，触发转换目录互斥而产生启动错误；已停止验证服务后独立重跑，最终结果为上述 301 项、0 error。互斥错误不被当作产品通过证据。
- Harness 单元测试 30 项全部通过；node --check 两个前端脚本、git diff --check 与 Harness validate 通过。

## 剩余边界

App 真实下载安装和 Manifest 签名协议尚未接通；远程 HTTP 转换服务未实现；新增模型均非正式发布资格。自定义 PT 的类别、导出能力、校准集效果和目标 Android 设备仍需分别验收。以上不由 COCO 功能测试替代。
