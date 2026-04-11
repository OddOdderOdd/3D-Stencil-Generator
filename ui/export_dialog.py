"""
ui/export_dialog.py
Modal dialog shown when the user clicks Export.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QRadioButton, QLineEdit, QFileDialog, QMessageBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from export.guide_writer import PlateInfo, generate_html_guide


class ExportDialog(QDialog):
    def __init__(
        self,
        plates: list[PlateInfo],
        current_output_dir: str,
        canvas_w_mm: float,
        canvas_h_mm: float,
        bed_w_mm: float,
        bed_h_mm: float,
        n_colors: int,
        n_cols: int,
        n_rows: int,
        parent=None,
    ):
        super().__init__(parent)
        self.plates = plates
        self.output_dir = current_output_dir
        self._canvas_w  = canvas_w_mm
        self._canvas_h  = canvas_h_mm
        self._bed_w     = bed_w_mm
        self._bed_h     = bed_h_mm
        self._n_colors  = n_colors
        self._n_cols    = n_cols
        self._n_rows    = n_rows

        self.setWindowTitle("Export Stencils")
        self.setFixedWidth(460)
        self.setModal(True)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # ── Title ───────────────────────────────────────────────────────────
        title = QLabel("📦  Export Stencils")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        info = QLabel(
            f"{len(self.plates)} plate(s) ready\n"
            f"Currently saved in:\n{self.output_dir}"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#999; font-size:10px;")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        # ── Format choice ────────────────────────────────────────────────────
        fmt_group = QGroupBox("Export format")
        fg = QVBoxLayout(fmt_group)
        self.opt_stl  = QRadioButton("STL files only")
        self.opt_both = QRadioButton("STL files + HTML step guide  (recommended)")
        self.opt_both.setChecked(True)
        fg.addWidget(self.opt_stl)
        fg.addWidget(self.opt_both)
        layout.addWidget(fmt_group)

        # ── Output directory ─────────────────────────────────────────────────
        dir_group = QGroupBox("Output directory")
        dg = QHBoxLayout(dir_group)
        self.dir_edit = QLineEdit(self.output_dir)
        browse = QPushButton("Browse…")
        browse.setFixedWidth(80)
        browse.clicked.connect(self._browse)
        dg.addWidget(self.dir_edit)
        dg.addWidget(browse)
        layout.addWidget(dir_group)

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        export_btn = QPushButton("✅  Export")
        export_btn.setDefault(True)
        export_btn.setStyleSheet(
            "background:#27ae60; color:#fff; font-weight:bold; padding:9px 22px;"
        )
        export_btn.clicked.connect(self._do_export)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(export_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Output directory", self.output_dir)
        if d:
            self.dir_edit.setText(d)

    def _do_export(self):
        dest = Path(self.dir_edit.text().strip())
        if not dest:
            QMessageBox.warning(self, "No directory", "Please choose an output directory.")
            return

        dest.mkdir(parents=True, exist_ok=True)
        current = Path(self.output_dir)

        # Copy STLs if the directory changed
        moved: list[PlateInfo] = []
        if dest.resolve() != current.resolve():
            for p in self.plates:
                src = p.stl_path
                if src.exists():
                    dst_path = dest / src.name
                    shutil.copy2(src, dst_path)
                    # Mutate PlateInfo so the guide references the new location
                    p.stl_path = dst_path
            moved = self.plates

        guide_path: Path | None = None
        if self.opt_both.isChecked():
            try:
                guide_path = generate_html_guide(
                    self.plates,
                    self._canvas_w, self._canvas_h,
                    self._bed_w, self._bed_h,
                    self._n_colors,
                    self._n_cols, self._n_rows,
                    dest,
                )
            except Exception as exc:
                QMessageBox.warning(
                    self, "Guide error",
                    f"Step guide generation failed:\n{exc}\n\nSTL files were still saved."
                )

        msg = (
            f"✅  Export complete!\n\n"
            f"{len(self.plates)} STL file(s) saved to:\n{dest}"
        )
        if guide_path:
            msg += f"\n\nStep guide: {guide_path.name}"

        QMessageBox.information(self, "Export complete", msg)
        self.accept()
