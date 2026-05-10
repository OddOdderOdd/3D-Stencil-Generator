"""
workers/generator_thread.py
============================
QThread that runs the full stencil generation pipeline off the UI thread.

Generation strategy
-------------------
There are two mutually exclusive modes:

MODE A — Palette mode  (background enabled OR at least one owned colour enabled)
    1. Build an active palette: background colour (if enabled) + enabled owned
       colours, in that order.
    2. Assign EVERY pixel in the canvas image to its nearest palette entry by
       Euclidean RGB distance (core/palette_mapper.py).
       → No pixel is left unassigned; every pixel goes to the best available
         colour from the paints the user actually owns.
    3. Generate one stencil plate per palette entry per tile.
    K-means is NOT used for mask generation in this mode — only for the
    quantised preview in the UI.

MODE B — Computer colour mode  (no background, no owned colours)
    Classic K-means behaviour.  One plate per active cluster per tile.

Signals
-------
progress(int)        0–100
log(str)             single log line
plate_ready(dict)    after each STL written
finished(list)       list[PlateInfo]
error(str)           fatal error
"""

from __future__ import annotations

import traceback
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from config import PX_PER_MM
from core.quantizer import quantize, QuantizeResult
from core.palette_mapper import build_palette_map, PaletteEntry, PaletteMap
from core.tiler import (
    compute_tile_grid, get_tile_mask, canvas_size_px,
)
from core.geometry import mask_to_plate
from core.mesh_builder import build_mesh
from export.stl_writer import export_stl
from export.guide_writer import PlateInfo


def _hex_to_rgb(hx: str) -> tuple[int, int, int]:
    hx = hx.lstrip("#")
    return int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)


def _coverage_of_mask(mask: np.ndarray) -> float:
    total = mask.size
    if total == 0:
        return 0.0
    return 100.0 * float(np.count_nonzero(mask)) / total


