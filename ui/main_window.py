"""
ui/main_window.py
Root PyQt5 application window.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QTextEdit, QProgressBar, QLabel,
    QFileDialog, QMessageBox, QFrame,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from config import (
    DEFAULT_CANVAS_W_MM, DEFAULT_CANVAS_H_MM,
    DEFAULT_BED_W_MM, DEFAULT_BED_H_MM,
)
from core.quantizer import quantize
from core.tiler import compute_tile_grid
from ui.panels import ControlPanel
from ui.preview_canvas import PreviewCanvas
from ui.export_dialog import ExportDialog
from workers.generator_thread import GeneratorWorker
from export.guide_writer import PlateInfo


# ── Application stylesheet ────────────────────────────────────────────────────

DARK_QSS = """
QMainWindow, QDialog { background: #12121f; }
QWidget       { background: #12121f; color: #e0e0e0;
                font-family: 'Segoe UI', Arial, sans-serif; }
QGroupBox {
    border: 1px solid #2e2e4a; border-radius: 8px;
    margin-top: 10px; padding-top: 8px;
    font-weight: bold; color: #a0c4ff;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QPushButton {
    background: #1c2a4a; color: #e0e0e0;
    border: 1px solid #2e2e4a; border-radius: 6px; padding: 7px 14px;
}
QPushButton:hover   { background: #253560; border-color: #e94560; }
QPushButton:pressed { background: #e94560; color: #fff; }
QPushButton:disabled{ background: #1a1a2a; color: #555; border-color: #2a2a3a; }
QDoubleSpinBox, QSpinBox, QLineEdit {
    background: #1c1c30; border: 1px solid #2e2e4a;
    border-radius: 5px; padding: 4px 8px; color: #e0e0e0;
}
QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus { border-color: #e94560; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button {
    background: #253560; border: none; width: 18px;
}
QSlider::groove:horizontal {
    height: 6px; background: #2e2e4a; border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #e94560; width: 16px; height: 16px;
    margin: -5px 0; border-radius: 8px;
}
QSlider::sub-page:horizontal { background: #e94560; border-radius: 3px; }
QCheckBox { color: #e0e0e0; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 3px;
    border: 1px solid #555; background: #1c1c30;
}
QCheckBox::indicator:checked { background: #e94560; border-color: #e94560; }
QRadioButton { color: #e0e0e0; spacing: 8px; }
QRadioButton::indicator {
    width: 14px; height: 14px; border-radius: 7px;
    border: 1px solid #555; background: #1c1c30;
}
QRadioButton::indicator:checked { background: #e94560; border-color: #e94560; }
QTextEdit {
    background: #0a0a14; border: 1px solid #2e2e4a;
    border-radius: 6px; color: #7fff7f;
    font-family: 'Consolas', 'Courier New', monospace; font-size: 11px;
}
QProgressBar {
    background: #1c1c30; border-radius: 5px; height: 14px;
    border: 1px solid #2e2e4a; text-align: center; color: #fff;
}
QProgressBar::chunk { background: #e94560; border-radius: 5px; }
QSplitter::handle { background: #2e2e4a; }
QScrollBar:vertical {
    background: #1c1c30; width: 10px; border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #3a3a5a; border-radius: 5px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎨  3D Stencil Generator")
        self.setMinimumSize(1050, 680)
        self.setStyleSheet(DARK_QSS)

        self._image_path: str | None = None
        self._raw_image = None         # BGR ndarray
        self._worker: GeneratorWorker | None = None
        self._plates: list[PlateInfo] = []
        self._output_dir = str(Path.home() / "stencil_output")

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        # Left: control panel
        self._panel = ControlPanel()
        self._panel.upload_btn.clicked.connect(self._on_upload)
        self._panel.colors_changed.connect(self._on_colors_changed)
        self._panel.preview_requested.connect(self._on_preview)
        self._panel.generate_requested.connect(self._on_generate)
        self._panel.export_requested.connect(self._on_export)
        root.addWidget(self._panel)

        # Right: preview + log
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        splitter = QSplitter(Qt.Vertical)

        # Image preview
        self._preview = PreviewCanvas()
        splitter.addWidget(self._preview)

        # Log + progress
        log_frame = QFrame()
        log_frame.setStyleSheet(
            "background:#0d0d1a; border-radius:8px; border:1px solid #2e2e4a;"
        )
        lf = QVBoxLayout(log_frame)
        lf.setContentsMargins(8, 8, 8, 8)

        log_header = QHBoxLayout()
        log_lbl = QLabel("Processing Log")
        log_lbl.setStyleSheet("color:#a0c4ff; font-weight:bold;")
        self._progress = QProgressBar()
        self._progress.setValue(0)
        self._progress.setFixedHeight(15)
        log_header.addWidget(log_lbl)
        log_header.addWidget(self._progress)
        lf.addLayout(log_header)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("Log output will appear here…")
        self._log.setMinimumHeight(120)
        lf.addWidget(self._log)

        splitter.addWidget(log_frame)
        splitter.setSizes([420, 200])

        right_layout.addWidget(splitter)
        root.addWidget(right, stretch=1)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.webp)"
        )
        if not path:
            return

        img = cv2.imread(path)
        if img is None:
            QMessageBox.critical(self, "Load error", f"Cannot read image:\n{path}")
            return

        self._image_path = path
        self._raw_image  = img
        h, w = img.shape[:2]

        self._panel.set_image_info(os.path.basename(path), w, h)
        self._panel.generate_btn.setEnabled(True)
        self._panel.preview_btn.setEnabled(True)

        self._preview.show_image(img, "Original Image")
        self._on_preview()

    def _on_colors_changed(self, _n: int):
        if self._raw_image is not None:
            self._on_preview()

    def _on_preview(self):
        if self._raw_image is None:
            return
        n = self._panel.n_colors.value()
        qr = quantize(self._raw_image, n)
        self._preview.show_image(qr.quantized_image,
                                  f"Quantised Preview  ({n} colours)")
        self._panel.swatch_bar.set_colors(
            [tuple(c) for c in qr.centers_bgr.tolist()]
        )

    def _on_generate(self):
        if self._image_path is None:
            QMessageBox.warning(self, "No image", "Please upload an image first.")
            return

        self._log.clear()
        self._progress.setValue(0)
        self._plates.clear()
        self._panel.set_generating(True)
        self._panel.set_export_ready(False)

        params = self._panel.get_params()
        params["image_path"]  = self._image_path
        params["output_dir"]  = self._output_dir

        self._worker = GeneratorWorker(params)
        self._worker.progress.connect(self._progress.setValue)
        self._worker.log.connect(self._append_log)
        self._worker.plate_ready.connect(self._on_plate_ready)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_export(self):
        if not self._plates:
            QMessageBox.warning(self, "Nothing to export", "Generate stencils first.")
            return

        params = self._panel.get_params()
        grid = compute_tile_grid(
            params["canvas_w_mm"], params["canvas_h_mm"],
            params["bed_w_mm"],   params["bed_h_mm"],
        )

        dlg = ExportDialog(
            self._plates,
            self._output_dir,
            params["canvas_w_mm"], params["canvas_h_mm"],
            params["bed_w_mm"],    params["bed_h_mm"],
            params["n_colors"],
            grid.n_cols, grid.n_rows,
            parent=self,
        )
        dlg.exec_()

    # ── Worker callbacks ──────────────────────────────────────────────────────

    def _append_log(self, msg: str):
        self._log.append(msg)
        # Auto-scroll to bottom
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_plate_ready(self, info: dict):
        # Could update a live plate list here in future
        pass

    def _on_finished(self, plates: list):
        self._plates = plates
        self._panel.set_generating(False)
        self._panel.set_export_ready(len(plates) > 0)
        self._progress.setValue(100)

    def _on_error(self, msg: str):
        self._panel.set_generating(False)
        self._append_log(f"\n❌  ERROR:\n{msg}")
        QMessageBox.critical(self, "Generation error", msg[:800])

    # ── Window close ──────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(3000)
        event.accept()
