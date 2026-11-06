---
major_task_id: M42
result: pending
owner: unassigned
accepted_at:
---

# M42 App升级发布服务、双来源托管与快速恢复验收

## 验收结论

待全部子任务完成后执行真实验收。本文件只登记验收范围，不表示功能已经交付。

## 验收范围

- `server-video-service` 提供 App 版本检查、下载地址、安装许可、回执、撤回和恢复策略接口；
- `admin-web` 仅向启用的平台管理员提供 App 版本管理、MinIO 上传、第三方公开 HTTPS 直链登记、发布、停止分发、兼容门禁、审计和快速回退；
- MinIO 与第三方公开 HTTPS 直链两条来源分别通过真实完整 APK 端到端验收；
- APK 版本、大小、SHA-256、applicationId、SDK/ABI 与生产签名身份由统一核验器从实际完整文件读取并校验；
- 服务端策略提交和设备恢复分别统计，公开外链的 APK 字节不由业务服务代理。

## 明确不包含

- 不包含差分升级、热修复、静默安装、MDM 或自动下载；
- 首阶段不要求第三方私有签名 URL、自动故障切源或复杂灰度；
- 不保存生产签名私钥、MinIO 密钥或第三方管理密钥到仓库、API 响应、日志或浏览器。

## 验收标准

- [ ] 只有 `PLATFORM_ADMIN` 能调用全部版本管理写接口；普通平台账号、项目负责人、项目用户、停用或已降权账号被服务端拒绝。
- [ ] MinIO 与第三方公开 HTTPS 直链均能登记、完整核验、发布、停止分发和供应更高 versionCode 恢复包。
- [ ] 发布记录与工件内容不可原地覆盖；版本码全局递增，来源修订、并发 CAS、幂等键及审计行为可验证。
- [ ] 公开外链由 App 直连，服务端只提供小体积策略和地址响应；外链失败不隐式回源业务容器或 MinIO。
- [ ] 100 稳定、101 问题、102 恢复演练区分策略止损与设备恢复，未联系设备或未启动新包不记成功。
- [ ] PostgreSQL、MinIO、HTTPS、管理后台构建、权限、故障恢复及 Android 双来源联调证据完整。

## 小任务完成记录

| ID | 小任务 | 状态 | 记录 |
|---|---|---|---|
| M42-T01 | 冻结App升级服务端契约与数据模型 | completed（契约/模型） | `harness/records/M42/M42-T01.md` |
| M42-T02 | 实现APK统一工件核验器 | completed（真实SDK/签名核验） | `harness/records/M42/M42-T02.md` |
| M42-T03 | 实现MinIO自有APK上传与不可变存储 | completed | `harness/records/M42/M42-T03.md` |
| M42-T04 | 实现第三方公开HTTPS直链登记与核验 | completed | `harness/records/M42/M42-T04.md` |
| M42-T05 | 实现版本发布策略、检查、地址与回执API | completed | `harness/records/M42/M42-T05.md` |
| M42-T06 | 实现平台管理员版本管理后台 | completed | `harness/records/M42/M42-T06.md` |
| M42-T07 | 实现停止分发、兼容门禁与快速回退 | completed | `harness/records/M42/M42-T07.md` |
| M42-T08 | 加固并发、审计、凭据与外链网络边界 | completed | `harness/records/M42/M42-T08.md` |
| M42-T09 | 完成双来源服务端与管理后台真实验收 | in_progress | `harness/records/M42/M42-T09.md` |
| M42-T10 | 完成Android双来源升级与恢复联合验收 | pending | `harness/records/M42/M42-T10.md` |

## 遗留风险

- T09 本地联合已覆盖真实数据库、MinIO、受控 HTTPS 源和无 API 拦截的生产构建浏览器；具体证据见 `harness/evidence/M42/T09-verification.md`。正式生产签名与设备安装尚未验收，M42 大任务保持 pending 验收结论。

- 正式域名、MinIO endpoint/bucket、第三方托管供应商、生产签名证书指纹和正式 APK 尚需实施时配置；这些材料缺失时不得将对应发布或联合验收标为通过。

