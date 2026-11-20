# M40-T01 / Android M109-T01 验证（2026-10-23）

实现契约：`docs/evidence-display-overlay-v1.md`。仅新数据，不回填历史；框、标签与置信度来自证据捕获帧，不复用后续最新检测。PC EvidenceImage 使用现有视觉风格局部叠加，不修改媒体内容和业务流程。

| 检查 | 结果 | 证据 |
|---|---|---|
| `npm run test -- --reporter=dot tests/evidence-overlay.test.ts tests/alerts.test.ts tests/alert-sync.test.ts` | 24 项通过（3 文件） | 对应测试源与本次执行输出 |
| `npm run build`（含 vue-tsc） | 通过，3606 modules | `admin-web/dist/` 与本次执行输出 |
| `npm run test:e2e:production -- tests-e2e/alerts.spec.ts --grep 'new evidence overlay'` | 2 项通过 | `M40-browser.log`、`M40/display-{landscape,portrait}-{desktop,narrow}.png` |
| `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_analysis*.py' -v` | 22 项通过 | `M40-analysis-tests.log` |
| `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_mobile_alert_ingest.py' -v` | 21 项通过 | `M40-ingest-tests.log` |
| `python -m unittest discover -s harness/tests -p 'test_*.py'` | 34 项通过，validate 通过 | `M40-harness-tests.log` |
| Android JVM / API27 / 构建 / Lint | 1060 JVM + 3 API27 通过；Lint 0 errors、371 warnings、1 hint | `../mobile-app/harness/evidence/M109-validation.md` 与关联日志 |

浏览器使用已有 `C:/Program Files/Google/Chrome/Application/chrome.exe`，production 资产通过本地隔离 FastAPI 服务加载；身份、事件和媒体由浏览器路由提供可重复夹具，不访问生产账号/事件。横图使用原有 PNG，竖图仅在测试中旋转该夹具。测试逐项检查实际图片留白后框的几何坐标（误差小于 1px）、resize 后重算、已烘焙时无二次叠加。截图已人工视觉核对，属于绘制验证，不代表模型业务精度。

分析测试验证视频实际 overlay 开关与 bakedIn 一致、后续检测不改变证据快照、SQLite 重开后快照一致，以及 JPEG 字节与原 quality88 编码完全相同。上传测试验证 L1 幂等重放和分级上传后元数据保留、传给存储的媒体字节不变。测试进程显式清空 DATABASE_URL，用测试临时/内存库；对象存储边界使用测试替身，并非真实 MinIO 联调。媒体链路未更改，未启动 Docker 或操作远程 MinIO。

首次浏览器运行因 Playwright 默认的 Chromium 1248 未安装而失败；从既有项目验收材料确认本机 Chrome 路径后指定已有浏览器复验通过，无下载。原环境失败日志保留为 `M40-browser-initial-environment-failure.log`。Android 首次像素断言的抗锯齿诊断与复验见配套记录，未删除失败证据。

未部署服务器、未改历史数据、未提交或推送。需发布更新后的 App、PC 资产和服务端方能让后续新数据跨端带框。下载保持原文件，缺失/非法快照正常显示图片但不伪造框。
