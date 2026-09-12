# 管理后台输出与诊断通道

管理页的视频流详情现在读取 `GET /api/streams/{stream_id}/playback`，展示 WHEP 主播放地址、LL-HLS 回退地址、RTSP 诊断地址和 `publish_state`。WHEP/LL-HLS 是生产播放入口；RTSP 仅供 VLC/ffprobe 诊断。

预览区域保留 MJPEG 与 WebSocket JPEG，用于检查输入和服务状态，页面明确标注“诊断预览”，不将其作为生产低延迟播放协议。

检测结果通过独立的 `WS /api/streams/{stream_id}/detections` 旁路更新，视频订阅断开不会阻止元数据接收。YOLO 关闭或 Live API 不可用时，页面显示等待/空结果而不伪造检测数据；Demo 模式仍保留原型 Mock 数据。
