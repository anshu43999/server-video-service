"""检测叠加层（M08-T01）。

叠加只从结构化检测结果推导，且可整体关闭；关闭时输出原始帧，不做任何绘制。
标签用权重原始类名（ASCII），中文显示名属于 Manifest 映射层，不在这里渲染。
"""

from __future__ import annotations

import colorsys
from collections.abc import Iterable

import cv2

from .detection import Detection

# 黄金比例取色：类别 id 相邻时颜色也拉得开，且同一 id 每次都是同一个颜色。
GOLDEN_RATIO_CONJUGATE = 0.618033988749895
LABEL_FONT = cv2.FONT_HERSHEY_SIMPLEX
LABEL_SCALE = 0.5
LABEL_TEXT_COLOR = (0, 0, 0)


def class_color(class_id: int) -> tuple[int, int, int]:
    """按类别 id 生成稳定的 BGR 颜色。"""
    hue = (int(class_id) * GOLDEN_RATIO_CONJUGATE) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.85, 1.0)
    return (int(blue * 255), int(green * 255), int(red * 255))


def format_label(detection: Detection, show_confidence: bool = True) -> str:
    text = f"{detection.label} {detection.confidence:.2f}" if show_confidence else detection.label
    if detection.track_id is not None:
        text = f"#{detection.track_id} {text}"
    return text


def draw_overlay(
    frame,
    detections: Iterable[Detection],
    show_confidence: bool = True,
    thickness: int = 2,
):
    """在帧副本上按结构化结果画框与标签，返回新帧；传入的帧不被修改。"""
    if frame is None:
        raise ValueError("frame must not be None")
    canvas = frame.copy()
    height, width = canvas.shape[:2]
    for detection in detections:
        if detection.box is None:
            continue  # 分类型结果没有框，叠加层跳过而不是伪造一个框
        x1, y1, x2, y2 = detection.box.as_pixels(width, height)
        color = class_color(detection.class_id)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)
        text = format_label(detection, show_confidence)
        (text_width, text_height), baseline = cv2.getTextSize(text, LABEL_FONT, LABEL_SCALE, 1)
        top = max(0, y1 - text_height - baseline)
        cv2.rectangle(
            canvas,
            (x1, top),
            (min(width, x1 + text_width), min(height, top + text_height + baseline)),
            color,
            -1,
        )
        cv2.putText(
            canvas, text, (x1, top + text_height), LABEL_FONT, LABEL_SCALE, LABEL_TEXT_COLOR, 1, cv2.LINE_AA
        )
    return canvas