class GeneratorWorker(QThread):
    progress    = pyqtSignal(int)
    log         = pyqtSignal(str)
    plate_ready = pyqtSignal(dict)
    finished    = pyqtSignal(list)
    error       = pyqtSignal(str)

    def __init__(self, params: dict, parent=None):
        super().__init__(parent)
        self.params = params
        self._abort = False

    def abort(self):
        self._abort = True

    def _log(self, msg: str):
        self.log.emit(msg)

    def _progress(self, value: int):
        self.progress.emit(max(0, min(100, value)))

    def run(self):
        try:
            self._generate()
        except Exception:
            self.error.emit(traceback.format_exc())

    # ── shared plate builder ──────────────────────────────────────────────────

    def _run_plate(
        self,
        mask: np.ndarray,
        tile,
        plate_id: str,
        color_rgb: tuple[int, int, int],
        coverage_pct: float,
        color_idx: int,
        thickness_mm: float,
        thicken_edges: bool,
        output_dir: Path,
        plates: list,
    ) -> bool:
        plate_poly, n_bridges = mask_to_plate(mask, tile.w_mm, tile.h_mm)
        if plate_poly is None:
            self._log(f"    {plate_id}: empty geometry — skipped")
            return False

        bridge_note = f", {n_bridges} bridge(s)" if n_bridges else ""
        self._log(f"    {plate_id}: polygon OK{bridge_note}")

        mesh = build_mesh(
            plate_poly, tile.w_mm, tile.h_mm,
            plate_id, thickness_mm, thicken_edges,
        )
        if mesh is None:
            self._log(f"    {plate_id}: mesh generation failed — skipped")
            return False

        try:
            stl_path = export_stl(mesh, plate_id, output_dir)
            self._log(f"    ✓  {stl_path.name}")
        except Exception as exc:
            self._log(f"    ✗  STL export failed: {exc}")
            return False

        info = PlateInfo(
            plate_id=plate_id,
            color_idx=color_idx,
            tile_label=tile.label,
            tile_col=tile.col,
            tile_row=tile.row,
            color_rgb=color_rgb,
            coverage_pct=round(coverage_pct, 2),
            n_bridges=n_bridges,
            stl_path=stl_path,
            thickness_mm=thickness_mm,
            thickened=thicken_edges,
        )
        plates.append(info)
        self.plate_ready.emit({
            "plate_id": plate_id,
            "color_rgb": color_rgb,
            "coverage_pct": info.coverage_pct,
            "n_bridges": n_bridges,
            "stl_path": str(stl_path),
        })
        return True

    # ── tile mask helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _tile_mask_from_palette(pmap: PaletteMap, tile, label: str) -> np.ndarray:
        region = pmap.assignment_map[tile.y0_px:tile.y1_px, tile.x0_px:tile.x1_px]
        idx = pmap._index_of(label)
        if idx < 0:
            return np.zeros((tile.h_px, tile.w_px), dtype=np.uint8)
        return np.where(region == idx, np.uint8(255), np.uint8(0))

    # ── main pipeline ─────────────────────────────────────────────────────────

    def _generate(self):
        p = self.params
        image_path         = p["image_path"]
        canvas_w_mm        = float(p["canvas_w_mm"])
        canvas_h_mm        = float(p["canvas_h_mm"])
        bed_w_mm           = float(p["bed_w_mm"])
        bed_h_mm           = float(p["bed_h_mm"])
        requested_n_colors = int(p["n_colors"])
        thickness_mm       = float(p["thickness_mm"])
        thicken_edges      = bool(p["thicken_edges"])
        tolerance_pct      = float(p["tolerance_pct"])
        output_dir         = Path(p["output_dir"])

        active_computer_indices: list[int] = p.get("active_computer_indices") or []
        active_owned_hexes: list[str]      = p.get("active_owned_hexes") or []
        background_hex: str                = p.get("background_hex", "#FFFFFF")
        background_enabled: bool           = bool(p.get("background_enabled", False))
        owned_thresholds: dict[str, float] = p.get("owned_thresholds") or {}

        # ── Step 1 — Load & resize ────────────────────────────────────────────
        self._log("📷  Loading image…")
        raw = cv2.imread(image_path)
        if raw is None:
            self.error.emit(f"Cannot read image: {image_path}")
            return

        canvas_w_px, canvas_h_px = canvas_size_px(canvas_w_mm, canvas_h_mm)
        self._log(
            f"    Canvas: {canvas_w_px}×{canvas_h_px} px "
            f"({canvas_w_mm:.0f}×{canvas_h_mm:.0f} mm @ {PX_PER_MM} px/mm)"
        )
        scaled = cv2.resize(raw, (canvas_w_px, canvas_h_px), interpolation=cv2.INTER_AREA)

        if self._abort:
            self._log("Aborted.")
            return

        # ── Step 2 — Tile grid ────────────────────────────────────────────────
        grid = compute_tile_grid(canvas_w_mm, canvas_h_mm, bed_w_mm, bed_h_mm)
        self._log(
            f"📐  Tile grid: {grid.n_cols}×{grid.n_rows} = {len(grid.tiles)} tile(s)"
        )

        plates: list[PlateInfo] = []
        use_palette_mode = background_enabled or bool(active_owned_hexes)

        # ══════════════════════════════════════════════════════════════════════
        # MODE A — palette nearest-colour assignment
        # ══════════════════════════════════════════════════════════════════════
        if use_palette_mode:
            self._log("\n🎨  Mode: palette assignment")

            # ── Background: always a solid full plate, not pixel-assigned ────
            color_counter = 0
            if background_enabled:
                color_counter += 1
                bg_rgb = _hex_to_rgb(background_hex)
                self._log(f"\n  B0 background ({background_hex}) — solid plate")
                for tile in grid.tiles:
                    if self._abort:
                        break
                    solid_mask = np.full((tile.h_px, tile.w_px), 255, dtype=np.uint8)
                    self._log(f"\n  🔲  {tile.label}")
                    self._run_plate(
                        solid_mask, tile, f"B0_{tile.label}", bg_rgb, 100.0,
                        color_counter, thickness_mm, thicken_edges,
                        output_dir, plates,
                    )

            # ── Owned colours: nearest-within-threshold pixel assignment ─────
            owned_palette: list[PaletteEntry] = []
            for rank, hx in enumerate(active_owned_hexes, start=1):
                owned_palette.append(PaletteEntry(label=f"O{rank}", rgb=_hex_to_rgb(hx)))
                self._log(f"    O{rank} owned: {hx}")

            if owned_palette:
                thresh_by_label: dict[str, float] = {}
                for rank, hx in enumerate(active_owned_hexes, start=1):
                    if hx in owned_thresholds:
                        thresh_by_label[f"O{rank}"] = owned_thresholds[hx]

                self._log("    Building pixel-to-owned-colour assignment map…")
                if thresh_by_label:
                    self._log(f"    Thresholds: { {k: round(v) for k, v in thresh_by_label.items()} }")
                pmap = build_palette_map(scaled, owned_palette, thresholds=thresh_by_label)
                self._progress(15)

                if self._abort:
                    self._log("Aborted.")
                    return

                total_work = max(1, len(owned_palette) * len(grid.tiles))
                work_done  = 0

                for entry in owned_palette:
                    if self._abort:
                        break
                    color_counter += 1
                    label  = entry.label
                    rgb    = entry.rgb
                    hx_str = "#{:02X}{:02X}{:02X}".format(*rgb)
                    self._log(f"\n  Layer {label} ({hx_str})")

                    for tile in grid.tiles:
                        if self._abort:
                            break
                        work_done += 1
                        self._progress(15 + int(80 * work_done / total_work))
                        self._log(f"\n  🔲  {tile.label}")

                        mask     = self._tile_mask_from_palette(pmap, tile, label)
                        coverage = _coverage_of_mask(mask)

                        if coverage < tolerance_pct:
                            self._log(
                                f"    {label}: {coverage:.1f}% — skipped (< {tolerance_pct}%)"
                            )
                            continue

                        self._log(f"    {label}: {coverage:.1f}% — generating…")
                        self._run_plate(
                            mask, tile, f"{label}_{tile.label}", rgb, coverage,
                            color_counter, thickness_mm, thicken_edges,
                            output_dir, plates,
                        )
            else:
                self._progress(15)

        # ══════════════════════════════════════════════════════════════════════
        # MODE B — classic K-means computer colours
        # ══════════════════════════════════════════════════════════════════════
        else:
            self._log(
                f"\n💻  Mode: computer colours ({len(active_computer_indices)} active)"
            )
            self._log(f"🎨  Quantising to {requested_n_colors} colours (K-means)…")
            qr: QuantizeResult = quantize(scaled, requested_n_colors)
            n_colors = qr.n_colors
            if n_colors != requested_n_colors:
                self._log(f"    Requested {requested_n_colors}, effective {n_colors}")
            self._progress(15)

            if self._abort:
                self._log("Aborted.")
                return

            total_work = max(1, len(active_computer_indices) * len(grid.tiles))
            work_done  = 0
            comp_rank  = 0

            for color_idx in active_computer_indices:
                if self._abort:
                    break
                comp_rank += 1
                bgr      = qr.centers_bgr[color_idx]
                comp_rgb = (int(bgr[2]), int(bgr[1]), int(bgr[0]))
                hx_str   = "#{:02X}{:02X}{:02X}".format(*comp_rgb)
                lbl      = f"C{comp_rank}"
                self._log(f"\n  Computer {lbl} — cluster {color_idx+1} ({hx_str})")

                for tile in grid.tiles:
                    if self._abort:
                        break
                    work_done += 1
                    self._progress(15 + int(80 * work_done / total_work))
                    self._log(f"\n  🔲  {tile.label}")

                    mask     = get_tile_mask(qr.label_map, tile, color_idx)
                    coverage = _coverage_of_mask(mask)

                    if coverage < tolerance_pct:
                        self._log(
                            f"    {lbl}: {coverage:.1f}% — skipped (< {tolerance_pct}%)"
                        )
                        continue

                    self._log(f"    {lbl}: {coverage:.1f}% — generating…")
                    self._run_plate(
                        mask, tile, f"{lbl}_{tile.label}", comp_rgb, coverage,
                        comp_rank, thickness_mm, thicken_edges,
                        output_dir, plates,
                    )

        # ── Done ─────────────────────────────────────────────────────────────
        self._progress(100)
        self._log(f"\n🎉  Done — {len(plates)} plate(s) generated in {output_dir}")
        self.finished.emit(plates)
