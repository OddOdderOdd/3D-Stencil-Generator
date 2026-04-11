"""
export/guide_writer.py
Generates a self-contained HTML step guide from the list of generated plates.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class PlateInfo:
    plate_id: str
    color_idx: int          # 1-based
    tile_label: str
    tile_col: int
    tile_row: int
    color_rgb: tuple[int, int, int]   # (R, G, B)
    coverage_pct: float
    n_bridges: int
    stl_path: Path
    thickness_mm: float
    thickened: bool


# ── HTML template pieces ───────────────────────────────────────────────────────

_CSS = """
:root {
  --bg:      #12121f;
  --surface: #1c1c30;
  --card:    #23233a;
  --accent:  #e94560;
  --text:    #e0e0e0;
  --muted:   #888;
  --border:  #2e2e4a;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--text);
  font-family: 'Segoe UI', system-ui, sans-serif;
  padding: 30px 40px; max-width: 1100px; margin: auto;
}
h1 { color: var(--accent); font-size: 2rem; margin-bottom: 4px; }
.subtitle { color: var(--muted); font-size: .9rem; margin-bottom: 30px; }
h2 {
  font-size: 1.1rem; font-weight: 700;
  background: var(--accent); color: #fff;
  display: inline-block; padding: 4px 14px;
  border-radius: 4px; margin-bottom: 14px;
}
h3 { color: #a0c4ff; font-size: 1rem; margin-bottom: 8px; }
section { background: var(--surface); border-radius: 10px;
          padding: 22px; margin-bottom: 24px;
          border-left: 4px solid var(--accent); }

/* Color reference table */
table { width: 100%; border-collapse: collapse; }
th { background: #0f3460; padding: 8px 12px; text-align: left; font-weight: 600; }
td { padding: 7px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: var(--card); }

/* Swatch */
.sw {
  display: inline-block; width: 22px; height: 22px;
  border-radius: 4px; vertical-align: middle;
  border: 1px solid rgba(255,255,255,.2); margin-right: 8px;
}
code {
  background: var(--card); border-radius: 3px;
  padding: 1px 6px; font-size: .85em; color: #a0c4ff;
}

/* Tile grid */
.tile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px; margin-top: 10px;
}
.tile-card {
  background: var(--card); border-radius: 8px; padding: 14px;
}
.tile-card h4 { color: #a0c4ff; font-size: .95rem; margin-bottom: 8px; }
.plate-row { display: flex; align-items: center; gap: 8px;
             font-size: .85rem; margin: 4px 0; }
.bridge-badge {
  background: #5a2020; color: #faa;
  font-size: .7rem; padding: 1px 6px; border-radius: 3px;
}

/* Steps */
.step { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 18px; }
.step-num {
  background: var(--accent); color: #fff; font-weight: bold;
  min-width: 32px; height: 32px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.step-body { line-height: 1.6; }
.step-body strong { font-size: 1rem; }
.step-body small { color: var(--muted); display: block; font-size: .82rem; }

/* Tile map SVG container */
.tilemap-wrap { overflow-x: auto; margin-top: 10px; }

footer { text-align: center; color: var(--muted); font-size: .8rem; margin-top: 40px; }
"""


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = [x / 255 for x in rgb]
    return 0.299 * r + 0.587 * g + 0.114 * b


def _text_color(rgb: tuple[int, int, int]) -> str:
    return "#111" if _luminance(rgb) > 0.5 else "#eee"


def _color_table(plates: list[PlateInfo]) -> str:
    # Group by color_idx
    by_color: dict[int, list[PlateInfo]] = {}
    for p in plates:
        by_color.setdefault(p.color_idx, []).append(p)

    rows = ""
    for cidx in sorted(by_color.keys()):
        plist = by_color[cidx]
        rgb = plist[0].color_rgb
        hx = _hex(rgb)
        tile_labels = ", ".join(p.tile_label for p in plist)
        filenames = ", ".join(os.path.basename(p.stl_path) for p in plist)
        rows += f"""
        <tr>
          <td><span class='sw' style='background:{hx}'></span> Color {cidx}</td>
          <td><code>{hx}</code></td>
          <td>rgb({rgb[0]}, {rgb[1]}, {rgb[2]})</td>
          <td>{tile_labels}</td>
          <td style='font-size:.8em'>{filenames}</td>
        </tr>"""

    return f"""
    <table>
      <thead><tr>
        <th>Color</th><th>Hex</th><th>RGB</th>
        <th>Tiles</th><th>STL Files</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


def _tile_cards(plates: list[PlateInfo]) -> str:
    by_tile: dict[str, list[PlateInfo]] = {}
    for p in plates:
        by_tile.setdefault(p.tile_label, []).append(p)

    cards = ""
    for label in sorted(by_tile.keys()):
        plist = sorted(by_tile[label], key=lambda x: x.color_idx)
        rows_html = ""
        for p in plist:
            hx = _hex(p.color_rgb)
            fname = os.path.basename(p.stl_path)
            bridge_html = (f"<span class='bridge-badge'>{p.n_bridges} bridge(s)</span>"
                           if p.n_bridges > 0 else "")
            rows_html += f"""
            <div class='plate-row'>
              <span class='sw' style='background:{hx}'></span>
              <code>{fname}</code>
              <span style='color:#888;font-size:.8rem'>{p.coverage_pct:.1f}%</span>
              {bridge_html}
            </div>"""
        cards += f"<div class='tile-card'><h4>📐 {label}</h4>{rows_html}</div>"

    return f"<div class='tile-grid'>{cards}</div>"


def _tilemap_svg(plates: list[PlateInfo], n_cols: int, n_rows: int) -> str:
    """Simple SVG grid showing which colours are on which tile."""
    CELL = 60
    PAD  = 30
    total_w = n_cols * CELL + PAD * 2
    total_h = n_rows * CELL + PAD * 2

    # Collect colors per tile
    tile_colors: dict[tuple[int,int], list[tuple[int,int,int]]] = {}
    for p in plates:
        key = (p.tile_col, p.tile_row)
        tile_colors.setdefault(key, []).append(p.color_rgb)

    cells = ""
    for row in range(n_rows):
        for col in range(n_cols):
            x = PAD + col * CELL
            y = PAD + row * CELL
            colors = tile_colors.get((col, row), [])
            n = len(colors)
            if n == 0:
                cells += f"<rect x='{x}' y='{y}' width='{CELL}' height='{CELL}' fill='#2a2a3a' stroke='#3a3a5a'/>"
            else:
                # Split cell into n vertical strips
                strip_w = CELL / n
                for i, rgb in enumerate(colors):
                    hx = _hex(rgb)
                    cells += (f"<rect x='{x + i*strip_w:.1f}' y='{y}' "
                              f"width='{strip_w:.1f}' height='{CELL}' fill='{hx}' stroke='none'/>")
                cells += f"<rect x='{x}' y='{y}' width='{CELL}' height='{CELL}' fill='none' stroke='#555' stroke-width='1'/>"

            # Label
            col_letter = chr(ord("A") + col)
            label = f"{col_letter}{row+1}"
            cells += (f"<text x='{x + CELL/2}' y='{y + CELL - 6}' "
                      f"text-anchor='middle' fill='white' font-size='9' "
                      f"font-family='monospace' opacity='0.9'>{label}</text>")

    return (f"<svg width='{total_w}' height='{total_h}' "
            f"xmlns='http://www.w3.org/2000/svg' style='background:#12121f'>"
            f"{cells}</svg>")


def _printing_steps(plates: list[PlateInfo]) -> str:
    by_color: dict[int, list[PlateInfo]] = {}
    for p in plates:
        by_color.setdefault(p.color_idx, []).append(p)

    steps_html = ""
    for step_num, cidx in enumerate(sorted(by_color.keys()), 1):
        plist = by_color[cidx]
        rgb = plist[0].color_rgb
        hx = _hex(rgb)
        tc = _text_color(rgb)
        tile_names = ", ".join(p.tile_label for p in plist)
        fnames = ", ".join(os.path.basename(p.stl_path) for p in plist)
        bridge_note = (" — some plates contain structural bridges that will appear "
                       "as thin lines in the spray result"
                       if any(p.n_bridges > 0 for p in plist) else "")
        steps_html += f"""
        <div class='step'>
          <div class='step-num'>{step_num}</div>
          <div class='step-body'>
            <strong>
              <span class='sw' style='background:{hx};border-color:{tc}'></span>
              Apply Color {cidx} &nbsp;<code>{hx}</code>
            </strong>
            <small>Tiles: {tile_names}</small>
            <small>Files: {fnames}</small>
            <small style='color:#c88'>{bridge_note}</small>
          </div>
        </div>"""

    return steps_html


# ── Public API ────────────────────────────────────────────────────────────────

def generate_html_guide(
    plates: list[PlateInfo],
    canvas_w_mm: float,
    canvas_h_mm: float,
    bed_w_mm: float,
    bed_h_mm: float,
    n_colors: int,
    n_cols: int,
    n_rows: int,
    output_dir: str | Path,
) -> Path:
    """
    Write step_guide.html to *output_dir* and return its path.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    color_table  = _color_table(plates)
    tile_cards   = _tile_cards(plates)
    tilemap_svg  = _tilemap_svg(plates, n_cols, n_rows)
    print_steps  = _printing_steps(plates)

    total_stls   = len(plates)
    total_bridges = sum(p.n_bridges for p in plates)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stencil Step Guide</title>
<style>{_CSS}</style>
</head>
<body>

<h1>🎨 Spray Paint Stencil Guide</h1>
<p class="subtitle">
  Generated {now} &bull;
  Canvas {canvas_w_mm:.0f}×{canvas_h_mm:.0f} mm &bull;
  Printer bed {bed_w_mm:.0f}×{bed_h_mm:.0f} mm &bull;
  {n_colors} colors &bull;
  {n_cols}×{n_rows} tile grid &bull;
  {total_stls} STL file(s) &bull;
  {total_bridges} bridge(s) inserted
</p>

<section>
  <h2>📊 Color Reference</h2>
  {color_table}
</section>

<section>
  <h2>🗺️ Tile Map</h2>
  <p style="color:var(--muted);font-size:.85rem;margin-bottom:8px">
    Each cell shows the colour strips present on that tile.
    Grey cells = no plates generated (all colours below tolerance).
  </p>
  <div class="tilemap-wrap">{tilemap_svg}</div>
</section>

<section>
  <h2>📐 Tile Breakdown</h2>
  {tile_cards}
</section>

<section>
  <h2>🖨️ Printing &amp; Application Order</h2>
  <p style="color:var(--muted);font-size:.85rem;margin-bottom:14px">
    Print and spray in this sequence. Allow each colour to dry fully before
    positioning the next stencil layer.
  </p>
  {print_steps}
</section>

<section>
  <h2>📋 Tips</h2>
  <ul style="line-height:2;padding-left:20px;color:var(--text)">
    <li>Print at <strong>100% infill</strong> for clean spray edges.</li>
    <li>Recommended materials: <strong>PETG or ABS</strong> (solvent-resistant).</li>
    <li>All tiles share identical outer frame dimensions — align by edge.</li>
    {'<li>Raised lip (thickened edges) aids layer registration.</li>' if any(p.thickened for p in plates) else ''}
    <li>Plates engraved with their ID on the top face — check before spraying.</li>
    <li>Bridges appear as thin raised lines in the final artwork; touch up with
        a fine brush if needed.</li>
  </ul>
</section>

<footer>Generated by 3D Stencil Generator &bull; {now}</footer>
</body>
</html>"""

    path = output_dir / "step_guide.html"
    path.write_text(html, encoding="utf-8")
    return path
