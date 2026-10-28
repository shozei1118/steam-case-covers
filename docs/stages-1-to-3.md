# Case Covers: stages 1–3

## Existing project audit

- `gui.py` is a Tkinter front end. It delegates Steam detection, cover creation, application and restore to `steamcase.py`; its existing layout and controls are untouched in these stages.
- `steamcase.py` is also the CLI. It reads Steam library/account data, downloads Steam artwork, composites `assets/frame.png`, creates backups before installing custom art, and restores backups. Its frame path, 600 × 900 canvas and `(14, 96, 586, 872)` art window remain unchanged. Reset also recognizes covers generated with the previous badged Steam frame through exact hashes of its header and lower lip; the old image is retained only as a test fixture.
- `tools/build_frame.py` generates the Steam frame SVG and `assets/frame.png`. That PNG remains the runtime source for Steam, and the platform exporter copies the current generated PNG byte for byte into `assets/frames/steam.png`. The current Steam frame deliberately omits the former Windows/Linux header badges while retaining the original centered Steam artwork and the other design elements.
- Runtime dependencies remain Python and Pillow. The new frame builder uses `resvg_py` and Pillow at build time only; all generated PNGs are committed and can be inspected without Steam or the GUI. Windows build machines can install the pinned build dependencies from `requirements-build.txt`.

## Platform data and export

`platforms/catalog.json` defines 29 IDs across PlayStation, Xbox, Nintendo, Sega and Steam, with twelve-color palettes, a frame template, local SVG paths and review notes. Windows PC, Linux, DOS, Game Gear and all five Atari entries have been removed with their frame and logo assets. `platform_catalog.py` loads the catalog without GUI or Steam imports. Exact SVG origins, hashes and license notes are in `assets/logos/MANIFEST.json`.

Generate all default frames and the visual index:

```powershell
python -m pip install -r requirements-build.txt
python tools/build_frame.py
python tools/build_platform_frames.py --all
python tools/build_logo_preview.py
python tools/build_standalone_preview.py
```

For a single PNG, run `python tools/build_platform_frames.py --platform ps4 --variant colored --output ps4.png`. A Genesis regional banner is available with `--platform mega_drive --region genesis`. The exporter preserves the original frame geometry, gradient and gloss structure while changing all twelve palette colors, including the lower lip. It renders each SVG logo at its original aspect ratio in the center of the full header. Transparent SVG margins are cropped first. The combined visible bounds of the original Steam icon and wordmark are measured at build time (currently 204 × 42 pixels) and cap every other logo. A platform may set `template.logo_scale` to a number in `(0, 1]` for a smaller local adjustment. Every default output is a 600 × 900 transparent PNG under `assets/frames/`; `assets/frames/steam.png` is byte-identical to the current `assets/frame.png`.

Open `logo-preview.html` locally to review each platform's frame, logo choices, selected variant, frame color and outstanding notes. `logo-preview-standalone.html` embeds all 29 frames and 87 SVG logos as data URLs, together with the source manifest and third-party notices, for viewing without the project folder. The Steam runtime, GUI, online artwork sources and manual export flows are outside the scope of these first three stages.
