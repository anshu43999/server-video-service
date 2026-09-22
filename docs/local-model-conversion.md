# 本机模型上传与异步转换

2026-09-08，M26。管理后台的“模型资产 → 上传与模型处理”提供真实上传与转换。

COCO 仅用作用户功能测试模型，不代表业务精度。训练好的 `.pt` 在服务端虚拟环境中完成 CPU 试推理后直接登记；移动端使用单独导出的 `.tflite`。移动端转换失败不会撤回已经验证通过的 PT，也不会改变已有视频流绑定。

## 使用步骤

1. 启动服务并登录管理后台，进入“模型资产 → 上传与模型处理”。生产环境使用登录后签发的动态 Session；仅在 `DEPLOYMENT_ENV=development` 的本机调试中可配置 `ADMIN_TOKEN` 使用静态便捷鉴权。
2. 本机开发环境可选择 WSL 或 local，并填写对应 Python **绝对路径**，不需要手动 activate。Docker 生产环境不填写 WSL 发行版或宿主机 Python 路径；统一选择后台保存的 remote 配置，由 Compose 内部的 `model-converter` 容器执行转换。
3. 保存本机开发配置后点击“检测已保存环境”。系统会先同步探测 Python 解释器，探测失败时不会创建任务；探测通过后才排队做依赖检测。Docker 生产环境由容器健康检查和远程转换接口负责接线，不执行服务器宿主机 WSL 探测。依赖检测成功不代表某个业务模型必然转换成功；实际模型仍需独立导出与试推理。
4. 上传 Ultralytics 常规目标检测 PT，填写名称、版本、场景与用途。当前不支持分类、分割、姿态和端到端/NMS 内置检测模型。每次上传创建独立模型 ID；名称、版本与两端原始标签保持一致。
5. PT 验证任务通过后，目录显示模型，按流绑定下拉框可以选择它。可设为**新流默认模型**，已有流不自动切换。
6. 点击任务上的“生成移动端模型”，或者在配置中开启自动转换。第一版采用已验证的 INT8 导出链，输入支持 640、416、320。已上传版本的输入尺寸固定，修改默认尺寸只影响新上传。
7. INT8 必须选择校准集档案。`coco8-dev` 在生产转换镜像中对应真实 Ultralytics COCO8（8 张图片和 YOLO 标签），不依赖首次下载；它只验证转换链路，不代表业务数据分布。业务模型应在后台上传包含代表性图片的 ZIP，系统生成 YAML、版本和内容哈希。任务只保存校准集 ID 与不可变快照，不接受任意服务器路径。
8. 转换完成后验证实际 TFLite 输入、输出和一次预热，再登记 Android 产物与 Manifest。任务失败可查看日志并按当前配置重试。已发布版本不允许覆盖不同内容，应重新上传新版本。

上传过程显示真实的已上传字节百分比。上传完成后，后台任务列表每 4 秒刷新一次：排队任务显示队列位置和等待时长；本地、WSL 与远程任务显示当前阶段、最近活动、已运行时长和状态。导出器无法提供可靠百分比时使用流动的“不确定进度”提示，不伪造数值；远程服务能提供真实上传/下载百分比时才显示具体百分比。

## 任务与进程

配置与 SQLite 任务数据库位于 `models/local-conversion/`，已忽略 Git。每次执行使用独立目录；不手工修改任务数据库或删除正在使用的产物。为保持目录与模型注册表同一文件系统，第一版工作目录由服务端固定，页面只读展示。

只有一个工作线程执行任务，并有进程目录锁；以单 ASGI worker 启动。排队任务保留到重启后，执行中任务在重启后标记 `interrupted`，需显式重试。不要在模型转换中启用开发热重载。WSL 内部的监督进程对导出子进程组执行超时和取消，常规服务退出会等待取消。每次重试使用新目录，旧导出进程不能覆盖重试产物。

