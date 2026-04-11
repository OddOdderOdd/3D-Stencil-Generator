"""
ui/panels.py
Left-side control panel: all input widgets grouped into QGroupBoxes.
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
    QCheckBox, QSlider, QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor

from config import (
    DEFAULT_CANVAS_W_MM, DEFAULT_CANVAS_H_MM,
    DEFAULT_BED_W_MM, DEFAULT_BED_H_MM,
    DEFAULT_N_COLORS, DEFAULT_THICKNESS_MM,
    DEFAULT_TOLERANCE_PCT, DEFAULT_THICKEN_EDGES,
)


class ColourOwnershipBar(QWidget):
    """
    A vertical list of (swatch + checkbox) rows — one per quantised colour.
    The checkbox means "I own this colour / include it in generation."
    Unchecked colours are skipped by the worker, same as tolerance filtering.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._layout.setSpacing(4)
        self._rows: list[tuple[QFrame, QCheckBox]] = []

    # Keep old name so existing callers (swatch_bar.set_colors) still work
    def set_colors(self, bgr_list: list[tuple[int, int, int]]):
        # Clear existing rows
        for swatch, cb in self._rows:
            swatch.deleteLater()
            cb.deleteLater()
        self._rows.clear()
        # Also remove all child widgets from layout
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, bgr in enumerate(bgr_list):
            r, g, b = int(bgr[2]), int(bgr[1]), int(bgr[0])
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            swatch = QFrame()
            swatch.setFixedSize(24, 24)
            swatch.setStyleSheet(
                f"background: rgb({r},{g},{b}); border-radius: 4px; "
                f"border: 1.5px solid rgba(255,255,255,0.25);"
            )

            hex_str = f"#{r:02x}{g:02x}{b:02x}"
            cb = QCheckBox(f"C{idx+1}  {hex_str}")
            cb.setChecked(True)          # owned by default
            cb.setToolTip(
                f"Colour {idx+1}: {hex_str}  rgb({r},{g},{b})\n"
                "Uncheck to skip this colour during generation."
            )
            cb.setStyleSheet("font-size: 11px; color: #e0e0e0;")

            row_layout.addWidget(swatch)
            row_layout.addWidget(cb)
            row_layout.addStretch()
            self._layout.addWidget(row_widget)
            self._rows.append((swatch, cb))

    def owned_indices(self) -> list[int]:
        """Return 0-based indices of colours whose checkbox is checked."""
        return [i for i, (_, cb) in enumerate(self._rows) if cb.isChecked()]

    def all_owned(self) -> bool:
        return all(cb.isChecked() for _, cb in self._rows)

    def set_all_checked(self, checked: bool):
        """Check or uncheck every colour at once."""""
        for _, cb in self._rows:
            cb.setChecked(checked)

    # Keep backward compat for tests that check _squares
    @property
    def _squares(self):
        return [sw for sw, _ in self._rows]


