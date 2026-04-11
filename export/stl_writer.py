"""
export/stl_writer.py
Handles STL file naming, directory creation, and export.
"""

from __future__ import annotations

import os
from pathlib import Path

import trimesh


def plate_filename(plate_id: str) -> str:
    """Return the STL filename for a given plate ID."""
    return f"{plate_id}.stl"


def export_stl(
    mesh: trimesh.Trimesh,
    plate_id: str,
    output_dir: str | Path,
) -> Path:
    """
    Export *mesh* as a binary STL file.

    Parameters
    ----------
    mesh       : watertight Trimesh solid
    plate_id   : used for the filename, e.g. "C1_Tile_A1"
    output_dir : directory to write into (created if missing)

    Returns
    -------
    Path to the written file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    path = output_dir / plate_filename(plate_id)
    mesh.export(str(path), file_type="stl")
    return path
