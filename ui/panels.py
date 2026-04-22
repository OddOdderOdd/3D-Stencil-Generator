from __future__ import annotations

from PyQt5.QtCore import Qt, QSettings, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config import (
    DEFAULT_BED_H_MM,
    DEFAULT_BED_W_MM,
    DEFAULT_CANVAS_H_MM,
    DEFAULT_CANVAS_W_MM,
    DEFAULT_N_COLORS,
    DEFAULT_THICKEN_EDGES,
    DEFAULT_THICKNESS_MM,
    DEFAULT_TOLERANCE_PCT,
)


class ColourLogicBar(QWidget):
    """Quantised colours + ownership logic controls, persisted with QSettings."""
    state_changed = pyqtSignal()
    optimise_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("3d-stencil-generator", "app")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._layout.setSpacing(6)
        self._rows: list[dict] = []
        self._owned_rows: list[dict] = []

        own_group = QGroupBox("Owned colours")
        own_layout = QVBoxLayout(own_group)
        own_layout.setContentsMargins(8, 8, 8, 8)
        own_layout.setSpacing(6)
        self._layout.addWidget(own_group)

        add_row = QHBoxLayout()
        self.hex_input = QLineEdit()
        self.hex_input.setPlaceholderText("#RRGGBB")
        self.hex_input.setMaxLength(7)
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._add_owned_hex)
        add_row.addWidget(QLabel("HTML/HEX:"))
        add_row.addWidget(self.hex_input, stretch=1)
        add_row.addWidget(self.add_btn)
        own_layout.addLayout(add_row)

        pick_row = QHBoxLayout()
        self.pick_btn = QPushButton("Pick colour…")
        self.pick_btn.setToolTip("Open color picker tool.")
        self.pick_btn.clicked.connect(self._pick_owned_colour)
        self.import_btn = QPushButton("Import")
        self.import_btn.clicked.connect(self._import_owned_colours)
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._save_owned_colours)
        pick_row.addWidget(self.pick_btn)
        pick_row.addWidget(self.import_btn)
        pick_row.addWidget(self.save_btn)
        own_layout.addLayout(pick_row)

        self._owned_rows_layout = QVBoxLayout()
        self._owned_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._owned_rows_layout.setSpacing(4)
        own_layout.addLayout(self._owned_rows_layout)

        comp_group = QGroupBox("Computer colours")
        comp_layout = QVBoxLayout(comp_group)
        comp_layout.setContentsMargins(8, 8, 8, 8)
        comp_layout.setSpacing(6)
        self._layout.addWidget(comp_group)

        top = QHBoxLayout()
        self.optimise_btn = QPushButton("Optimise")
        self.optimise_btn.setToolTip("Enable the most useful computer colours for the current image.")
        self.optimise_btn.clicked.connect(self.optimise_requested.emit)
        top.addWidget(self.optimise_btn)
        top.addStretch()
        comp_layout.addLayout(top)

        self._computer_rows_layout = QVBoxLayout()
        self._computer_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._computer_rows_layout.setSpacing(4)
        comp_layout.addLayout(self._computer_rows_layout)

        self._load_owned_hexes()

    def _normalize_hex(self, text: str) -> str | None:
        t = text.strip().upper()
        if not t:
            return None
        if not t.startswith("#"):
            t = f"#{t}"
        if len(t) != 7:
            return None
        try:
            int(t[1:], 16)
        except ValueError:
            return None
        return t


    def _load_owned_hexes(self):
        raw = self._settings.value("owned_hexes", [], type=list)
        self._owned_entries = []
        for rec in raw:
            if isinstance(rec, dict):
                hx = self._normalize_hex(rec.get("hex", ""))
                use = bool(rec.get("use", True))
            else:
                hx = self._normalize_hex(str(rec))
                use = True
            if hx:
                self._owned_entries.append({"hex": hx, "use": use})
        self._owned_entries.sort(key=lambda e: e["hex"])
        self._render_owned_hexes()

    def _save_owned_hexes(self):
        self._settings.setValue("owned_hexes", self._owned_entries)

    def _render_owned_hexes(self):
        while self._owned_rows_layout.count() > 0:
            item = self._owned_rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._owned_rows.clear()

        for entry in self._owned_entries:
            hx = entry["hex"]
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            swatch = QFrame()
            swatch.setFixedSize(16, 16)
            swatch.setStyleSheet(f"background:{hx}; border-radius:3px; border:1px solid rgba(255,255,255,0.3);")

            label = QLabel(hx)
            label.setStyleSheet("font-size: 11px; color: #e0e0e0;")

            use_btn = QPushButton("Use")
            use_btn.setCheckable(True)
            use_btn.setFixedHeight(24)
            use_btn.setChecked(entry["use"])
            self._sync_use_style(use_btn)
            use_btn.toggled.connect(lambda state, b=use_btn: self._sync_use_style(b))
            use_btn.toggled.connect(lambda state, h=hx: self._set_owned_use(h, state))
            use_btn.toggled.connect(self.state_changed.emit)

            remove_btn = QPushButton("✕")
            remove_btn.setFixedSize(24, 24)
            remove_btn.clicked.connect(lambda _=False, h=hx: self._remove_owned_hex(h))

            row_layout.addWidget(swatch)
            row_layout.addWidget(label)
            row_layout.addStretch()
            row_layout.addWidget(use_btn)
            row_layout.addWidget(remove_btn)
            self._owned_rows_layout.addWidget(row_widget)
            self._owned_rows.append({"hex": hx, "btn": use_btn})

    def _add_owned_hex(self):
        hx = self._normalize_hex(self.hex_input.text())
        if not hx:
            return
        if hx not in [e["hex"] for e in self._owned_entries]:
            self._owned_entries.append({"hex": hx, "use": True})
            self._owned_entries.sort(key=lambda e: e["hex"])
            self._save_owned_hexes()
            self._render_owned_hexes()
            self.state_changed.emit()
        self.hex_input.clear()

    def _pick_owned_colour(self):
        color = QColorDialog.getColor(parent=self, title="Pick owned colour")
        if not color.isValid():
            return
        self.hex_input.setText(color.name().upper())
        self._add_owned_hex()


    def _set_owned_use(self, hx: str, use: bool):
        for entry in self._owned_entries:
            if entry["hex"] == hx:
                entry["use"] = bool(use)
                break
        self._save_owned_hexes()

    def _remove_owned_hex(self, hx: str):
        self._owned_entries = [e for e in self._owned_entries if e["hex"] != hx]
        self._save_owned_hexes()
        self._render_owned_hexes()
        self.state_changed.emit()

    def _import_owned_colours(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import owned colours", "", "Text files (*.txt)")
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            lines = [self._normalize_hex(line) for line in f.readlines()]
        merged = {e["hex"]: e for e in self._owned_entries}
        for hx in lines:
            if hx and hx not in merged:
                merged[hx] = {"hex": hx, "use": True}
        self._owned_entries = sorted(merged.values(), key=lambda e: e["hex"])
        self._save_owned_hexes()
        self._render_owned_hexes()
        self.state_changed.emit()

    def _save_owned_colours(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save owned colours", "owned_colours.txt", "Text files (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(e["hex"] for e in self._owned_entries))

    def set_colors(self, bgr_list: list[tuple[int, int, int]]):
        while self._computer_rows_layout.count() > 0:
            item = self._computer_rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()

        in_use_owned = set(self.in_use_owned_hexes())
        for idx, bgr in enumerate(bgr_list):
            r, g, b = int(bgr[2]), int(bgr[1]), int(bgr[0])
            hx = f"#{r:02X}{g:02X}{b:02X}"
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            swatch = QFrame()
            swatch.setFixedSize(24, 24)
            swatch.setStyleSheet(
                f"background: rgb({r},{g},{b}); border-radius: 4px; border: 1.5px solid rgba(255,255,255,0.25);"
            )

            label = QLabel(hx)
            label.setStyleSheet("font-size: 11px; color: #e0e0e0;")

            use_btn = QPushButton("Use")
            use_btn.setCheckable(True)
            use_btn.setFixedHeight(24)
            should_use = (not in_use_owned) or (hx in in_use_owned)
            use_btn.setChecked(should_use)
            self._sync_use_style(use_btn)
            use_btn.toggled.connect(lambda state, b=use_btn: self._sync_use_style(b))
            use_btn.toggled.connect(self._refresh_computer_identifiers)
            use_btn.toggled.connect(self.state_changed.emit)

            row_layout.addWidget(swatch)
            row_layout.addWidget(label)
            row_layout.addStretch()
            row_layout.addWidget(use_btn)
            self._computer_rows_layout.addWidget(row_widget)

            self._rows.append({"idx": idx, "hex": hx, "btn": use_btn, "label": label})

        self._refresh_computer_identifiers()
        self.state_changed.emit()

    def _refresh_computer_identifiers(self):
        active_i = 1
        for row in self._rows:
            if row["btn"].isChecked():
                row["label"].setText(f"C{active_i}  {row['hex']}")
                active_i += 1
            else:
                row["label"].setText(row["hex"])

    def _sync_use_style(self, btn: QPushButton):
        if btn.isChecked():
            btn.setStyleSheet("background:#42b883; color:white; font-weight:bold;")
        else:
            btn.setStyleSheet("background:#4b2230; color:#ffb3c1;")

    def in_use_owned_hexes(self) -> list[str]:
        result = []
        for row in self._owned_rows:
            if row["btn"].isChecked():
                result.append(row["hex"])
        return result

    def owned_indices(self) -> list[int]:
        return [r["idx"] for r in self._rows if r["btn"].isChecked()]

    def skipped_indices(self) -> list[int]:
        return [r["idx"] for r in self._rows if not r["btn"].isChecked()]

    def optimise_for_coverage(self, coverage: list[float], tolerance: float):
        if not self._rows:
            return
        best_idx = max(range(len(coverage)), key=lambda i: coverage[i] if i < len(coverage) else 0.0)
        for row in self._rows:
            cov = coverage[row["idx"]] if row["idx"] < len(coverage) else 0.0
            keep = cov >= tolerance
            if all(c < tolerance for c in coverage):
                keep = row["idx"] == best_idx
            row["btn"].setChecked(keep)
        self._refresh_computer_identifiers()
        self.state_changed.emit()


class ControlPanel(QWidget):
    colors_changed = pyqtSignal(int)
    settings_changed = pyqtSignal()
    color_logic_changed = pyqtSignal()
    generate_requested = pyqtSignal()
    export_requested = pyqtSignal()
    grid_preview_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(360)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 8, 0)
        root.setSpacing(10)

        title = QLabel("3D Stencil Generator")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setStyleSheet("color: #e94560;")
        root.addWidget(title)

        sub = QLabel("Image → 3D-printable spray-paint stencils")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #777; font-size: 11px; margin-bottom: 4px;")
        root.addWidget(sub)

        img_group = QGroupBox("Image")
        ig = QVBoxLayout(img_group)
        self.upload_btn = QPushButton("📂  Upload Image…")
        self.img_info = QLabel("No image loaded")
        self.img_info.setStyleSheet("color: #888; font-size: 10px;")
        self.img_info.setWordWrap(True)
        ig.addWidget(self.upload_btn)
        ig.addWidget(self.img_info)
        root.addWidget(img_group)

        dim_group = QGroupBox("Dimensions (cm)")
        dg = QGridLayout(dim_group)
        dg.setVerticalSpacing(6)

        def _dspin(val_mm, lo=0.1, hi=500.0, step=1.0):
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setValue(val_mm / 10.0)
            s.setSingleStep(step)
            s.setSuffix(" cm")
            s.setDecimals(1)
            return s

        dg.addWidget(QLabel("Canvas W:"), 0, 0)
        self.canvas_w = _dspin(DEFAULT_CANVAS_W_MM)
        dg.addWidget(self.canvas_w, 0, 1)

        dg.addWidget(QLabel("Canvas H:"), 1, 0)
        self.canvas_h = _dspin(DEFAULT_CANVAS_H_MM)
        dg.addWidget(self.canvas_h, 1, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        dg.addWidget(sep, 2, 0, 1, 2)

        dg.addWidget(QLabel("Bed W:"), 3, 0)
        self.bed_w = _dspin(DEFAULT_BED_W_MM)
        dg.addWidget(self.bed_w, 3, 1)

        dg.addWidget(QLabel("Bed H:"), 4, 0)
        self.bed_h = _dspin(DEFAULT_BED_H_MM)
        dg.addWidget(self.bed_h, 4, 1)

        self.grid_toggle_btn = QPushButton("Show tile grid")
        self.grid_toggle_btn.setCheckable(True)
        self.grid_toggle_btn.setToolTip("Toggle tile grid overlay on preview.")
        self.grid_toggle_btn.toggled.connect(self.grid_preview_toggled.emit)
        dg.addWidget(self.grid_toggle_btn, 5, 0, 1, 2)

        root.addWidget(dim_group)

        pal_group = QGroupBox("Colour logic")
        pg2 = QVBoxLayout(pal_group)
        pg2.setSpacing(8)
        max_row = QHBoxLayout()
        max_row.addWidget(QLabel("Maximum Colours (mN):"))
        self.n_colors = QSpinBox()
        self.n_colors.setRange(2, 24)
        self.n_colors.setValue(DEFAULT_N_COLORS)
        self.n_colors.valueChanged.connect(self.colors_changed)
        self.n_colors.valueChanged.connect(self.settings_changed.emit)
        max_row.addWidget(self.n_colors)
        pg2.addLayout(max_row)

        self.real_n_label = QLabel("Real colours (N): 0")
        self.real_n_label.setStyleSheet("color:#9aa; font-size:11px;")
        pg2.addWidget(self.real_n_label)

        self.logic_warning_label = QLabel("")
        self.logic_warning_label.setStyleSheet("color:#ff6b6b; font-size:11px; font-weight:bold;")
        self.logic_warning_label.hide()
        pg2.addWidget(self.logic_warning_label)

        self.swatch_bar = ColourLogicBar()
        self.swatch_bar.state_changed.connect(self.color_logic_changed.emit)
        self.swatch_bar.optimise_requested.connect(self.color_logic_changed.emit)
        pg2.addWidget(self.swatch_bar)
        root.addWidget(pal_group)

        param_group = QGroupBox("Stencil Parameters")
        pg = QGridLayout(param_group)
        pg.setVerticalSpacing(6)

        pg.addWidget(QLabel("Thickness:"), 0, 0)
        self.thickness = QDoubleSpinBox()
        self.thickness.setRange(0.4, 10.0)
        self.thickness.setValue(DEFAULT_THICKNESS_MM)
        self.thickness.setSingleStep(0.1)
        self.thickness.setSuffix(" mm")
        self.thickness.setDecimals(1)
        self.thickness.valueChanged.connect(self.settings_changed.emit)
        pg.addWidget(self.thickness, 0, 1)

        self.thicken_edges = QCheckBox("Thicken edges  (alignment lip +0.4 mm)")
        self.thicken_edges.setChecked(DEFAULT_THICKEN_EDGES)
        self.thicken_edges.toggled.connect(self.settings_changed.emit)
        pg.addWidget(self.thicken_edges, 1, 0, 1, 2)
        root.addWidget(param_group)

        tol_group = QGroupBox("Tolerance")
        tg = QVBoxLayout(tol_group)
        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel("Skip plate if colour coverage <"))
        self.tol_label = QLabel(f"{int(DEFAULT_TOLERANCE_PCT)}%")
        self.tol_label.setStyleSheet("color: #e94560; font-weight: bold; min-width: 36px;")
        tol_row.addWidget(self.tol_label)
        tg.addLayout(tol_row)

        from PyQt5.QtWidgets import QSlider
        self.tol_slider = QSlider(Qt.Horizontal)
        self.tol_slider.setRange(0, 50)
        self.tol_slider.setValue(int(DEFAULT_TOLERANCE_PCT))
        self.tol_slider.setTickInterval(5)
        self.tol_slider.setTickPosition(QSlider.TicksBelow)
        self.tol_slider.valueChanged.connect(lambda v: self.tol_label.setText(f"{v}%"))
        self.tol_slider.valueChanged.connect(self.settings_changed.emit)
        tg.addWidget(self.tol_slider)
        root.addWidget(tol_group)

        root.addStretch()

        self.generate_btn = QPushButton("⚙️   Generate Stencils")
        self.generate_btn.setEnabled(False)
        self.generate_btn.setStyleSheet(
            "background:#e94560; color:#fff; font-weight:bold; font-size:13px; padding:10px; border-radius:7px;"
        )
        self.generate_btn.clicked.connect(self.generate_requested)
        root.addWidget(self.generate_btn)

        self.export_btn = QPushButton("📦  Export…")
        self.export_btn.setEnabled(False)
        self.export_btn.setStyleSheet("font-size:12px; padding:8px; border-radius:7px;")
        self.export_btn.clicked.connect(self.export_requested)
        root.addWidget(self.export_btn)

    def get_params(self) -> dict:
        return {
            "canvas_w_mm": self.canvas_w.value() * 10.0,
            "canvas_h_mm": self.canvas_h.value() * 10.0,
            "bed_w_mm": self.bed_w.value() * 10.0,
            "bed_h_mm": self.bed_h.value() * 10.0,
            "n_colors": self.n_colors.value(),
            "thickness_mm": self.thickness.value(),
            "thicken_edges": self.thicken_edges.isChecked(),
            "tolerance_pct": float(self.tol_slider.value()),
            "owned_colour_indices": self.swatch_bar.owned_indices(),
        }

    def set_real_color_count(self, n: int):
        self.real_n_label.setText(f"Real colours (N): {n}")

    def set_color_logic_validity(self, valid: bool, message: str = ""):
        if valid:
            self.logic_warning_label.hide()
            self.logic_warning_label.setText("")
        else:
            self.logic_warning_label.setText(f"❗ {message}")
            self.logic_warning_label.show()

    def set_image_info(self, filename: str, w: int, h: int):
        self.img_info.setText(f"✓ {filename}  ({w}×{h} px)")

    def set_generating(self, active: bool):
        self.generate_btn.setEnabled(not active)
        self.generate_btn.setText("⏳  Generating…" if active else "⚙️   Generate Stencils")
        self.upload_btn.setEnabled(not active)

    def set_export_ready(self, ready: bool):
        self.export_btn.setEnabled(ready)
