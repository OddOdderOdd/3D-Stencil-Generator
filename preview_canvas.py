"""
ui/preview_canvas.py
Right-side image preview panel.
Shows the original image, or the quantised version when preview is active.
"""

from __future__ import annotations

import cv2
import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QImage, QFont


class PreviewCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._title = QLabel("Image Preview")
        self._title.setStyleSheet("color:#a0c4ff; font-weight:bold; font-size:12px;")
        layout.addWidget(self._title)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setStyleSheet(
            "background:#0d0d1a; border-radius:8px; color:#555;"
        )
        self._image_label.setText("Upload an image to begin")
        self._image_label.setFont(QFont("Segoe UI", 11))
        self._image_label.setMinimumSize(400, 250)
        layout.addWidget(self._image_label, stretch=1)

        self._current_bgr: np.ndarray | None = None

    # ── Public ────────────────────────────────────────────────────────────────

    def show_image(self, image_bgr: np.ndarray, title: str = "Image Preview"):
        """Display a BGR numpy image, scaled to fit the widget."""
        self._current_bgr = image_bgr
        self._title.setText(title)
        self._render(image_bgr)

    def clear(self):
        self._current_bgr = None
        self._image_label.setPixmap(QPixmap())
        self._image_label.setText("Upload an image to begin")

    # ── Resize event ─────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_bgr is not None:
            self._render(self._current_bgr)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _render(self, image_bgr: np.ndarray):
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)

        max_w = max(self._image_label.width()  - 4, 100)
        max_h = max(self._image_label.height() - 4, 100)
        pix = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._image_label.setPixmap(pix)
        self._image_label.setText("")
