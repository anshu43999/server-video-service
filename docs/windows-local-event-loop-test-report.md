# M05-T10 Windows 本地连接接收异常修复报告

## 范围与代码状态

- 日期：2026-11-23（Asia/Shanghai）。
- 基线提交：`fea0d48ee112e4ac2dd80ad80c80c05880a572cf`，修改未提交、未推送。
- 任务：M05-T10；只修改本地事件循环模块、run.py、Windows 启动脚本、
  Uvicorn 最低版本要求、对应测试/README 与 Harness 流程记录。
- 开始时已有 database.py/main.py 改动、模型注册表改动/模型删除、移动短视频相关
  未跟踪文件和历史测试材料；本任务未改动这些内容。

## 故障与修复

用户日志显示 Python 3.13 的 IocpProactor.accept 抛出 WinError 64，随后
Proactor 的 `_start_serving` 报告 `Accept failed on a socket`。
本机标准库该异常分支会关闭监听 socket。因此日志中仍有 HTTP 200，
不能证明后续新连接接收能力正常。具体触发断连的客户端或网络设备未知。

Windows 本地普通启动、Reload 启动及 run.py 使用显式 Selector 工厂。
非 Windows 的 run.py 保留 Uvicorn auto；不改系统 Python，不吞掉事件循环异常，
不调整生产容器入口，不绕过数据库/MinIO 启动校验。
requirements.txt 的 Uvicorn 下限提高至 0.36；启动脚本的已有依赖检查同时
检查 get_loop_factory，避免旧依赖标记跳过兼容检查。

## 环境与实际执行

- Windows，Python 3.13.15，Uvicorn 0.52.4，项目 `.venv`。
- 验证级别：L1 定向回归，外加本机随机端口的隔离网络故障测试。
- `python harness/harness.py validate`、`status`、`next`、`show M05-T10`：
  状态读取及校验成功，经 add/start 正式绑定任务。
- `.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_local_event_loop.py -v`
  最终 5 项通过，0 失败、0 跳过，耗时 0.340 秒。
  - 非 Windows 选择 auto。
  - run.py 参数与循环工厂正确，测试使用虚假配置且不导入业务 app。
  - PowerShell 两条启动分支均传递循环工厂，保留端口及 reload 参数。
  - 实际 Uvicorn Config 在 reload 开/关时均创建 Selector，非 Proactor。
  - 真实 loopback ASGI 测试：20 次不完整 HTTP 请求后 TCP RST，
    10 次 WebSocket 101 握手后 TCP RST，随后 5 次 HTTP 均返回 200/ok；
    事件循环未捕获异常计数为 0，退出后监听 socket 已关闭。
- PowerShell Parser.ParseFile 校验 start-server.ps1：通过。
- `git diff --check`：通过；只有现存换行格式提示。
- 通过 curl 只读核对 Uvicorn 官方 0.36.0 的 config.py：
  get_loop_factory 支持导入自定义工厂，符合所声明版本下限。
  首次沙箱请求 20 秒超时，授权重试后成功。未安装/升级任何依赖。

## 首轮失败与复测

首轮 4 项通过、1 项失败：测试 ASGI 夹具未声明 Content-Length，
HTTP chunked 响应不以裸 `ok` 结尾，导致正文断言失败；当时 HTTP 已返回 200。
为夹具加入正确长度后复测 5 项通过；测试 WebSocket 使用实际默认协议选择。
该失败属于测试夹具，不记录为业务修复前后性能对照。

## 未验证项与限制

- 未启动、重启、停止用户业务服务；隔离测试仅运行内存 ASGI 应用，
  使用 127.0.0.1 随机端口，未导入 app.main、读取业务配置或连接数据库/MinIO。
- 未运行真实 Reload 子进程、业务摄像机/告警链路或长稳测试；仅核对
  Reload 配置实际返回的事件循环和入口参数。
- 未在操作系统内稳定复现原始 WinError 64；测试验证的是替代循环在 TCP
  突断后的接收能力，不声称复现了原故障的全部网络条件。
- Windows Selector 最多 512 个套接字，包括客户端、输入和数据库连接；
  不支持 asyncio 子进程/管道。当前 app 目录未检出对应 asyncio
  子进程/管道 API 调用。未来引入时需重新评估；高并发部署继续采用 Linux。
- 原进程不会热切换事件循环，需用户自行停止并重新启动后生效。
- 本任务不修复先前远端 MinIO 不可达问题，连接状态未再次验证。

## 留存

本报告为唯一最终测试报告。测试输出直接读取，未创建原始日志、数据库、
截图或测试产物目录；测试 socket 和协程已结束。Harness 状态与完成记录保留。
