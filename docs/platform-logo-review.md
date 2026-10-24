# Platform logo review

The eight reviewed frames use existing SVG files from the [asset manifest](../assets/logos/MANIFEST.json). No logo drawing or trademark artwork was altered. The current frame geometry, 600 × 900 size, transparent art window and Steam reference size are preserved.

| Platform | Default SVG | Frame color | Header adjustment |
| --- | --- | --- | --- |
| Wii | White | `#328fa6` | None |
| PlayStation 5 | White | `#397cbe` | None |
| Game Boy | White | `#869572` | None |
| Game Boy Color | Multicolored COLOR wordmark | `#7654a3` | Deeper violet case and lavender header for the dark blue letters |
| Nintendo 64 | Four-color N emblem | `#2388a3` | Deeper teal case and muted teal header for the dark blue wordmark |
| GameCube | White | `#6743a2` | None; its purple emblem was less distinct against the purple header |
| Dreamcast | Orange spiral | `#cb5b28` | Darker burnt-orange header for the spiral |
| PlayStation | Multicolored PS emblem | `#606575` | None |

[Compare all eight frames with dark and light sample artwork](platform-logo-comparison.png). The preview is built through the same `cover_workflow.export_one` PNG compositor used by the application. Run `python tools/build_platform_logo_comparison.py` to regenerate it.

The later five-platform refinement replaced the PS2, PS3 and PSP combined marks with standalone wordmarks from the same pinned source collection. Their frame colors remain `#273e9e`, `#3c414d` and `#30374c`. The Nintendo 64 and Game Boy Color colored SVGs were kept byte-for-byte; only their palettes changed. [Compare the five headers before and after](playstation-nintendo-header-review.png) and [compare complete covers with identical dark and light sample artwork](playstation-nintendo-frame-review.png).
