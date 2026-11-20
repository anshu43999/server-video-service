# M36-T05 验证记录

日期：2026-10-19。交付位于 `admin-web/src/features/models`、`admin-web/src/features/scenes`、`admin-web/src/app/router.ts` 与 `app/conversion_api.py`，说明见 `docs/admin-project-scenes.md`。

## 交付

- 模型目录区分 PC-only、mobile-only、双端，按目标端显示独立就绪/发布状态；移动签名对 PC-only 显示不适用。
- PT 上传选择目标端；双端按重复参数提交。PC-only 转换任务不提供移动转换入口。精确版本发布提交 targets、licenseApproved 和原因。
- 新增项目场景列表、创建编辑、有序成员增删与上下移动、图片/视频适用性、single/sync/async 声明、启停、批准/撤销。
- project.read / project.scenes.manage / project.scenes.approve 控制页面与操作；普通用户不读取维护模型候选，不显示写入或批准按钮。
- CAS 冲突保留草稿并停止自动重放；刷新后恢复。界面明确说明多模型同步/异步执行器尚未实现。

## 实际测试

1. `npm run typecheck`：通过。
2. `npm run test`：17 files / 113 tests passed。
3. `npm run build`：通过，Vite production build 3601 modules，767ms。
4. 场景生产构建浏览器流程：2 passed，31.4 秒，覆盖 1440px / 390px、真实登录、项目权限、创建、两版本排序、批准、普通用户可见、撤销、成员移除、409 草稿保留、刷新恢复、Enter/Escape。
5. 模型目标端生产构建浏览器流程：1 passed，13.4 秒，覆盖 PC 独立发布请求和双端上传的重复 supportedTargets 参数。
6. `test_conversion_api.py`：20 tests passed，4.105 秒，覆盖 PC-only 跳过自动转换、mobile-only 与双端转换/发布等后端契约。
7. Harness 单测、validate/render 记录在任务完成记录中。

## 目视检查

- `M36-T05-scenes-1440.png`：桌面导航、项目上下文、场景状态和成员操作无溢出。
- `M36-T05-scenes-390.png`：窄屏按钮换行、成员列表、状态标签和操作按钮均可读，无横向溢出。

## 边界与风险

未执行真实模型推理、真实转换、Android 真机/模拟器或生产部署。多模型 sync/async 只保存声明，不执行编排；场景批准不会改变旧 assignment 和视频流。浏览器夹具使用合成 PT 与隔离内存存储，真实 PostgreSQL 和迁移回归由 M36-T03/T04 及后续 M36-T06 覆盖。
