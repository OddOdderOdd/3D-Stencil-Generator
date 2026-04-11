"""
workers/generator_thread.py
QThread that runs the full stencil generation pipeline off the UI thread.

Signals
-------
progress(int)        0–100 progress bar value
log(str)             single log line (append to console)
plate_ready(dict)    emitted after each STL is written (for live preview)
finished(list)       list of PlateInfo dicts when all plates are done
error(str)           fatal error message
"""

from __future__ import annotations

import os
import traceback
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from config import PX_PER_MM
from core.quantizer import quantize, QuantizeResult
from core.tiler import (
    compute_tile_grid, get_tile_mask, get_color_coverage,
    should_generate_plate, canvas_size_px,
)
from core.geometry import mask_to_plate
from core.mesh_builder import build_mesh
from export.stl_writer import export_stl
from export.guide_writer import PlateInfo


class GeneratorWorker(QThread):
    progress   = pyqtSignal(int)
    log        = pyqtSignal(str)
    plate_ready = pyqtSignal(dict)
    finished   = pyqtSignal(list)   # list[PlateInfo]
    error      = pyqtSignal(str)

    def __init__(self, params: dict, parent=None):
        """
        params keys
        -----------
        image_path      : str
        canvas_w_mm     : float
        canvas_h_mm     : float
        bed_w_mm        : float
        bed_h_mm        : float
        n_colors        : int
        thickness_mm    : float
        thicken_edges   : bool
        tolerance_pct   : float
        output_dir      : str
        """
        super().__init__(parent)
        self.params = params
        self._abort = False

    def abort(self):
        self._abort = True

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log(self, msg: str):
        self.log.emit(msg)

    def _progress(self, value: int):
        self.progress.emit(max(0, min(100, value)))

    # ── Main entry ────────────────────────────────────────────────────────────

    def run(self):
        try:
            self._generate()
        except Exception:
            self.error.emit(traceback.format_exc())

    def _generate(self):
        p = self.params
        image_path   = p["image_path"]
        canvas_w_mm  = float(p["canvas_w_mm"])
        canvas_h_mm  = float(p["canvas_h_mm"])
        bed_w_mm     = float(p["bed_w_mm"])
        bed_h_mm     = float(p["bed_h_mm"])
        n_colors     = int(p["n_colors"])
        thickness_mm = float(p["thickness_mm"])
        # None or empty list both mean "all owned"
        _owned = p.get("owned_colour_indices", None)
        owned_indices = _owned if _owned else None
        thicken_edges = bool(p["thicken_edges"])
        tolerance_pct = float(p["tolerance_pct"])
        output_dir   = Path(p["output_dir"])

        # ── Step 1 — Load & resize image ─────────────────────────────────────
        self._log("📷  Loading image…")
        raw = cv2.imread(image_path)
        if raw is None:
            self.error.emit(f"Cannot read image: {image_path}")
            return

        canvas_w_px, canvas_h_px = canvas_size_px(canvas_w_mm, canvas_h_mm)
        self._log(f"    Canvas: {canvas_w_px}×{canvas_h_px} px "
                  f"({canvas_w_mm:.0f}×{canvas_h_mm:.0f} mm @ {PX_PER_MM} px/mm)")
        scaled = cv2.resize(raw, (canvas_w_px, canvas_h_px), interpolation=cv2.INTER_AREA)

        if self._abort:
            self._log("Aborted.")
            return

        # ── Step 2 — K-means quantization ────────────────────────────────────
        self._log(f"🎨  Quantising to {n_colors} colours (K-means)…")
        qr: QuantizeResult = quantize(scaled, n_colors)
        self._progress(10)

        if self._abort:
            self._log("Aborted.")
            return

        # ── Step 3 — Tile grid ────────────────────────────────────────────────
        grid = compute_tile_grid(canvas_w_mm, canvas_h_mm, bed_w_mm, bed_h_mm)
        total_tiles  = len(grid.tiles)
        total_plates = total_tiles * n_colors   # upper bound for progress
        self._log(f"📐  Tile grid: {grid.n_cols}×{grid.n_rows} = {total_tiles} tile(s)")

        plates: list[PlateInfo] = []
        plate_idx = 0

        for tile in grid.tiles:
            if self._abort:
                self._log("⚠️  Aborted.")
                break

            self._log(f"\n🔲  {tile.label} ({tile.w_mm:.1f}×{tile.h_mm:.1f} mm)")

            for color_idx in range(n_colors):
                if self._abort:
                    break

                plate_idx += 1
                prog = 10 + int(85 * plate_idx / total_plates)
                self._progress(prog)

                # ── Coverage check ────────────────────────────────────────────
                # Skip colours the user has marked as not owned
                if owned_indices is not None and color_idx not in owned_indices:
                    self._log(f"    C{color_idx+1}: skipped (not owned)")
                    continue

                coverage = get_color_coverage(qr.label_map, tile, color_idx)
                if not should_generate_plate(coverage, tolerance_pct):
                    self._log(f"    C{color_idx+1}: {coverage:.1f}% — skipped (< {tolerance_pct}%)")
                    continue

                self._log(f"    C{color_idx+1}: {coverage:.1f}% — generating…")

                # ── Build mask ────────────────────────────────────────────────
                mask = get_tile_mask(qr.label_map, tile, color_idx)

                # ── Geometry pipeline ─────────────────────────────────────────
                plate_poly, n_bridges = mask_to_plate(mask, tile.w_mm, tile.h_mm)
                if plate_poly is None:
                    self._log(f"    C{color_idx+1}: empty geometry — skipped")
                    continue

                bridge_note = f", {n_bridges} bridge(s)" if n_bridges else ""
                self._log(f"    C{color_idx+1}: polygon OK{bridge_note}")

                # ── Plate ID ──────────────────────────────────────────────────
                plate_id = f"C{color_idx+1}_{tile.label}"

                # ── 3D mesh ───────────────────────────────────────────────────
                mesh = build_mesh(
                    plate_poly,
                    tile.w_mm, tile.h_mm,
                    plate_id,
                    thickness_mm,
                    thicken_edges,
                )
                if mesh is None:
                    self._log(f"    C{color_idx+1}: mesh generation failed — skipped")
                    continue

                # ── Export STL ────────────────────────────────────────────────
                try:
                    stl_path = export_stl(mesh, plate_id, output_dir)
                    self._log(f"    ✓  {stl_path.name}")
                except Exception as exc:
                    self._log(f"    ✗  STL export failed: {exc}")
                    continue

                # ── Collect metadata ──────────────────────────────────────────
                bgr = qr.centers_bgr[color_idx]
                rgb = (int(bgr[2]), int(bgr[1]), int(bgr[0]))

                info = PlateInfo(
                    plate_id=plate_id,
                    color_idx=color_idx + 1,
                    tile_label=tile.label,
                    tile_col=tile.col,
                    tile_row=tile.row,
                    color_rgb=rgb,
                    coverage_pct=round(coverage, 2),
                    n_bridges=n_bridges,
                    stl_path=stl_path,
                    thickness_mm=thickness_mm,
                    thickened=thicken_edges,
                )
                plates.append(info)
                self.plate_ready.emit({
                    "plate_id": plate_id,
                    "color_rgb": rgb,
                    "coverage_pct": info.coverage_pct,
                    "n_bridges": n_bridges,
                    "stl_path": str(stl_path),
                })

        self._progress(100)
        self._log(f"\n🎉  Done — {len(plates)} plate(s) generated in {output_dir}")
        self.finished.emit(plates)
