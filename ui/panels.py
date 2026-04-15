"""
ui/panels.py
Left-side control panel: all input widgets grouped into QGroupBoxes.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QSettings, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("3d-stencil-generator", "app")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._layout.setSpacing(6)
        self._rows: list[dict] = []

        top = QHBoxLayout()
        self.no_limit = QCheckBox("No limit")
        self.no_limit.setChecked(True)
        self.no_limit.toggled.connect(self._on_no_limit_toggled)
        top.addWidget(self.no_limit)
        top.addStretch()
        self._layout.addLayout(top)

        add_row = QHBoxLayout()
        self.hex_input = QLineEdit()
        self.hex_input.setPlaceholderText("#RRGGBB")
        self.hex_input.setMaxLength(7)
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._add_owned_hex)
        add_row.addWidget(QLabel("Owned hex:"))
        add_row.addWidget(self.hex_input, stretch=1)
        add_row.addWidget(self.add_btn)
        self._layout.addLayout(add_row)

        self.owned_list = QLabel()
        self.owned_list.setWordWrap(True)
        self.owned_list.setStyleSheet("color:#9aa; font-size:10px;")
        self._layout.addWidget(self.owned_list)

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
        self._owned_hexes = [h for h in (self._normalize_hex(x) for x in raw) if h]
        self._render_owned_hexes()

    def _save_owned_hexes(self):
        self._settings.setValue("owned_hexes", self._owned_hexes)

    def _render_owned_hexes(self):
        if not self._owned_hexes:
            self.owned_list.setText("Saved owned colours: (none)")
        else:
            self.owned_list.setText("Saved owned colours: " + ", ".join(self._owned_hexes))

    def _add_owned_hex(self):
        hx = self._normalize_hex(self.hex_input.text())
        if not hx:
            return
        if hx not in self._owned_hexes:
            self._owned_hexes.append(hx)
            self._owned_hexes.sort()
            self._save_owned_hexes()
            self._render_owned_hexes()
        self.hex_input.clear()

    def _on_no_limit_toggled(self, checked: bool):
        for row in self._rows:
            row["btn"].setEnabled(not checked)
        self.state_changed.emit()

    def set_colors(self, bgr_list: list[tuple[int, int, int]]):
        while self._layout.count() > 3:
            item = self._layout.takeAt(3)
            if item.widget():
                item.widget().deleteLater()
        self._rows.clear()

        owned_set = set(self._owned_hexes)
        no_limit = self.no_limit.isChecked()

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

            label = QLabel(f"C{idx+1}  {hx}")
            label.setStyleSheet("font-size: 11px; color: #e0e0e0;")

            skip_btn = QPushButton("Skip")
            skip_btn.setCheckable(True)
            skip_btn.setFixedHeight(24)
            skip_btn.setToolTip("Highlighted means this colour will not be used.")
            should_skip = (not no_limit) and bool(owned_set) and (hx not in owned_set)
            skip_btn.setChecked(should_skip)
            self._sync_skip_style(skip_btn)
            skip_btn.toggled.connect(lambda state, b=skip_btn: self._sync_skip_style(b))
            skip_btn.toggled.connect(self.state_changed.emit)

            row_layout.addWidget(swatch)
            row_layout.addWidget(label)
            row_layout.addStretch()
            row_layout.addWidget(skip_btn)
            self._layout.addWidget(row_widget)

            skip_btn.setEnabled(not no_limit)
            self._rows.append({"idx": idx, "hex": hx, "btn": skip_btn})
        self.state_changed.emit()

    def _sync_skip_style(self, btn: QPushButton):
        if btn.isChecked():
            btn.setStyleSheet("background:#e94560; color:white; font-weight:bold;")
        else:
            btn.setStyleSheet("")

    def owned_indices(self) -> list[int]:
        if self.no_limit.isChecked():
            return []
        return [r["idx"] for r in self._rows if not r["btn"].isChecked()]

    def skipped_indices(self) -> list[int]:
        if self.no_limit.isChecked():
            return []
        return [r["idx"] for r in self._rows if r["btn"].isChecked()]


class ControlPanel(QWidget):
    colors_changed = pyqtSignal(int)
    settings_changed = pyqtSignal()
    color_logic_changed = pyqtSignal()
    generate_requested = pyqtSignal()
    export_requested = pyqtSignal()
    grid_preview_pressed = pyqtSignal()
    grid_preview_released = pyqtSignal()

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

        self.grid_hold_btn = QPushButton("Hold: show tile grid")
        self.grid_hold_btn.setCheckable(False)
        self.grid_hold_btn.setToolTip("Press and hold to overlay tile grid on preview.")
        self.grid_hold_btn.pressed.connect(self.grid_preview_pressed)
        self.grid_hold_btn.released.connect(self.grid_preview_released)
        dg.addWidget(self.grid_hold_btn, 5, 0, 1, 2)

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
