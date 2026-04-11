# 3D Stencil Generator

Convert any image into 3D-printable spray-paint stencil plates.

## Requirements

- Python 3.11+
- A display server (X11 or Wayland) for the GUI

## Quick start (CachyOS / Arch Linux)

```bash
chmod +x run.sh && ./run.sh
```

`run.sh` now does a single editable install (`pip install -e .`) into `.venv` and launches the app.

## Manual install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
stencil-generator
```

## Project structure

```text
.
├── core/      # quantization, tiling, geometry, mesh building
├── ui/        # main window + widgets/dialogs
├── workers/   # background generation thread
├── export/    # STL and HTML guide output
├── config.py  # global constants/tuning
├── main.py    # desktop entry point
└── run.sh     # one-command setup/launch
```

## Run tests

```bash
pip install -e "[dev]"
pytest
```

## Usage

1. **Upload Image** — any PNG, JPG, BMP, TIFF or WebP
2. **Set dimensions** — canvas size (your full artwork) and printer bed size
3. **Set colours** — N controls how many colours K-means extracts
4. **Colour Ownership** — uncheck colours you don't own; they are skipped
5. **Preview** — see the quantised palette and tile-grid overlay before generating
6. **Generate** — produces one STL per colour per tile
7. **Export** — choose STL only or STL + HTML step guide

## Output files

| File | Description |
|---|---|
| `C1_Tile_A1.stl` | Stencil plate for colour 1, tile column A row 1 |
| `C2_Tile_B3.stl` | Stencil plate for colour 2, tile column B row 3 |
| `step_guide.html` | Colour reference, tile map, and layer-by-layer guide |

## Print settings

- **Material**: PETG or ABS (solvent-resistant)
- **Infill**: 100%
- **Layer height**: 0.2 mm
- **Default plate thickness**: 1.2 mm (adjustable in UI)
