"""
ui/preview_canvas.py
Right-side image preview panel.
"""

from __future__ import annotations

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


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
        self._image_label.setStyleSheet("background:#0d0d1a; border-radius:8px; color:#555;")
        self._image_label.setText("Upload an image to begin")
        self._image_label.setFont(QFont("Segoe UI", 11))
        self._image_label.setMinimumSize(400, 250)
        layout.addWidget(self._image_label, stretch=1)

        self._current_bgr: np.ndarray | None = None
        self._grid_cols = 0
        self._grid_rows = 0
        self._show_grid = False

    def show_image(self, image_bgr: np.ndarray, title: str = "Image Preview"):
        self._current_bgr = image_bgr
        self._title.setText(title)
        self._render(image_bgr)

    def set_grid_overlay(self, n_cols: int, n_rows: int, visible: bool):
        self._grid_cols = max(0, int(n_cols))
        self._grid_rows = max(0, int(n_rows))
        self._show_grid = bool(visible)
        if self._current_bgr is not None:
            self._render(self._current_bgr)

    def clear(self):
        self._current_bgr = None
        self._image_label.setPixmap(QPixmap())
        self._image_label.setText("Upload an image to begin")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_bgr is not None:
            self._render(self._current_bgr)

    def _render(self, image_bgr: np.ndarray):
        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)

        max_w = max(self._image_label.width() - 4, 100)
        max_h = max(self._image_label.height() - 4, 100)
        pix = pix.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        if self._show_grid and self._grid_cols > 0 and self._grid_rows > 0:
            painter = QPainter(pix)
            pen = QPen(Qt.white)
            pen.setWidth(1)
            painter.setPen(pen)
            pw, ph = pix.width(), pix.height()
            for c in range(1, self._grid_cols):
                x = round(c * pw / self._grid_cols)
                painter.drawLine(x, 0, x, ph)
            for r in range(1, self._grid_rows):
                y = round(r * ph / self._grid_rows)
                painter.drawLine(0, y, pw, y)
            painter.end()

        self._image_label.setPixmap(pix)
        self._image_label.setText("")
