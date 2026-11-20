# M33-T54 识别场景列表行内高频操作

## 结果

- 在每个场景表格行内按权限展示“编辑”“启用/停用”“批准/撤销批准”和“详情”，减少为了常规操作先打开详情的步骤。
- 成员、运行方案、参数查看、模型成员管理、参数重新批准仍在详情中；高风险软删除仍需影响预览及明确确认。
- 行内写操作复用既有场景修订/CAS、权限、busy锁、冲突后刷新核验和结果反馈；详情关闭后重读当前场景，不使用陈旧revision。
- 固定右操作列在窄屏保持可达，必要的数据列在表格区域横向查看；不产生页面级横向溢出。详情用键盘和Escape行为仍通过。

## 验证

- `npm run test`：25个文件、183项通过。
- `npm run build`：TypeScript与production build通过。
- 隔离 production Playwright 6项通过：行内编辑的键盘打开/关闭、详情只显示低频操作、长名称、1366×768及390×768布局，原创建/批准/重新批准/参数编辑/角色边界及场景输入组合回归。
- 固定布局测量：1366×768显示6条完整行，390×768显示5条完整行；页面宽度不溢出。
- Playwright用本地 Chrome和隔离临时服务；20条布局数据由只读route fixture提供，禁止写入业务API；其余流程使用本地临时模型文件和测试账号。
- Harness 34项通过，`validate`和`render`通过。

## 证据

- `admin-web/tests-e2e/scene-list.spec.ts`
- `admin-web/tests-e2e/scenes.spec.ts`
- `admin-web/tests-e2e/scene-inputs.spec.ts`
- `evidence/M33/M33-T54-browser.log`
- `evidence/M33/M33-T54-all-unit-tests.log`
- `evidence/M33/M33-T54-build.log`
- `evidence/M33/M33-T54-harness-tests.log`
- 本目录 `list-1366.png`、`list-390.png`、`long-name-390.png`、`details-1440.png`、`details-390.png`、`edited-1440.png`、`edited-390.png`。

## 遗留与状态

- 人工状态：**待人工复测**；未代填人工验收通过。
- 仅在本地Chrome与隔离fixture验证，其他浏览器和真实业务数据仍待人工检查。
- 未部署或重启业务服务，未修改业务数据，未提交或推送Git。
