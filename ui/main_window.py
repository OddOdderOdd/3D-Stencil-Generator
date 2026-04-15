"""
ui/main_window.py
Root PyQt5 application window.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.quantizer import quantize
from core.tiler import compute_tile_grid
from export.guide_writer import PlateInfo
from ui.export_dialog import ExportDialog
from ui.panels import ControlPanel
from ui.preview_canvas import PreviewCanvas
from workers.generator_thread import GeneratorWorker

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
QTextEdit {
    background: #0a0a14; border: 1px solid #2e2e4a;
    border-radius: 6px; color: #7fff7f;
    font-family: 'Consolas', 'Courier New', monospace; font-size: 11px;
}
QProgressBar { background: #1c1c30; border-radius: 5px; height: 14px; border: 1px solid #2e2e4a; }
QProgressBar::chunk { background: #e94560; border-radius: 5px; }
QSplitter::handle { background: #2e2e4a; }
QListWidget { background:#0d0d1a; border:1px solid #2e2e4a; border-radius:6px; }
QToolButton { background:transparent; border:none; color:#a0c4ff; font-size:18px; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎨  3D Stencil Generator")
        self.setMinimumSize(1160, 700)
        self.setStyleSheet(DARK_QSS)

        self._image_path: str | None = None
        self._raw_image = None
        self._worker: GeneratorWorker | None = None
        self._plates: list[PlateInfo] = []
        self._output_dir = str(Path.cwd())
        self._last_qr = None

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.addStretch()
        self._settings_btn = QToolButton()
        self._settings_btn.setText("⚙")
        self._settings_btn.setToolTip("Settings (coming soon)")
        top.addWidget(self._settings_btn)
        root.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, stretch=1)

        self._panel = ControlPanel()
        self._panel.upload_btn.clicked.connect(self._on_upload)
        self._panel.colors_changed.connect(self._on_colors_changed)
        self._panel.generate_requested.connect(self._on_generate)
        self._panel.export_requested.connect(self._on_export)
        self._panel.grid_preview_pressed.connect(self._show_grid_preview)
        self._panel.grid_preview_released.connect(self._hide_grid_preview)
        body.addWidget(self._panel)

        right = QWidget()
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        center_split = QSplitter(Qt.Vertical)
        self._preview = PreviewCanvas()
        center_split.addWidget(self._preview)

        log_frame = QFrame()
        log_frame.setStyleSheet("background:#0d0d1a; border-radius:8px; border:1px solid #2e2e4a;")
        lf = QVBoxLayout(log_frame)
        self._progress = QProgressBar()
        self._progress.setValue(0)
        lf.addWidget(QLabel("Processing Log"))
        lf.addWidget(self._progress)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("Log output will appear here…")
        lf.addWidget(self._log)
        center_split.addWidget(log_frame)
        center_split.setSizes([420, 210])

        right_layout.addWidget(center_split, stretch=1)

        self._layers_panel = QFrame()
        self._layers_panel.setFixedWidth(280)
        self._layers_panel.setStyleSheet("background:#0d0d1a; border-radius:8px; border:1px solid #2e2e4a;")
        lp = QVBoxLayout(self._layers_panel)
        lp.addWidget(QLabel("Stencil Layers"))
        self._layer_list = QListWidget()
        self._layer_list.itemChanged.connect(self._on_layer_visibility_changed)
        lp.addWidget(self._layer_list)
        lp.addWidget(QLabel("Stencil logic"))
        self._logic_text = QTextEdit()
        self._logic_text.setReadOnly(True)
        lp.addWidget(self._logic_text)
        self._layers_panel.hide()
        right_layout.addWidget(self._layers_panel)

        body.addWidget(right, stretch=1)

    def _on_upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.webp)",
        )
        if not path:
            return
        img = cv2.imread(path)
        if img is None:
            QMessageBox.critical(self, "Load error", f"Cannot read image:\n{path}")
            return

        self._image_path = path
        self._raw_image = img
        self._output_dir = str(Path(path).parent)
        h, w = img.shape[:2]
        self._panel.set_image_info(os.path.basename(path), w, h)
        self._panel.generate_btn.setEnabled(True)

        self._preview.show_image(img, "Original Image")
        self._on_preview()

    def _on_colors_changed(self, _n: int):
        if self._raw_image is not None:
            self._on_preview()

    def _on_preview(self):
        if self._raw_image is None:
            return
        requested = self._panel.n_colors.value()
        self._last_qr = quantize(self._raw_image, requested)
        used = self._last_qr.n_colors
        self._preview.show_image(self._last_qr.quantized_image, f"Quantised Preview ({used} colours)")
        self._panel.swatch_bar.set_colors([tuple(c) for c in self._last_qr.centers_bgr.tolist()])

    def _show_grid_preview(self):
        if self._raw_image is None:
            return
        p = self._panel.get_params()
        grid = compute_tile_grid(p["canvas_w_mm"], p["canvas_h_mm"], p["bed_w_mm"], p["bed_h_mm"])
        self._preview.set_grid_overlay(grid.n_cols, grid.n_rows, True)

    def _hide_grid_preview(self):
        self._preview.set_grid_overlay(0, 0, False)

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
        params["image_path"] = self._image_path
        params["output_dir"] = self._output_dir

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
        grid = compute_tile_grid(params["canvas_w_mm"], params["canvas_h_mm"], params["bed_w_mm"], params["bed_h_mm"])
        dlg = ExportDialog(
            self._plates,
            self._output_dir,
            params["canvas_w_mm"],
            params["canvas_h_mm"],
            params["bed_w_mm"],
            params["bed_h_mm"],
            params["n_colors"],
            grid.n_cols,
            grid.n_rows,
            parent=self,
        )
        dlg.exec_()

    def _append_log(self, msg: str):
        self._log.append(msg)
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_plate_ready(self, info: dict):
        _ = info

    def _on_finished(self, plates: list):
        self._plates = plates
        self._panel.set_generating(False)
        self._panel.set_export_ready(len(plates) > 0)
        self._progress.setValue(100)
        self._populate_layers_panel()

    def _populate_layers_panel(self):
        self._layer_list.blockSignals(True)
        self._layer_list.clear()
        if not self._plates:
            self._layers_panel.hide()
            self._layer_list.blockSignals(False)
            return

        grouped: dict[int, list[PlateInfo]] = {}
        for p in self._plates:
            grouped.setdefault(p.color_idx, []).append(p)

        for color_idx in sorted(grouped):
            item = QListWidgetItem(f"Colour C{color_idx} ({len(grouped[color_idx])} tile(s))")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self._layer_list.addItem(item)

        lines = ["Generated stencil logic:"]
        for color_idx in sorted(grouped):
            cov = np.mean([p.coverage_pct for p in grouped[color_idx]])
            lines.append(f"- C{color_idx}: {len(grouped[color_idx])} plate(s), avg coverage {cov:.1f}%")
        self._logic_text.setText("\n".join(lines))

        self._layers_panel.show()
        self._layer_list.blockSignals(False)
        self._apply_layer_preview()

    def _on_layer_visibility_changed(self, _item: QListWidgetItem):
        self._apply_layer_preview()

    def _apply_layer_preview(self):
        if self._last_qr is None:
            return
        visible_idxs: set[int] = set()
        for i in range(self._layer_list.count()):
            item = self._layer_list.item(i)
            if item.checkState() == Qt.Checked:
                label = item.text().split()[1]  # Cx
                visible_idxs.add(int(label[1:]) - 1)

        if not visible_idxs:
            blank = np.zeros_like(self._last_qr.quantized_image)
            self._preview.show_image(blank, "Layer Preview (none visible)")
            return

        out = self._last_qr.quantized_image.copy()
        labels = self._last_qr.label_map
        mask = np.isin(labels, list(visible_idxs))
        faded = (out * 0.15).astype(np.uint8)
        out[~mask] = faded[~mask]
        self._preview.show_image(out, f"Layer Preview ({len(visible_idxs)} visible)")

    def _on_error(self, msg: str):
        self._panel.set_generating(False)
        self._append_log(f"\n❌  ERROR:\n{msg}")
        QMessageBox.critical(self, "Generation error", msg[:800])

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(3000)
        event.accept()
