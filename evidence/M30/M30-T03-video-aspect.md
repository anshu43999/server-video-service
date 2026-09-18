# M30-T03 视频预览比例验收

## 结果

管理后台的视频流详情预览和数据看板视频墙均使用 `object-fit: contain`。输入画面始终按原始宽高比缩放；容器比例不一致时显示深色留边，不拉伸、不裁切。

## 浏览器验证

验证脚本：`evidence/M30/verify_video_aspect.py`

| 视口 | 组件 | 容器尺寸 | 源图尺寸 | 计算样式 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 1440x900 | 视频流详情预览 | 609x250 | 1672x941 | `object-fit: contain` | 通过，左右留边且完整显示 |
| 390x844 | 数据看板视频墙 | 213x120 | 1672x941 | `object-fit: contain` | 通过，等比例完整显示 |

截图：

- `evidence/M30/M30-T03-desktop-streams.png`
- `evidence/M30/M30-T03-mobile-dashboard.png`

## 自动化验证

- `python -m unittest tests.test_admin_stream_live -v`：6 项通过。
- `python -m unittest tests.test_admin_dashboard_live -v`：4 项通过。
- 样式契约覆盖 `.stream-preview-image` 和 `.dashboard-stream-media img`，防止回退为 `cover`。

## 边界

本次只调整视频预览。告警证据缩略图继续使用 `cover`，因为缩略图允许填满裁切，不属于视频播放画面。
