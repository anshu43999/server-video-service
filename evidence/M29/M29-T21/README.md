# M29-T21 告警详情读取已保存建议

状态：待人工复测。未提交或推送 Git；未修改数据库或生成服务。

打开详情调用 GET latest，服务端明确无历史时展示生成入口；读取错误仅重新 GET。手动生成/重新生成仍 POST 并保留旧版本。历史按钮独立提供，加载/空态/错误分开；切项目/事件或关闭中止旧读取，同一事件刷新不重复读取。当前仍为服务端模拟建议。

已执行：
- Vitest `alert-advice-dialog.test.ts`：6/6，通过（含共享快照自动读取、POST=0、重新进入、同身份刷新、GET失败重试和迟到响应隔离）。首次运行因 beforeEach 返回 mock 被 Vitest 视为清理函数导致5失败，修正测试后6通过。
- `npm run build`：vue-tsc与生产构建通过，产物 index-DKI9O0W6.js。
- Playwright Chrome 生产资产 `alert-advice.spec.ts --grep 'production advice states'`：1440/390两宽度2/2通过，覆盖重新打开读取已有版本不POST、重新生成后历史2条、无匹配/部分结果/失败手动重试。截图由现有测试保存在 evidence/M41/M41-T09-advice-1440.png 和 -390.png。
- 后端真实 FastAPI/持久仓储回归 `test_alert_advice_generation_api.py`：6/6通过，覆盖latest/history/幂等/权限/跨项目/重启不变快照。
- Harness：34/34通过。沙箱下5项临时目录权限失败，提权重跑34通过；失败原因未隐瞒。

后续补充测试结果见 Harness 完成记录。跨端同一真实告警的人工体验待人工复测；另一端已打开详情不主动推送新建议，重新进入读取最新。
