"""
core/geometry.py
Converts a binary tile mask into a printable Shapely polygon.

Pipeline
--------
1. find_contours_hierarchical  — OpenCV RETR_TREE contours + hierarchy
2. classify_contours           — bucket by nesting depth
3. build_base_plate            — solid tile rectangle
4. apply_cutouts               — subtract Level-0 (color-region) contours
5. restore_inner_solids        — union back Level-1 (solid-within-hole) contours
6. add_bridges                 — connect floating islands (Level-2+) to the plate
7. finalize_plate              — scale px → mm, validate, return
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from shapely.geometry import Polygon, MultiPolygon, Point, LineString
from shapely.ops import nearest_points, unary_union
from shapely import affinity
from shapely.validation import make_valid

from config import (
    PX_PER_MM,
    BRIDGE_WIDTH_MM,
    MIN_BRIDGE_LENGTH_MM,
    MIN_CONTOUR_AREA_MM2,
    CONTOUR_APPROX_EPSILON,
)


# ── Internal dataclass ────────────────────────────────────────────────────────

@dataclass
class ContourTree:
    outer: list[Polygon] = field(default_factory=list)   # Level 0 — cutouts
    inner: list[Polygon] = field(default_factory=list)   # Level 1 — solid-in-hole
    islands: list[Polygon] = field(default_factory=list) # Level 2+ — floating


# ── Step 1 — Contour detection ────────────────────────────────────────────────

def find_contours_hierarchical(
    mask: np.ndarray,
) -> tuple[tuple, np.ndarray | None]:
    """
    Run cv2.findContours with RETR_TREE to obtain the full nesting hierarchy.

    Returns (contours, hierarchy) exactly as OpenCV does, or ((), None) when
    no contours are found.
    """
    # Light morphological cleanup to reduce noise without altering structure
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    cleaned = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    contours, hierarchy = cv2.findContours(
        cleaned, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    return contours, hierarchy


# ── Step 2 — Contour classification ──────────────────────────────────────────

def _contour_to_polygon(cnt: np.ndarray, epsilon: float) -> Polygon | None:
    """
    Simplify an OpenCV contour and convert it to a Shapely Polygon.
    Returns None if the result is degenerate.
    """
    approx = cv2.approxPolyDP(cnt, epsilon, closed=True)
    pts = approx[:, 0, :].tolist()
    if len(pts) < 3:
        return None
    try:
        poly = Polygon(pts)
        poly = make_valid(poly)
        if poly.is_empty or not isinstance(poly, (Polygon, MultiPolygon)):
            return None
        # Unwrap MultiPolygon to its largest member
        if isinstance(poly, MultiPolygon):
            poly = max(poly.geoms, key=lambda p: p.area)
        return poly
    except Exception:
        return None


def classify_contours(
    contours: tuple,
    hierarchy: np.ndarray,
    min_area_px: float,
) -> ContourTree:
    """
    Walk the RETR_TREE hierarchy and bucket each contour by nesting depth.

    OpenCV hierarchy per contour: [next, prev, first_child, parent]
      depth 0  → no parent  → outer boundary of a color region  (cutout)
      depth 1  → parent is depth-0 → solid island inside a hole  (keep solid)
      depth 2+ → floating island that needs a bridge
    """
    tree = ContourTree()
    if hierarchy is None:
        return tree

    hier = hierarchy[0]  # shape (N, 4)

    def depth_of(idx: int) -> int:
        d = 0
        parent = hier[idx][3]
        while parent >= 0:
            d += 1
            parent = hier[parent][3]
        return d

    for i, cnt in enumerate(contours):
        area_px = cv2.contourArea(cnt)
        if area_px < min_area_px:
            continue

        poly = _contour_to_polygon(cnt, CONTOUR_APPROX_EPSILON)
        if poly is None:
            continue

        d = depth_of(i)
        if d == 0:
            tree.outer.append(poly)
        elif d == 1:
            tree.inner.append(poly)
        else:
            tree.islands.append(poly)

    return tree


# ── Steps 3–5 — Base plate + cutouts + inner solids ──────────────────────────

def build_base_plate(tile_w_px: int, tile_h_px: int) -> Polygon:
    """Solid rectangle covering the entire tile in pixel coordinates."""
    return Polygon([
        (0,          0),
        (tile_w_px,  0),
        (tile_w_px,  tile_h_px),
        (0,          tile_h_px),
    ])


def apply_cutouts(plate: Polygon, outer_contours: list[Polygon]) -> Polygon:
    """
    Subtract each color-region contour from the plate.
    These become the holes through which paint passes.
    """
    for cutout in outer_contours:
        try:
            plate = plate.difference(cutout)
            plate = make_valid(plate)
        except Exception:
            pass
    return plate


def restore_inner_solids(plate: Polygon, inner_contours: list[Polygon]) -> Polygon:
    """
    Union inner-solid contours (Level 1) back into the plate.
    These are material that sits inside a cutout — they must stay solid
    but become floating islands until bridges are added.
    """
    for solid in inner_contours:
        try:
            plate = plate.union(solid)
            plate = make_valid(plate)
        except Exception:
            pass
    return plate


# ── Step 6 — Bridge algorithm ─────────────────────────────────────────────────

def _build_bridge_rect(p1: Point, p2: Point, width_mm: float, px_per_mm: float) -> Polygon:
    """
    Build a rectangle of *width_mm* connecting points p1 and p2 (in pixel space).

    Geometry
    --------
    Given two endpoints, compute:
      • direction vector along the bridge axis (unit)
      • perpendicular vector (unit) for the width
      • four corners = p1 ± perp*(width/2), p2 ± perp*(width/2)
    """
    half_w = (width_mm * px_per_mm) / 2.0

    dx = p2.x - p1.x
    dy = p2.y - p1.y
    length = math.hypot(dx, dy)

    if length < 1e-9:
        # Points are coincident — return a tiny square
        return Point(p1.x, p1.y).buffer(half_w, cap_style=3)

    # Unit perpendicular
    px = -dy / length
    py =  dx / length

    corners = [
        (p1.x + px * half_w,  p1.y + py * half_w),
        (p1.x - px * half_w,  p1.y - py * half_w),
        (p2.x - px * half_w,  p2.y - py * half_w),
        (p2.x + px * half_w,  p2.y + py * half_w),
    ]
    return Polygon(corners)


def add_bridges(
    plate: Polygon,
    floating_islands: list[Polygon],
    bridge_width_mm: float = BRIDGE_WIDTH_MM,
    min_bridge_length_mm: float = MIN_BRIDGE_LENGTH_MM,
) -> tuple[Polygon, int]:
    """
    Iteratively connect every floating island to the growing solid mass
    using the shortest-path bridge algorithm.

    Algorithm
    ---------
    1. Start with `connected` = the plate (which may already have interior gaps).
    2. Each iteration: find the unconnected island closest to `connected`.
    3. Use shapely.ops.nearest_points() to get the exact closest point pair.
    4. If the gap is larger than min_bridge_length_mm, insert a bridge rectangle.
    5. Union island + bridge into `connected`.  Repeat until all islands connected.

    This iterative approach handles dependency chains where island B is closer
    to island A than to the frame — A must be connected first.

    Returns
    -------
    (final_polygon, n_bridges_added)
    """
    if not floating_islands:
        return plate, 0

    connected = make_valid(plate)
    unconnected = [make_valid(isl) for isl in floating_islands]
    n_bridges = 0
    min_gap_px = min_bridge_length_mm * PX_PER_MM

    max_iterations = len(floating_islands) * 3  # safety guard
    iterations = 0

    while unconnected and iterations < max_iterations:
        iterations += 1

        # Find the island with the smallest gap to the current connected mass
        best_idx = -1
        best_dist = float("inf")
        best_p_on_connected = None
        best_p_on_island = None

        for idx, island in enumerate(unconnected):
            try:
                dist = connected.distance(island)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx
                    pt_c, pt_i = nearest_points(connected, island)
                    best_p_on_connected = pt_c
                    best_p_on_island = pt_i
            except Exception:
                continue

        if best_idx < 0:
            break  # no valid island found

        island = unconnected.pop(best_idx)

        if best_dist > min_gap_px:
            # Insert a bridge rectangle between the two nearest points
            bridge = _build_bridge_rect(
                best_p_on_connected,
                best_p_on_island,
                bridge_width_mm,
                PX_PER_MM,
            )
            n_bridges += 1
            try:
                connected = connected.union(bridge)
                connected = make_valid(connected)
            except Exception:
                pass

        # Always absorb the island into the connected mass
        try:
            connected = connected.union(island)
            connected = make_valid(connected)
        except Exception:
            pass

    return connected, n_bridges


# ── Step 7 — Scale to mm ──────────────────────────────────────────────────────

def finalize_plate(
    polygon: Polygon,
    px_per_mm: float = PX_PER_MM,
) -> Polygon | None:
    """
    Scale the pixel-space polygon to millimetre coordinates.
    Returns None if the result is empty or invalid.
    """
    if polygon is None or polygon.is_empty:
        return None

    scale = 1.0 / px_per_mm
    scaled = affinity.scale(polygon, xfact=scale, yfact=scale, origin=(0, 0))
    scaled = make_valid(scaled)

    if scaled.is_empty:
        return None
    return scaled


# ── Public convenience function ───────────────────────────────────────────────

def mask_to_plate(
    mask: np.ndarray,
    tile_w_mm: float,
    tile_h_mm: float,
) -> tuple[Polygon | None, int]:
    """
    Full pipeline: binary uint8 mask → mm-space Shapely plate polygon.

    Parameters
    ----------
    mask      : np.ndarray  shape (H, W), uint8, values 0 or 255
    tile_w_mm : float  actual tile width in mm  (may differ from bed at edges)
    tile_h_mm : float  actual tile height in mm

    Returns
    -------
    (plate_polygon_mm, n_bridges)
      plate_polygon_mm — printable plate in mm coordinates, or None if empty
      n_bridges        — number of structural bridges inserted
    """
    h_px, w_px = mask.shape
    if h_px == 0 or w_px == 0:
        return None, 0          # zero-dimension tile (canvas edge overshoot)

    min_area_px = MIN_CONTOUR_AREA_MM2 * (PX_PER_MM ** 2)

    contours, hierarchy = find_contours_hierarchical(mask)
    if not contours:
        return None, 0

    tree = classify_contours(contours, hierarchy, min_area_px)

    plate = build_base_plate(w_px, h_px)
    plate = apply_cutouts(plate, tree.outer)

    # Both depth-1 inner solids and deeper islands can be floating after
    # cutouts are applied.  Route all of them through add_bridges so a
    # bridge is inserted only when the gap is real (distance > threshold).
    # Contours that already touch the plate (distance == 0) are absorbed for
    # free with no bridge added.
    all_islands = tree.inner + tree.islands
    plate, n_bridges = add_bridges(plate, all_islands)

    plate_mm = finalize_plate(plate)
    return plate_mm, n_bridges
