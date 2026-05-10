"""
core/palette_mapper.py
======================
Nearest-within-threshold pixel assignment, with highest-threshold tiebreak.

Assignment rules
----------------
1. For each pixel, find all owned colours whose threshold the pixel falls within.
2. If exactly one → that colour gets the pixel.
3. If multiple → the one with the HIGHEST threshold wins.
   (Rationale: a higher threshold means the user wants that colour to claim
   aggressively, so it takes priority over more selective colours.)
4. If none → pixel is unassigned (-1). Background (B0) is a separate solid
   plate and does not participate in pixel assignment.

Public API
----------
build_palette_map(image_bgr, owned_entries, thresholds=None)  -> PaletteMap
PaletteMap.mask_for(label)      -> np.ndarray uint8 (H, W)
PaletteMap.coverage_for(label)  -> float (0-100)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class PaletteEntry:
    label: str
    rgb: tuple[int, int, int]


@dataclass
class PaletteMap:
    # shape (H, W), dtype int16; -1 = unassigned
    assignment_map: np.ndarray
    palette: list[PaletteEntry]

    def mask_for(self, label: str) -> np.ndarray:
        idx = self._index_of(label)
        if idx < 0:
            h, w = self.assignment_map.shape
            return np.zeros((h, w), dtype=np.uint8)
        return np.where(self.assignment_map == idx, np.uint8(255), np.uint8(0))

    def coverage_for(self, label: str) -> float:
        total = self.assignment_map.size
        if total == 0:
            return 0.0
        idx = self._index_of(label)
        if idx < 0:
            return 0.0
        return 100.0 * float(np.sum(self.assignment_map == idx)) / total

    def _index_of(self, label: str) -> int:
        for i, e in enumerate(self.palette):
            if e.label == label:
                return i
        return -1


DEFAULT_THRESHOLD = 80.0


def build_palette_map(
    image_bgr: np.ndarray,
    owned_entries: Sequence[PaletteEntry],
    thresholds: dict[str, float] | None = None,
) -> PaletteMap:
    """
    Assign pixels to owned colours using highest-threshold-wins tiebreak.

    Parameters
    ----------
    image_bgr     : (H, W, 3) uint8 BGR image
    owned_entries : owned-colour entries — NO background (B0) entry
    thresholds    : {label: max_rgb_distance}.  Default 80 if not specified.
                    Range 0-441 (sqrt(3)*255 is the theoretical max).

    Returns
    -------
    PaletteMap  assignment_map: 0..N-1 = palette index, -1 = unassigned
    """
    owned_entries = list(owned_entries)
    thresholds    = thresholds or {}

    if not owned_entries:
        h, w = image_bgr.shape[:2]
        return PaletteMap(
            assignment_map=np.full((h, w), -1, dtype=np.int16),
            palette=[],
        )

    h, w = image_bgr.shape[:2]

    # (P, 3) float32 RGB pixels
    rgb_pixels = image_bgr[:, :, ::-1].reshape(-1, 3).astype(np.float32)

    # (N, 3) palette RGB
    palette_rgb = np.array([list(e.rgb) for e in owned_entries], dtype=np.float32)

    # (P, N) Euclidean RGB distances
    diff = rgb_pixels[:, np.newaxis, :] - palette_rgb[np.newaxis, :, :]
    dist = np.sqrt((diff ** 2).sum(axis=2))

    # (N,) threshold vector
    thresh_vec = np.array(
        [float(thresholds.get(e.label, DEFAULT_THRESHOLD)) for e in owned_entries],
        dtype=np.float32,
    )

    # (P, N) bool — True where this colour is a candidate for this pixel
    in_range = dist <= thresh_vec[np.newaxis, :]   # (P, N)

    # For pixels with multiple candidates, the highest-threshold colour wins.
    # We achieve this by scoring each candidate as its threshold value, then
    # taking argmax over candidates.  Non-candidates get score -inf.
    scores = np.where(in_range, thresh_vec[np.newaxis, :], -np.inf)  # (P, N)

    best_idx = scores.argmax(axis=1).astype(np.int16)   # (P,)

    # Pixels where no candidate existed → unassigned
    no_candidate = ~in_range.any(axis=1)                # (P,)
    best_idx[no_candidate] = -1

    return PaletteMap(
        assignment_map=best_idx.reshape(h, w),
        palette=owned_entries,
    )
