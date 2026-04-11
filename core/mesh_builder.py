"""
core/mesh_builder.py
Converts a mm-space Shapely polygon into a watertight Trimesh solid,
then engraves a plate-ID string onto the frame surface.

Engraving uses a custom 5×7 bitmap font defined in config.py — no font
files required, works offline, always renders identically.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.validation import make_valid
from shapely import affinity
import trimesh
import trimesh.creation
import trimesh.repair
import trimesh.boolean

from config import (
    EDGE_RIM_EXTRA_MM,
    EDGE_RIM_INSET_MM,
    ENGRAVE_DEPTH_MM,
    ENGRAVE_CHAR_WIDTH_MM,
    ENGRAVE_CHAR_HEIGHT_MM,
    ENGRAVE_CHAR_SPACING_MM,
    ENGRAVE_MARGIN_MM,
    ENGRAVE_STROKE_WIDTH_MM,
    BITMAP_FONT,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

# Minimum polygon area (mm²) worth extruding — filters degenerate slivers
_MIN_AREA_MM2 = 0.05   # lowered from 0.3 to allow small engraving strokes
# Simplification tolerance (mm) applied before earcut triangulation
_SIMPLIFY_TOL = 0.04


def _extrude(polygon: Polygon | MultiPolygon, height: float) -> trimesh.Trimesh | None:
    """
    Robustly extrude a Shapely polygon to a Trimesh solid.

    Handles MultiPolygons by extruding each part separately and concatenating.
    Applies buffer(0) + simplify() before extrusion to clean topology and
    reduce vertex count for earcut triangulation (which struggles with
    high-vertex-count circles from pixel-traced contours).
    Runs normal/winding repair and hole-filling on every produced mesh.
    """
    if polygon is None or polygon.is_empty or height <= 0:
        return None

    polygon = make_valid(polygon).buffer(0)
    if polygon.is_empty:
        return None

    def _extrude_one(poly: Polygon) -> trimesh.Trimesh | None:
        if poly.area < _MIN_AREA_MM2:
            return None
        # Simplify to reduce earcut vertex count while preserving topology
        poly = poly.simplify(_SIMPLIFY_TOL, preserve_topology=True)
        poly = make_valid(poly).buffer(0)
        if poly.is_empty:
            return None
        try:
            m = trimesh.creation.extrude_polygon(poly, height=height)
            if len(m.faces) < 4:
                return None
            trimesh.repair.fix_normals(m)
            trimesh.repair.fix_winding(m)
            if not m.is_watertight:
                trimesh.repair.fill_holes(m)
            return m
        except Exception as exc:
            print(f"    [mesh] extrude_polygon failed: {exc}")
            return None

    if isinstance(polygon, MultiPolygon):
        parts = [_extrude_one(g) for g in polygon.geoms if not g.is_empty]
        parts = [p for p in parts if p is not None]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        result = trimesh.util.concatenate(parts)
        trimesh.repair.fix_normals(result)
        if not result.is_watertight:
            trimesh.repair.fill_holes(result)
        return result

    return _extrude_one(polygon)


def _combine(*meshes: trimesh.Trimesh | None) -> trimesh.Trimesh | None:
    """Concatenate non-None meshes into one."""
    valid = [m for m in meshes if m is not None]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    return trimesh.util.concatenate(valid)


# ── Engraving ─────────────────────────────────────────────────────────────────

def _char_strokes(char: str) -> list[Polygon]:
    """
    Convert a single character to a list of Shapely rectangles
    using the 5×7 bitmap font, positioned at the origin (bottom-left).

    The character cell occupies:
        x: 0 .. ENGRAVE_CHAR_WIDTH_MM
        y: 0 .. ENGRAVE_CHAR_HEIGHT_MM
    """
    grid = BITMAP_FONT.get(char.upper(), BITMAP_FONT.get(" "))
    if grid is None:
        return []

    rows = len(grid)      # 7
    cols = len(grid[0])   # 5
    cell_w = ENGRAVE_CHAR_WIDTH_MM  / cols
    cell_h = ENGRAVE_CHAR_HEIGHT_MM / rows
    sw = ENGRAVE_STROKE_WIDTH_MM

    rects: list[Polygon] = []
    for r, row in enumerate(grid):
        # Bitmap rows: row 0 = top, so invert y
        y_top    = ENGRAVE_CHAR_HEIGHT_MM - r       * cell_h
        y_bottom = ENGRAVE_CHAR_HEIGHT_MM - (r + 1) * cell_h
        for c, ink in enumerate(row):
            if not ink:
                continue
            x_left  = c       * cell_w
            x_right = (c + 1) * cell_w
            rects.append(box(x_left, y_bottom, x_right, y_top))

    return rects


def _text_cutout_mesh(
    plate_id: str,
    tile_w_mm: float,
    z_top: float,
    depth: float = ENGRAVE_DEPTH_MM,
) -> trimesh.Trimesh | None:
    """
    Build a single mesh that is the union of all character cutouts for
    *plate_id*, positioned along the bottom edge of the tile frame.

    The text starts at (ENGRAVE_MARGIN_MM, ENGRAVE_MARGIN_MM) in XY
    and is cut downward from *z_top* by *depth*.
    """
    cw = ENGRAVE_CHAR_WIDTH_MM
    cs = ENGRAVE_CHAR_SPACING_MM
    margin = ENGRAVE_MARGIN_MM

    char_meshes: list[trimesh.Trimesh] = []
    x_cursor = margin

    for char in plate_id:
        if x_cursor + cw > tile_w_mm - margin:
            break  # ran out of frame space

        strokes = _char_strokes(char)
        for rect in strokes:
            # Translate rect to current cursor position
            translated = affinity.translate(rect, xoff=x_cursor, yoff=margin)
            m = _extrude(translated, depth + 0.01)  # tiny over-cut to avoid z-fighting
            if m is not None:
                m.apply_translation([0, 0, z_top - depth])
                char_meshes.append(m)

        x_cursor += cw + cs

    if not char_meshes:
        return None

    return _combine(*char_meshes)


# ── Main public function ───────────────────────────────────────────────────────

def build_mesh(
    plate_polygon_mm: Polygon | MultiPolygon,
    tile_w_mm: float,
    tile_h_mm: float,
    plate_id: str,
    thickness_mm: float,
    thicken_edges: bool,
) -> trimesh.Trimesh | None:
    """
    Convert *plate_polygon_mm* (Shapely, mm coords) into a watertight
    Trimesh STL-ready solid, with optional edge rim and ID engraving.

    Parameters
    ----------
    plate_polygon_mm : Shapely Polygon or MultiPolygon in mm coordinates
    tile_w_mm        : tile width in mm (for rim and text positioning)
    tile_h_mm        : tile height in mm
    plate_id         : string engraved onto the frame, e.g. "C1_Tile_A1"
    thickness_mm     : base extrusion height
    thicken_edges    : whether to add a raised perimeter rim

    Returns
    -------
    trimesh.Trimesh or None if geometry is degenerate
    """
    if plate_polygon_mm is None or plate_polygon_mm.is_empty:
        return None

    plate_polygon_mm = make_valid(plate_polygon_mm)

    # ── 1. Base plate extrusion ───────────────────────────────────────────────
    base_mesh = _extrude(plate_polygon_mm, thickness_mm)
    if base_mesh is None:
        return None

    parts: list[trimesh.Trimesh] = [base_mesh]

    # ── 2. Optional perimeter rim ─────────────────────────────────────────────
    if thicken_edges:
        try:
            full_rect = box(0, 0, tile_w_mm, tile_h_mm)
            inner_rect = box(
                EDGE_RIM_INSET_MM,
                EDGE_RIM_INSET_MM,
                tile_w_mm - EDGE_RIM_INSET_MM,
                tile_h_mm - EDGE_RIM_INSET_MM,
            )
            rim_ring = make_valid(full_rect.difference(inner_rect))
            if not rim_ring.is_empty:
                rim_mesh = _extrude(rim_ring, EDGE_RIM_EXTRA_MM)
                if rim_mesh is not None:
                    rim_mesh.apply_translation([0, 0, thickness_mm])
                    parts.append(rim_mesh)
        except Exception as e:
            print(f"    [mesh] Rim generation failed: {e}")

    # ── 3. Combine base + rim ─────────────────────────────────────────────────
    if len(parts) > 1:
        # Prefer boolean union (produces watertight manifold);
        # fall back to concatenate if any part is not a volume
        try:
            if all(m.is_watertight for m in parts):
                combined = trimesh.boolean.union(parts)
            else:
                combined = trimesh.util.concatenate(parts)
                trimesh.repair.fix_normals(combined)
                if not combined.is_watertight:
                    trimesh.repair.fill_holes(combined)
        except Exception:
            combined = trimesh.util.concatenate(parts)
    else:
        combined = parts[0]

    if combined is None:
        return None

    # ── 4. Engraving — boolean difference ────────────────────────────────────
    z_top = thickness_mm + (EDGE_RIM_EXTRA_MM if thicken_edges else 0.0)
    text_mesh = _text_cutout_mesh(plate_id, tile_w_mm, z_top)

    if text_mesh is not None:
        # Ensure both meshes are volumes before boolean op
        trimesh.repair.fix_normals(combined)
        trimesh.repair.fix_winding(combined)
        if not combined.is_watertight:
            trimesh.repair.fill_holes(combined)

        if combined.is_watertight:
            try:
                result = trimesh.boolean.difference([combined, text_mesh])
                if result is not None and not result.is_empty and len(result.faces) > 0:
                    combined = result
            except Exception as e:
                print(f"    [engrave] Boolean difference failed: {e}")

    # ── 5. Mesh repair ────────────────────────────────────────────────────────
    try:
        trimesh.repair.fix_normals(combined)
        trimesh.repair.fix_winding(combined)
    except Exception:
        pass

    return combined
