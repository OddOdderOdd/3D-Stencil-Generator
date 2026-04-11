"""
core/tiler.py
Canvas-to-tile decomposition.  Everything here works in two coordinate systems:
  * pixel space  — integer pixel indices inside the scaled canvas image
  * mm space     — floating-point millimetres, used for mesh generation
"""

from __future__ import annotations
from dataclasses import dataclass, field

import math
import numpy as np

from config import PX_PER_MM


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Tile:
    col: int            # 0-based column index (left → right)
    row: int            # 0-based row index    (top  → bottom)
    x0_px: int          # left edge in canvas pixel space
    y0_px: int          # top  edge in canvas pixel space
    w_px: int           # pixel width  (may be < full bed width at right edge)
    h_px: int           # pixel height (may be < full bed height at bottom edge)

    @property
    def x1_px(self) -> int:
        return self.x0_px + self.w_px

    @property
    def y1_px(self) -> int:
        return self.y0_px + self.h_px

    @property
    def w_mm(self) -> float:
        return self.w_px / PX_PER_MM

    @property
    def h_mm(self) -> float:
        return self.h_px / PX_PER_MM

    @property
    def label(self) -> str:
        """Human-readable tile label, e.g. 'Tile_B2'."""
        col_letter = chr(ord("A") + self.col)
        return f"Tile_{col_letter}{self.row + 1}"


@dataclass
class TileGrid:
    tiles: list[Tile] = field(default_factory=list)
    n_cols: int = 0
    n_rows: int = 0
    canvas_w_px: int = 0
    canvas_h_px: int = 0


# ── Public API ────────────────────────────────────────────────────────────────

def canvas_size_px(canvas_w_mm: float, canvas_h_mm: float) -> tuple[int, int]:
    """Return (width_px, height_px) for the scaled canvas."""
    return (
        max(1, round(canvas_w_mm * PX_PER_MM)),
        max(1, round(canvas_h_mm * PX_PER_MM)),
    )


def compute_tile_grid(
    canvas_w_mm: float,
    canvas_h_mm: float,
    bed_w_mm: float,
    bed_h_mm: float,
) -> TileGrid:
    """
    Divide the canvas (given in mm) into a grid of printer-bed-sized tiles.
    Edge tiles are smaller when the canvas is not an exact multiple of the bed.
    """
    canvas_w_px, canvas_h_px = canvas_size_px(canvas_w_mm, canvas_h_mm)
    tile_w_px = max(1, round(bed_w_mm * PX_PER_MM))
    tile_h_px = max(1, round(bed_h_mm * PX_PER_MM))

    n_cols = math.ceil(canvas_w_px / tile_w_px)
    n_rows = math.ceil(canvas_h_px / tile_h_px)

    tiles: list[Tile] = []
    for row in range(n_rows):
        for col in range(n_cols):
            x0 = col * tile_w_px
            y0 = row * tile_h_px
            w  = min(tile_w_px, canvas_w_px - x0)
            h  = min(tile_h_px, canvas_h_px - y0)
            if w <= 0 or h <= 0:
                continue   # edge tile with zero area — skip
            tiles.append(Tile(col=col, row=row, x0_px=x0, y0_px=y0, w_px=w, h_px=h))

    return TileGrid(
        tiles=tiles,
        n_cols=n_cols,
        n_rows=n_rows,
        canvas_w_px=canvas_w_px,
        canvas_h_px=canvas_h_px,
    )


def get_tile_mask(label_map: np.ndarray, tile: Tile, color_idx: int) -> np.ndarray:
    """
    Extract the binary mask (uint8, 0 or 255) for *color_idx* within *tile*.

    Parameters
    ----------
    label_map : np.ndarray  shape (H_canvas, W_canvas), int32
    tile      : Tile
    color_idx : int

    Returns
    -------
    np.ndarray  shape (tile.h_px, tile.w_px), uint8
    """
    region = label_map[tile.y0_px:tile.y1_px, tile.x0_px:tile.x1_px]
    mask = np.where(region == color_idx, np.uint8(255), np.uint8(0))
    return mask


def get_color_coverage(label_map: np.ndarray, tile: Tile, color_idx: int) -> float:
    """
    Return the percentage of *tile* pixels that belong to *color_idx* (0–100).
    """
    region = label_map[tile.y0_px:tile.y1_px, tile.x0_px:tile.x1_px]
    total = region.size
    if total == 0:
        return 0.0
    count = int(np.sum(region == color_idx))
    return count / total * 100.0


def should_generate_plate(coverage_pct: float, tolerance_pct: float) -> bool:
    return coverage_pct >= tolerance_pct