class ControlPanel(QWidget):
    """
    All parameter controls.  Emits no signals itself — the MainWindow
    reads values directly when the Generate button is pressed.
    """

    # Emitted when the user changes n_colors so the preview can refresh
    colors_changed = pyqtSignal(int)
    preview_requested = pyqtSignal()
    generate_requested = pyqtSignal()
    export_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(330)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 8, 0)
        root.setSpacing(10)

        # ── Title ──────────────────────────────────────────────────────────
        title = QLabel("3D Stencil Generator")
        title.setFont(QFont("Segoe UI", 15, QFont.Bold))
        title.setStyleSheet("color: #e94560;")
        root.addWidget(title)

        sub = QLabel("Image → 3D-printable spray-paint stencils")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #777; font-size: 11px; margin-bottom: 4px;")
        root.addWidget(sub)

        # ── Image ──────────────────────────────────────────────────────────
        img_group = QGroupBox("Image")
        ig = QVBoxLayout(img_group)
        self.upload_btn = QPushButton("📂  Upload Image…")
        self.img_info   = QLabel("No image loaded")
        self.img_info.setStyleSheet("color: #888; font-size: 10px;")
        self.img_info.setWordWrap(True)
        ig.addWidget(self.upload_btn)
        ig.addWidget(self.img_info)
        root.addWidget(img_group)

        # ── Dimensions ─────────────────────────────────────────────────────
        dim_group = QGroupBox("Dimensions (mm)")
        dg = QGridLayout(dim_group)
        dg.setVerticalSpacing(6)

        def _dspin(val, lo=1, hi=5000, step=10):
            s = QDoubleSpinBox()
            s.setRange(lo, hi); s.setValue(val)
            s.setSingleStep(step); s.setSuffix(" mm")
            s.setDecimals(1)
            return s

        dg.addWidget(QLabel("Canvas W:"),  0, 0)
        self.canvas_w = _dspin(DEFAULT_CANVAS_W_MM)
        dg.addWidget(self.canvas_w, 0, 1)

        dg.addWidget(QLabel("Canvas H:"),  1, 0)
        self.canvas_h = _dspin(DEFAULT_CANVAS_H_MM)
        dg.addWidget(self.canvas_h, 1, 1)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #333;"); dg.addWidget(sep, 2, 0, 1, 2)

        dg.addWidget(QLabel("Bed W:"),     3, 0)
        self.bed_w = _dspin(DEFAULT_BED_W_MM)
        dg.addWidget(self.bed_w, 3, 1)

        dg.addWidget(QLabel("Bed H:"),     4, 0)
        self.bed_h = _dspin(DEFAULT_BED_H_MM)
        dg.addWidget(self.bed_h, 4, 1)

        root.addWidget(dim_group)

        # ── Stencil parameters ─────────────────────────────────────────────
        param_group = QGroupBox("Stencil Parameters")
        pg = QGridLayout(param_group)
        pg.setVerticalSpacing(6)

        pg.addWidget(QLabel("Colours (N):"), 0, 0)
        self.n_colors = QSpinBox()
        self.n_colors.setRange(2, 16)
        self.n_colors.setValue(DEFAULT_N_COLORS)
        self.n_colors.valueChanged.connect(self.colors_changed)
        pg.addWidget(self.n_colors, 0, 1)

        pg.addWidget(QLabel("Thickness:"), 1, 0)
        self.thickness = QDoubleSpinBox()
        self.thickness.setRange(0.4, 10.0)
        self.thickness.setValue(DEFAULT_THICKNESS_MM)
        self.thickness.setSingleStep(0.1)
        self.thickness.setSuffix(" mm")
        self.thickness.setDecimals(1)
        pg.addWidget(self.thickness, 1, 1)

        self.thicken_edges = QCheckBox("Thicken edges  (alignment lip +0.4 mm)")
        self.thicken_edges.setChecked(DEFAULT_THICKEN_EDGES)
        pg.addWidget(self.thicken_edges, 2, 0, 1, 2)

        root.addWidget(param_group)

        # ── Tolerance ──────────────────────────────────────────────────────
        tol_group = QGroupBox("Tolerance")
        tg = QVBoxLayout(tol_group)

        tol_row = QHBoxLayout()
        tol_row.addWidget(QLabel("Skip plate if colour coverage <"))
        self.tol_label = QLabel(f"{int(DEFAULT_TOLERANCE_PCT)}%")
        self.tol_label.setStyleSheet("color: #e94560; font-weight: bold; min-width: 36px;")
        tol_row.addWidget(self.tol_label)
        tg.addLayout(tol_row)

        self.tol_slider = QSlider(Qt.Horizontal)
        self.tol_slider.setRange(0, 50)
        self.tol_slider.setValue(int(DEFAULT_TOLERANCE_PCT))
        self.tol_slider.setTickInterval(5)
        self.tol_slider.setTickPosition(QSlider.TicksBelow)
        self.tol_slider.valueChanged.connect(
            lambda v: self.tol_label.setText(f"{v}%")
        )
        tg.addWidget(self.tol_slider)

        root.addWidget(tol_group)

        # ── Palette preview ────────────────────────────────────────────────
        pal_group = QGroupBox("Colour Ownership")
        pg2 = QVBoxLayout(pal_group)
        self.swatch_bar = ColourOwnershipBar()
        pg2.addWidget(self.swatch_bar)

        # Select All / None row
        sel_row = QHBoxLayout()
        self.select_all_btn  = QPushButton("All")
        self.select_none_btn = QPushButton("None")
        for btn in (self.select_all_btn, self.select_none_btn):
            btn.setFixedHeight(22)
            btn.setStyleSheet("font-size:10px; padding:0 8px;")
        self.select_all_btn.clicked.connect(
            lambda: self.swatch_bar.set_all_checked(True))
        self.select_none_btn.clicked.connect(
            lambda: self.swatch_bar.set_all_checked(False))
        sel_row.addStretch()
        sel_row.addWidget(self.select_all_btn)
        sel_row.addWidget(self.select_none_btn)
        pg2.addLayout(sel_row)

        self.preview_btn = QPushButton("🔍  Preview quantised colours")
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self.preview_requested)
        pg2.addWidget(self.preview_btn)
        root.addWidget(pal_group)

        root.addStretch()

        # ── Action buttons ─────────────────────────────────────────────────
        self.generate_btn = QPushButton("⚙️   Generate Stencils")
        self.generate_btn.setEnabled(False)
        self.generate_btn.setStyleSheet(
            "background:#e94560; color:#fff; font-weight:bold; "
            "font-size:13px; padding:10px; border-radius:7px;"
        )
        self.generate_btn.clicked.connect(self.generate_requested)
        root.addWidget(self.generate_btn)

        self.export_btn = QPushButton("📦  Export…")
        self.export_btn.setEnabled(False)
        self.export_btn.setStyleSheet("font-size:12px; padding:8px; border-radius:7px;")
        self.export_btn.clicked.connect(self.export_requested)
        root.addWidget(self.export_btn)

    # ── Convenience accessors ──────────────────────────────────────────────

    def get_params(self) -> dict:
        return {
            "canvas_w_mm":          self.canvas_w.value(),
            "canvas_h_mm":          self.canvas_h.value(),
            "bed_w_mm":             self.bed_w.value(),
            "bed_h_mm":             self.bed_h.value(),
            "n_colors":             self.n_colors.value(),
            "thickness_mm":         self.thickness.value(),
            "thicken_edges":        self.thicken_edges.isChecked(),
            "tolerance_pct":        float(self.tol_slider.value()),
            "owned_colour_indices": self.swatch_bar.owned_indices(),
        }

    def set_image_info(self, filename: str, w: int, h: int):
        self.img_info.setText(f"✓ {filename}  ({w}×{h} px)")

    def set_generating(self, active: bool):
        self.generate_btn.setEnabled(not active)
        self.generate_btn.setText("⏳  Generating…" if active else "⚙️   Generate Stencils")
        self.upload_btn.setEnabled(not active)

    def set_export_ready(self, ready: bool):
        self.export_btn.setEnabled(ready)
