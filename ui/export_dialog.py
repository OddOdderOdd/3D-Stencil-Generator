"""
ui/export_dialog.py
Modal dialog shown when the user clicks Export.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

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
        self._canvas_w = canvas_w_mm
        self._canvas_h = canvas_h_mm
        self._bed_w = bed_w_mm
        self._bed_h = bed_h_mm
        self._n_colors = n_colors
        self._n_cols = n_cols
        self._n_rows = n_rows

        self.setWindowTitle("Export Stencils")
        self.setFixedWidth(500)
        self.setModal(True)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("📦  Export Stencils")
        title.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        info = QLabel(f"{len(self.plates)} plate(s) ready\nChoose folder + export name.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#999; font-size:10px;")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        fmt_group = QGroupBox("Export format")
        fg = QVBoxLayout(fmt_group)
        self.opt_stl = QRadioButton("STL files only")
        self.opt_both = QRadioButton("STL files + HTML step guide  (recommended)")
        self.opt_both.setChecked(True)
        fg.addWidget(self.opt_stl)
        fg.addWidget(self.opt_both)
        layout.addWidget(fmt_group)

        name_group = QGroupBox("Export name")
        ng = QVBoxLayout(name_group)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. dragon_poster")
        ng.addWidget(self.name_edit)
        layout.addWidget(name_group)

        dir_group = QGroupBox("Output directory (root)")
        dg = QHBoxLayout(dir_group)
        self.dir_edit = QLineEdit(self.output_dir)
        browse = QPushButton("Browse…")
        browse.setFixedWidth(80)
        browse.clicked.connect(self._browse)
        dg.addWidget(self.dir_edit)
        dg.addWidget(browse)
        layout.addWidget(dir_group)

        btn_row = QHBoxLayout()
        export_btn = QPushButton("✅  Export")
        export_btn.setDefault(True)
        export_btn.setStyleSheet("background:#27ae60; color:#fff; font-weight:bold; padding:9px 22px;")
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
        root = Path(self.dir_edit.text().strip())
        name = self.name_edit.text().strip()
        if not root:
            QMessageBox.warning(self, "No directory", "Please choose an output directory.")
            return
        if not name:
            QMessageBox.warning(self, "No export name", "Please enter an export name.")
            return

        safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)
        dest = root / safe_name
        dest.mkdir(parents=True, exist_ok=True)

        for p in self.plates:
            src = p.stl_path
            if src.exists():
                dst_path = dest / src.name
                shutil.copy2(src, dst_path)
                p.stl_path = dst_path

        guide_path: Path | None = None
        if self.opt_both.isChecked():
            try:
                guide_path = generate_html_guide(
                    self.plates,
                    self._canvas_w,
                    self._canvas_h,
                    self._bed_w,
                    self._bed_h,
                    self._n_colors,
                    self._n_cols,
                    self._n_rows,
                    dest,
                )
            except Exception as exc:
                QMessageBox.warning(self, "Guide error", f"Step guide generation failed:\n{exc}\n\nSTL files were still saved.")

        msg = f"✅  Export complete!\n\n{len(self.plates)} STL file(s) saved to:\n{dest}"
        if guide_path:
            msg += f"\n\nStep guide: {guide_path.name}"

        QMessageBox.information(self, "Export complete", msg)
        self.accept()
