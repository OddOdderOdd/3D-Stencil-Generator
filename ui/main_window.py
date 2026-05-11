"""
ui/main_window.py
Root PyQt5 application window.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
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
    QScrollArea,
    QSplitter,
    QTabWidget,
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
QTabWidget::pane { border:1px solid #2e2e4a; border-radius:6px; }
QTabBar::tab {
    background:#1a1a2a; color:#bbb; padding:6px 10px; margin-right:2px;
    border-top-left-radius:5px; border-top-right-radius:5px;
}
QTabBar::tab:selected { background:#253560; color:#fff; }
"""

# Qt.UserRole slots used on QListWidgetItems in the colour-layer list
_ROLE_CLUSTERS = Qt.UserRole          # list[int] — K-means cluster indices
_ROLE_KIND     = Qt.UserRole + 1      # str — "background" | "owned" | "color"
_ROLE_HEX      = Qt.UserRole + 2      # str — representative hex colour


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
        self._last_color_coverage = []
        self._color_logic_valid = True
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(180)
        self._preview_timer.timeout.connect(self._run_preview)
        self._slow_pc_mode = QSettings("3d-stencil-generator", "app").value(
            "slow_pc_mode", False, type=bool
        )

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.addStretch()
        self._slow_pc_btn = QToolButton()
        self._slow_pc_btn.setText("🐢")
        self._slow_pc_btn.setToolTip(
            "Slow PC mode: wait 1.5 s after a setting changes before updating preview\n"
            "(prevents freezing on slower machines)"
        )
        self._slow_pc_btn.setCheckable(True)
        self._slow_pc_btn.setChecked(self._slow_pc_mode)
        self._slow_pc_btn.setStyleSheet(
            "QToolButton:checked { background:#2a3a1a; color:#8f8; border-radius:4px; }"
        )
        self._slow_pc_btn.toggled.connect(self._on_slow_pc_toggled)
        top.addWidget(self._slow_pc_btn)

        self._settings_btn = QToolButton()
        self._settings_btn.setText("⚙")
        self._settings_btn.setToolTip("Settings")
        self._settings_btn.clicked.connect(self._on_settings_clicked)
        top.addWidget(self._settings_btn)
        root.addLayout(top)

        body_split = QSplitter(Qt.Horizontal)
        body_split.setChildrenCollapsible(False)
        root.addWidget(body_split, stretch=1)

        self._panel = ControlPanel()
        self._panel.upload_btn.clicked.connect(self._on_upload)
        self._panel.colors_changed.connect(self._on_colors_changed)
        self._panel.settings_changed.connect(self._on_preview)
        self._panel.color_logic_changed.connect(self._on_color_logic_changed)
        self._panel.generate_requested.connect(self._on_generate)
        self._panel.export_requested.connect(self._on_export)
        self._panel.grid_preview_toggled.connect(self._on_grid_toggle)
        self._panel.swatch_bar.optimise_requested.connect(self._on_optimise_colours)
        self._panel.swatch_bar.optimise_owned_requested.connect(self._on_optimise_owned_colours)
        self._panel.swatch_bar.optimise_background_requested.connect(self._on_optimise_background_colour)
        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setFrameShape(QFrame.NoFrame)
        panel_scroll.setWidget(self._panel)
        body_split.addWidget(panel_scroll)

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
        self._layers_panel.setMinimumWidth(310)
        self._layers_panel.setStyleSheet("background:#0d0d1a; border-radius:8px; border:1px solid #2e2e4a;")
        lp = QVBoxLayout(self._layers_panel)
        self._layers_tabs = QTabWidget()
        self._color_tab = QWidget()
        color_tab_layout = QVBoxLayout(self._color_tab)
        color_tab_layout.setContentsMargins(6, 6, 6, 6)
        color_tab_layout.setSpacing(6)
        self._show_original_pin = QCheckBox("Pinned: show original image")
        self._show_original_pin.toggled.connect(lambda _checked: self._apply_layer_preview())
        color_tab_layout.addWidget(self._show_original_pin)
        self._color_layer_list = QListWidget()
        color_tab_layout.addWidget(self._color_layer_list)
        self._layer_list = QListWidget()
        self._layer_list.itemChanged.connect(self._on_layer_visibility_changed)
        self._color_layer_list.itemChanged.connect(self._on_layer_visibility_changed)
        self._layers_tabs.addTab(self._color_tab, "Colour Layers")
        self._layers_tabs.addTab(self._layer_list, "Stencil Layers")
        self._layers_tabs.setCurrentIndex(0)
        self._layers_tabs.currentChanged.connect(lambda _i: self._apply_layer_preview())
        lp.addWidget(self._layers_tabs)
        lp.addWidget(QLabel("Stencil logic"))
        self._logic_text = QTextEdit()
        self._logic_text.setReadOnly(True)
        self._logic_text.setPlainText("Upload an image to view colour layers.")
        lp.addWidget(self._logic_text)
        right_layout.addWidget(self._layers_panel)

        body_split.addWidget(right)
        body_split.setStretchFactor(0, 0)
        body_split.setStretchFactor(1, 1)
        body_split.setSizes([370, 960])

    # ── upload ────────────────────────────────────────────────────────────────

    def _on_upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", "",
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
        run_dir = (
            Path(path).parent
            / f"{Path(path).stem}_stencils_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        self._output_dir = str(run_dir)
        h, w = img.shape[:2]
        self._panel.set_image_info(os.path.basename(path), w, h)
        self._panel.generate_btn.setEnabled(True)

        self._preview.show_image(img, "Original Image")
        self._on_preview()

    # ── preview pipeline ──────────────────────────────────────────────────────

    def _on_colors_changed(self, _n: int):
        if self._raw_image is not None:
            self._queue_preview_update()

    def _on_color_logic_changed(self):
        self._update_color_logic_state()
        self._populate_colour_layers_preview()
        self._apply_layer_preview()

    def _on_preview(self):
        self._queue_preview_update()

    def _queue_preview_update(self):
        self._preview_timer.start()

    def _run_preview(self):
        if self._raw_image is None:
            return
        requested = self._panel.n_colors.value()
        self._last_qr = quantize(self._raw_image, requested)
        self._last_color_coverage = self._compute_coverage(
            self._last_qr.label_map, self._last_qr.n_colors
        )
        # Give the swatch bar both the K-means centres and the resized canvas
        # image so it can run palette-mode assignment for owned-colour preview.
        self._panel.swatch_bar.set_kmeans_centers(self._last_qr.centers_bgr)
        from core.tiler import canvas_size_px
        p = self._panel.get_params()
        cw_px, ch_px = canvas_size_px(p["canvas_w_mm"], p["canvas_h_mm"])
        import cv2 as _cv2
        canvas_bgr = _cv2.resize(self._raw_image, (cw_px, ch_px), interpolation=_cv2.INTER_AREA)
        self._panel.swatch_bar.set_canvas_image(canvas_bgr)

        self._update_color_logic_state()
        used = self._effective_color_count()
        self._preview.show_image(
            self._last_qr.quantized_image,
            f"Quantised Preview ({used} active colours)",
        )
        self._panel.swatch_bar.set_colors(
            [tuple(c) for c in self._last_qr.centers_bgr.tolist()]
        )
        self._populate_colour_layers_preview()
        self._update_color_logic_state()

    def _on_grid_toggle(self, checked: bool):
        if not checked:
            self._preview.set_grid_overlay(0, 0, False)
            return
        if self._raw_image is None:
            return
        p = self._panel.get_params()
        grid = compute_tile_grid(
            p["canvas_w_mm"], p["canvas_h_mm"], p["bed_w_mm"], p["bed_h_mm"]
        )
        self._preview.set_grid_overlay(grid.n_cols, grid.n_rows, True)

    # ── optimise helpers ──────────────────────────────────────────────────────

    def _on_optimise_colours(self):
        if self._last_qr is None:
            return
        self._panel.swatch_bar.optimise_for_coverage(
            self._last_color_coverage, float(self._panel.tol_slider.value())
        )
        self._update_color_logic_state()
        self._populate_colour_layers_preview()
        self._apply_layer_preview()

    def _on_optimise_owned_colours(self):
        if self._last_qr is None:
            return
        coverage_by_hex: dict[str, float] = {}
        for idx, bgr in enumerate(self._last_qr.centers_bgr.tolist()):
            r, g, b = int(bgr[2]), int(bgr[1]), int(bgr[0])
            hx = f"#{r:02X}{g:02X}{b:02X}"
            coverage_by_hex[hx] = (
                self._last_color_coverage[idx]
                if idx < len(self._last_color_coverage) else 0.0
            )
        self._panel.swatch_bar.optimise_owned_for_coverage(
            coverage_by_hex, float(self._panel.tol_slider.value())
        )
        self._update_color_logic_state()
        self._populate_colour_layers_preview()
        self._apply_layer_preview()

    def _on_optimise_background_colour(self):
        if self._last_qr is None or not self._last_qr.centers_bgr.size:
            return
        dominant_idx = (
            int(np.argmax(np.array(self._last_color_coverage)))
            if self._last_color_coverage else 0
        )
        dominant_idx = max(0, min(dominant_idx, len(self._last_qr.centers_bgr) - 1))
        bgr = self._last_qr.centers_bgr[dominant_idx]
        hx = f"#{int(bgr[2]):02X}{int(bgr[1]):02X}{int(bgr[0]):02X}"
        self._panel.swatch_bar.set_background_hex(hx)
        self._populate_colour_layers_preview()
        self._apply_layer_preview()

    # ── generation ────────────────────────────────────────────────────────────

    def _on_generate(self):
        if self._image_path is None:
            QMessageBox.warning(self, "No image", "Please upload an image first.")
            return
        if not self._color_logic_valid:
            QMessageBox.warning(
                self, "Invalid colour logic",
                "Fix colour logic warning before generating.",
            )
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
        grid = compute_tile_grid(
            params["canvas_w_mm"], params["canvas_h_mm"],
            params["bed_w_mm"], params["bed_h_mm"],
        )
        dlg = ExportDialog(
            self._plates,
            self._output_dir,
            params["canvas_w_mm"],
            params["canvas_h_mm"],
            params["bed_w_mm"],
            params["bed_h_mm"],
            self._effective_color_count(),
            grid.n_cols,
            grid.n_rows,
            parent=self,
        )
        dlg.exec_()

    def _on_slow_pc_toggled(self, checked: bool):
        self._slow_pc_mode = checked
        QSettings("3d-stencil-generator", "app").setValue("slow_pc_mode", checked)
        delay = 1500 if checked else 180
        self._preview_timer.setInterval(delay)
        status = "ON (1.5 s delay)" if checked else "OFF (instant)"
        self._append_log(f"🐢  Slow PC mode {status}")

    def _on_settings_clicked(self):
        QMessageBox.information(self, "Settings", "Global settings are not implemented yet.")

    # ── log / progress ────────────────────────────────────────────────────────

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

    # ── layers panel (post-generation stencil list) ───────────────────────────

    def _populate_layers_panel(self):
        self._layer_list.blockSignals(True)
        self._color_layer_list.blockSignals(True)
        self._layer_list.clear()
        self._populate_colour_layers_preview()
        if not self._plates:
            self._logic_text.setPlainText(
                "Generate stencils to view tile-by-tile stencil breakdown."
            )
            self._layer_list.blockSignals(False)
            self._color_layer_list.blockSignals(False)
            return

        grouped: dict[int, list[PlateInfo]] = {}
        for p in self._plates:
            grouped.setdefault(p.color_idx, []).append(p)

        for color_idx in sorted(grouped):
            item = QListWidgetItem(
                f"Colour C{color_idx} ({len(grouped[color_idx])} tile(s))"
            )
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self._layer_list.addItem(item)

        lines = ["Generated stencil logic:"]
        for color_idx in sorted(grouped):
            cov = np.mean([p.coverage_pct for p in grouped[color_idx]])
            lines.append(
                f"- C{color_idx}: {len(grouped[color_idx])} plate(s), "
                f"avg coverage {cov:.1f}%"
            )
        self._logic_text.setText("\n".join(lines))

        self._layer_list.blockSignals(False)
        self._color_layer_list.blockSignals(False)
        self._apply_layer_preview()

    # ── colour layers preview list ────────────────────────────────────────────

    def _populate_colour_layers_preview(self):
        """
        Rebuild the Colour Layers list from active_layer_entries().
        All three kinds (background, owned, color) can appear together.

        _ROLE_CLUSTERS stores:
          background/owned → palette_label string ("B0", "O1", …)
          color            → list[int] of K-means cluster indices
        """
        self._color_layer_list.blockSignals(True)
        self._color_layer_list.clear()

        for entry in self._panel.swatch_bar.active_layer_entries():
            kind  = entry["kind"]
            label = entry["label"]
            hx    = entry.get("hex", "#888888")

            # palette-mode entries store their label string; computer entries
            # store their cluster index list — _apply_layer_preview reads kind
            # to know which to use.
            if kind in ("background", "owned"):
                role_data = entry.get("palette_label", label)
            else:
                role_data = entry.get("cluster_indices", [])

            display = f"  {label}  {hx}"
            item = QListWidgetItem(display)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(_ROLE_CLUSTERS, role_data)
            item.setData(_ROLE_KIND,     kind)
            item.setData(_ROLE_HEX,      hx)
            self._color_layer_list.addItem(item)

        self._color_layer_list.blockSignals(False)

    def _on_layer_visibility_changed(self, _item: QListWidgetItem):
        self._apply_layer_preview()

    def _apply_layer_preview(self):
        if self._last_qr is None:
            return

        if self._show_original_pin.isChecked() and self._raw_image is not None:
            self._preview.show_image(self._raw_image, "Original Image (pinned)")
            return

        active_list = (
            self._color_layer_list
            if self._layers_tabs.currentIndex() == 0
            else self._layer_list
        )

        # Collect checked items — all three kinds can coexist
        checked_items = []
        for i in range(active_list.count()):
            item = active_list.item(i)
            if item.checkState() == Qt.Checked:
                checked_items.append(item)

        if not checked_items:
            blank = np.zeros_like(self._last_qr.quantized_image)
            self._preview.show_image(blank, "Layer Preview (none visible)")
            return

        canvas_bgr = getattr(self._panel.swatch_bar, "_canvas_image_bgr", None)
        base = canvas_bgr if canvas_bgr is not None else self._last_qr.quantized_image
        h_base, w_base = base.shape[:2]

        has_background = any(i.data(_ROLE_KIND) == "background" for i in checked_items)
        owned_items    = [i for i in checked_items if i.data(_ROLE_KIND) == "owned"]
        color_items    = [i for i in checked_items if i.data(_ROLE_KIND) == "color"]

        # B0 alone — solid full plate, show the whole image
        if has_background and not owned_items and not color_items:
            self._preview.show_image(base, "Layer Preview — B0 (solid base coat)")
            return

        # Build combined pixel mask over all active non-background layers
        combined = np.zeros((h_base, w_base), dtype=bool)

        # Owned layers via palette assignment map
        if owned_items:
            pmap = self._panel.swatch_bar.get_palette_assignment()
            if pmap is not None:
                ph, pw = pmap.assignment_map.shape
                for item in owned_items:
                    lbl = item.data(_ROLE_CLUSTERS)  # palette_label stored here
                    if not lbl:
                        continue
                    idx = pmap._index_of(lbl)
                    if idx < 0:
                        continue
                    m = (pmap.assignment_map == idx)
                    if (ph, pw) != (h_base, w_base):
                        m = cv2.resize(m.astype(np.uint8), (w_base, h_base),
                                       interpolation=cv2.INTER_NEAREST).astype(bool)
                    combined |= m

        # Computer-colour layers via K-means label map
        if color_items and self._last_qr is not None:
            labels = self._last_qr.label_map
            kh, kw = labels.shape
            clusters: set[int] = set()
            for item in color_items:
                data = item.data(_ROLE_CLUSTERS)
                if isinstance(data, list):
                    clusters.update(data)
            if clusters:
                km = np.isin(labels, list(clusters))
                if (kh, kw) != (h_base, w_base):
                    km = cv2.resize(km.astype(np.uint8), (w_base, h_base),
                                    interpolation=cv2.INTER_NEAREST).astype(bool)
                combined |= km

        # If background is also checked it fills everything not claimed by
        # owned/computer layers — the whole image is visible
        if has_background:
            self._preview.show_image(
                base,
                f"Layer Preview ({len(checked_items)} layer(s)) — B0 fills remainder",
            )
            return

        if not combined.any():
            blank = np.zeros_like(base)
            self._preview.show_image(blank, "Layer Preview (none visible)")
            return

        faded  = (base * 0.15).astype(np.uint8)
        result = base.copy()
        result[~combined] = faded[~combined]
        edge_map = cv2.Canny((combined.astype(np.uint8) * 255), 70, 130)
        result[edge_map > 0] = (255, 255, 255)
        n = len(owned_items) + len(color_items)
        self._preview.show_image(result, f"Layer Preview ({n} layer(s))")

    # ── coverage / colour counting ────────────────────────────────────────────

    def _compute_coverage(self, label_map: np.ndarray, n_colors: int) -> list[float]:
        total = float(label_map.size)
        if total <= 0:
            return [0.0] * n_colors
        return [100.0 * float(np.mean(label_map == i)) for i in range(n_colors)]

    def _effective_color_count(self) -> int:
        if self._last_qr is None:
            return 0
        tolerance = float(self._panel.tol_slider.value())
        skipped = set(self._panel.swatch_bar.skipped_indices())
        active = 1 if self._panel.swatch_bar.background_enabled() else 0
        # count active owned colours
        active += len(self._panel.swatch_bar.active_owned_hexes())
        # count computer colours that are not skipped, not claimed by owned, and above tolerance
        claimed: set[int] = set()
        for hx in self._panel.swatch_bar.active_owned_hexes():
            claimed.update(self._panel.swatch_bar._resolve_owned_clusters(hx))
        for idx in range(self._last_qr.n_colors):
            if idx in skipped:
                continue
            if idx in claimed:
                continue
            coverage = (
                self._last_color_coverage[idx]
                if idx < len(self._last_color_coverage) else 0.0
            )
            if coverage < tolerance:
                continue
            active += 1
        return active

    def _update_color_logic_state(self):
        effective = self._effective_color_count()
        self._panel.set_real_color_count(effective)
        valid = effective > 0 if self._last_qr is not None else True
        self._color_logic_valid = valid
        if valid:
            self._panel.set_color_logic_validity(True)
        else:
            self._panel.set_color_logic_validity(
                False,
                "No active colours selected. Toggle at least one 'Use' button.",
            )
        has_img = self._raw_image is not None
        self._panel.generate_btn.setEnabled(has_img and valid)
        self._panel.export_btn.setEnabled(bool(self._plates) and valid)

    def _on_error(self, msg: str):
        self._panel.set_generating(False)
        self._append_log(f"\n❌  ERROR:\n{msg}")
        QMessageBox.critical(self, "Generation error", msg[:800])

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait(3000)
        event.accept()