后台通过固定脚本 `tools/conversion_worker.py` 和参数数组调用配置的 Python，不执行用户填写的 shell 命令。PT 校验使用后台自身的 Python；WSL 只负责移动端转换。转换进程与在线推理分开，但仍共享机器 CPU、内存，初期串行执行，不代表资源完全隔离。

上传使用原始二进制流，不需要新增 multipart 依赖；单次上限 512 MiB，最多一个上传，上传时保留 128 MiB 磁盘余量。只允许可信管理员上传：PyTorch PT 权重加载不是处理不可信文件的安全沙箱。开启网络部署前应配置已有管理员鉴权。

## API

以下接口均要求管理员权限（开发环境未配置令牌时沿用项目兼容模式）：

| 方法与路径 | 功能 |
|---|---|
| GET /api/conversion/config | 配置、工作目录与能力 |
| PUT /api/conversion/config | 保存执行方式、发行版、Python、默认校准集、输入尺寸、超时和自动转换 |
| GET/POST /api/conversion/calibration-datasets | 列出校准集或上传图片 ZIP |
| GET/DELETE /api/conversion/calibration-datasets/{id} | 查看或安全删除未被引用的校准集版本 |
| POST /api/conversion/check | 返回 202 与环境检测任务 |
| POST /api/conversion/uploads?filename=best.pt&name=模型&version=1.0.0&scenario=场景&purpose=development | 二进制 PT 上传，返回 202 与 PT 验证任务 |
| POST /api/conversion/uploads/{upload_id}/mobile?calibrationDatasetId={id} | 使用指定校准集创建移动端转换任务 |
| GET /api/conversion/jobs | 最近 100 个任务 |
| GET /api/conversion/jobs/{id} | 任务状态、结果与错误 |
| POST /api/conversion/jobs/{id}/retry | 失败/中断任务按当前配置重试 |
| GET /api/conversion/jobs/{id}/log | 当前尝试最近 32 KB 日志，仅管理员 |

执行方式支持 `wsl`、`local` 和 `remote`。remote 模式的 endpoint、令牌环境变量名、HTTP 开发开关、轮询间隔和本地复验方式可在同一后台页面配置；真实 Bearer 令牌只由服务进程环境提供，页面与配置 API 不接收令牌值。远程协议和部署约束见 `docs/remote-model-conversion.md`。

配置字段 `mode` 支持 `wsl`、`local` 和 `remote`。CentOS Docker 部署已提供独立 `model-converter` 容器；视频服务通过冻结的远程 HTTP 协议提交任务、轮询、下载并在自身容器中再次执行 LiteRT 张量复验。跨主机部署仍必须配置 HTTPS。

## 双端产物与当前边界

同一模型 ID、版本包含 `server-pt`、`android-int8` 和 `android-manifest` 产物。沿用 `/api/models` 目录、详情与下载 API，并返回 `serverReady`、`androidReady` 和 `androidContract`。原始 PT 保持服务端主产物，移动端必须通过 `artifacts` 选择 `platform=android, format=tflite`，不能使用兼容别名误下载 PT。

`androidConverted` 表示转换文件通过电脑端 LiteRT 张量校验与预热并可供管理员诊断下载；`androidReady` 只有在同一产物生成有效 Ed25519 签名 Manifest 后才为 `true`，表示满足 App 安装的服务端前置条件。App 侧仍需完成真实下载、验签、预热和激活后才能用于端侧推理。

签名私钥不属于本机转换环境配置，也不应直接写入 `.env` 或转换配置。Docker 生产环境如需
App 动态安装模型，按 `docs/docker-deployment.md` 附录 C 将私钥挂载到 `video-service`，并
使用与 App 公钥匹配的 `keyId`。未配置签名时，PT 服务端推理和 TFLite 转换仍可完成，但
模型保持 `signatureStatus=unsigned`、`androidReady=false`，App 不得安装；COCO 仅作为内部
功能测试模型。
