# M27-T07 转换器 Ultralytics 8.4.123 应急回退

日期：2026-11-10。M27-T07完成本地修复候选；用户随后明确批准本次降级相关改动提交、推送、构建及镜像验证，由M27-T08执行。生产切换和模型分发仍须另行授权。

## 范围与原因

M27-T06 已在相同 PT / 校准输入下证明：本地 8.4.123 生成正常模型，8.4.138 可触发 litert-torch 0.9.3 常量地址缓存复用。8.4.138 加常量存储保活也能恢复正常，但本次按用户优先修复线上故障的要求，选择**转换器专用版本回退**，不把诊断 monkey patch 直接用于生产。

回退是已验证模型/环境的规避措施，不声明修掉 litert-torch 底层缺陷，也不保证所有模型都正确。无需修改手机协议、阈值、类别开关、签名和授权。主视频服务继续使用 8.4.138。

## 实现

- 新增 constraints-converter.txt：Ultralytics=8.4.123；Torch=2.12.0+cpu、TorchVision=0.27.0+cpu 保持原镜像约束；LiteRT链保持0.9.3 / 2.1.6 / 0.8.0 / 0.3.1。
- Dockerfile.converter 将该文件复制为镜像内 /app/constraints-cpu.txt。这样 requirements-cpu.txt 的嵌套 -c 和 PIP_CONSTRAINT 同时读取同一份转换器约束，避免与仓库主服务8.4.138约束冲突。
- 原 constraints-cpu.txt、Dockerfile、requirements-yolo.txt 不变，不连带降级服务端视频推理。
- 构建继续执行 pip check 和 CPU/NMS 检查，新增 check_converter_runtime.py 对关键包进行精确版本核验。配置漂移/缺包时构建失败。
- 没有修改共享WSL/Windows虚拟环境，没有改转换执行算法；隔离测试包使用 evidence/M27 下的尝试目录或WSL独立临时目录，不作为发布输入。

## 本地验证及限制

初始本地回归：Python3.12，Torch2.12.1+cpu / TorchVision0.27.1+cpu；Ultralytics8.4.123。3次独立进程调用真实 conversion_worker.execute('mobile')，不启动服务、不写registry、不签名/重发。

3次模型图均与用户正常TFLite逐字节一致。5张业务图片（000054/000000/000012/000013/000015），两种delegate模式、3个新候选，共30组原始输出对照全部与正常基线一致。正常基线不是标注真值，结果不是mAP或业务精度验收。异常原文件在这些图片的default模式下均为0个NMS检测。

每次本地转换约12.7–15.5秒，子进程峰值RSS约1,731–1,752MiB；RSS不是容器峰值、并发总量或生产内存容量结论。图片解码和预处理沿用M27-T06诊断工具。测试阻断子进程socket，并跳过不影响校准像素的字体下载检查；未给转换器加任何权重保活补丁。

证据：evidence/M27/T07-20261110-real-rollback-01/acceptance.json。

目标核心依赖补测已通过：Torch2.12.0+cpu / TorchVision0.27.0+cpu、Ultralytics8.4.123及四项LiteRT依赖精确匹配，三次新进程导出和五图30组对照同样全部恢复正常基线。两套环境累计六次导出、60组输出对照通过。补测证据：evidence/M27/T07-20261110-target-rollback-02/acceptance.json。

补测实际Python仍为3.12.3，生产镜像 python:3.11 / Debian及完整依赖仍需从批准提交构建后进行容器内实际验收；本地成功不是生产整镜像验收。

## 最小提交范围（用户已批准）

生产必需4个文件：

1. .dockerignore
2. Dockerfile.converter
3. constraints-converter.txt
4. tools/check_converter_runtime.py

配套测试/说明：tests/test_converter_rollback.py、tests/test_docker_deployment.py、tools/accept_converter_rollback.py、tools/compare_mobile_model_outputs.py（M27-T06已有未跟踪依赖）、本文。

Harness任务记录/状态另按M27-T07增量审核；不得把当前整个脏工作区一次提交。现有worker、后台、App升级及其他任务改动不属于本次降级。当前worker.execute函数AST与HEAD一致，现有worker未提交差异位于环境能力检查，不需要为降级强行带入。

本次提交包含上述9个文件及受控构建入口tools/build_converter_release.sh；该入口拒绝脏检出、SHA不符和覆盖旧镜像标签，只构建转换器。Harness状态含其他任务未提交变更，因此保持本地，不整文件带入。镜像验收使用已提交的验收工具，显式指定/app/tools/conversion_worker.py，并在运行前要求与干净检出的worker逐字节一致；不把宿主机worker挂载覆盖镜像。

模型权重、校准复制件、下载包、运行日志、密钥和整个evidence运行目录不加入产品镜像或Git提交。正常hash/异常hash和测试摘要保留在文档/验收记录。

## 受控发布步骤（尚未执行）

1. 用户批准上述提交范围；审查实际diff并提交、推送，登记完整SHA。不要自行把构建授权当生产部署授权。
2. 开发构建服务器检查已有改动，再同步已推送SHA，使用干净检出及其中的Dockerfile.converter构建**新标签**。不覆盖旧标签，不传未提交补丁、不在容器内pip降级。
3. 镜像内记录Python、全部关键依赖和实际导入版本；执行CPU检查、精确版本检查、pip check，以及隔离真实PT重复转换和多图对照。不得把本地成功替代镜像实测。
4. 保存提交SHA、镜像ID/registry digest、完整tar SHA256和配置版本；资源容量未测或用户豁免要单独记录。
5. 获批后仅切换转换服务。先处理/等待转换队列，保留转换数据卷、校准卷和原配置；旧实现会把重启时running任务重新排队，不承诺无中断或不重跑。禁止双实例同时处理同一份任务目录。
6. 用原PT生成**新版本/新产物**，核验分数、hash、Manifest、签名及正常下载链路，再按既有审批/授权流程交付手机。保留旧异常模型和证据，不静默覆盖旧hash或同版本缓存。
7. 手机确认获得新hash后，按获批参数做真实识别验收；旧TFLite不会因转换器降级而自动修复。

## 失败处置

新镜像版本检查、真实转换或输出对照失败时停止推广，不降低置信度掩盖问题。不修改数据库、不自动迁移、不清任务/模型卷。

保留原镜像可用于服务可用性回退，但原转换链可能继续生成异常模型，不能把回退旧镜像等同正确性恢复。遇到异常先停止新增转换/发布并保存证据；生产动作和模型撤回/重发均按授权执行。

未来永久修复另立任务处理常量缓存生命周期/内容键，增加多模型、并发和完整精度回归。本次不扩大为该修复。
