# Product Motion Studio

**One-click product animation studio for Blender** — camera, motion, lights, backdrop, floor, look and render settings built around your model in seconds.

![Blender](https://img.shields.io/badge/Blender-5.0%2B-orange.svg)
![License](https://img.shields.io/badge/License-GPL--3.0-blue.svg)
![Version](https://img.shields.io/badge/Version-0.3.0-green.svg)

![Product Motion Studio demo](docs/media/demo.gif)

## Why

Setting up a product shot in Blender — camera framing, motion curves, lighting rigs, backdrop gradients, floor materials, color grading, render settings — takes hours of manual work. Product Motion Studio builds the entire studio around your selected object with one click, then lets you tweak every parameter live without rebuilding.

## Features

| Area | What you get |
|------|--------------|
| 🎬 **One-click recipes** | 16 complete styles (luxury perfume, tech launch, sneaker drop, turntable catalogue…) that set all 9 sections + duration |
| 🔄 **Product motion** | 54 presets: spins, drifts, reveals, impacts, flips, fly-bys, loops — all with measured peak speed, acceleration and floor-clearance |
| 🎥 **Camera** | 12 shot types × 25 motion presets (orbit, dolly, crane, whip, rack focus, handheld…) with C²-continuous curves |
| 💡 **Lighting & backdrop** | 64 lighting rigs (beauty, rim, glass, metal, jewellery, tech, food, automotive, high-key, low-key…) + 25 backdrops (cycloramas, gradients, 360° studios, your own image) + 6 background lights + 8 floors |
| 🎨 **Look & render** | 36 color/film looks + 7 formats (16:9, 9:16, 1:1, 4:5, 21:9, 4:3, 2.39:1) — Draft/Preview/Final/Custom quality, MP4 or PNG sequences |
| ⚡ **Live controls** | Lens, padding, DoF, f-stop, light power/tint/rotation, backdrop gradient colors/type/rotation, floor color/roughness, look intensity/exposure — all update instantly |
| 💾 **Your presets & scenes** | Save any section or the whole studio (with hand edits) as personal presets with thumbnails; export/import JSON bundles to share |
| 🛡 **Coverage check** | Warns when the camera sees past the backdrop ("void"), listing the frames and a fix tip per backdrop type |
| 🐍 **Python API** | `build`, `apply_recipe`, `set_live`, `set_render`, `save_preset`, `save_scene`, `export_user`, `import_user`, `state`… — designed for scripts and AI agents (Claude + Blender MCP) |

## Recipes

![Recipes grid](docs/media/recipes_grid.png)

The 16 built-in recipes: **luxury perfume**, **skincare pastel**, **tech launch dark**, **smartphone hero**, **sneaker drop**, **watch & jewellery sparkle**, **beverage can cool**, **food warm**, **packaging e-commerce white**, **automotive part metal**, **headphones studio**, **cosmetics pop color**, **minimal scandinavian**, **editorial noir**, **social 9:16 punchy**, **turntable catalogue**.

![Rendered stills](docs/media/stills_grid.jpg)

Frames from the demo above, rendered in Cycles with six of the recipes on simple test objects (glass bottle, metal can, plastic cube).

## Preset library

| Section | Count | Examples |
|---------|-------|----------|
| Product Motion | 54 | `spin_360_loop`, `pop_in_reveal`, `luxury_drift` |
| Camera Shot | 12 | `hero_34`, `macro`, `low_angle` |
| Camera Motion | 25 | `orbit_360_loop`, `push_in`, `whip_orbit_finale` |
| Lighting | 64 | `beauty_soft`, `dark_luxury_contour`, `glass_edges` |
| Background | 25 | `cyclorama_studio_grey`, `cyclorama_radial_spotlight`, `image` |
| Background Light | 6 | `soft_wash`, `spot_pool`, `rim_glow` |
| Floor | 8 | `matte`, `glossy`, `mirror`, `shadow_catcher` |
| Format | 7 | `16:9`, `9:16`, `1:1`, `21:9` |
| Look | 36 | `clean_commercial`, `dark_editorial`, `film_warm` |
| Recipe | 16 | `luxury_perfume`, `tech_launch_dark`, `turntable_catalogue` |

**Total: 253 built-in presets**, browsable as thumbnails in the panel, plus your own presets and scenes.

## Installation

**User**
1. Download `product_motion_studio-0.3.0.zip` from the [Releases](https://github.com/eliaaventuri/product-motion-studio/releases) page — **do not unzip it**
2. Blender → Edit → Preferences → Get Extensions → top-right menu → Install from Disk → select the zip
3. Enable "Product Motion Studio"

**For developers**
```bash
./tools/install_dev.sh
```
Creates a symlink into your Blender extensions folder and enables the add-on.

**Run tests**
```bash
blender -b --factory-startup --python tests/test_addon.py
```
91 headless tests across 8 test files (motion quality, camera quality, framing, live controls, user presets, state, prepare, addon).

## Quick start

1. Select your product object(s) in the 3D Viewport
2. Press **N** and open the **PMS** tab
3. Pick a **Recipe** from the thumbnails (e.g. *luxury perfume*) and click **Apply Recipe**, or choose a preset per section and click **Build All**
4. Fine-tune with the **Live controls** in any section (lens, light power, backdrop colours, look intensity…): changes apply instantly
5. In **10. Render**, choose **Final** and click **Render Animation**

## Scripting & AI agents

```python
# installed as an extension:
import bl_ext.user_default.product_motion_studio.api as api

# Apply a complete recipe
api.apply_recipe("luxury_perfume")

# Or build step by step
api.build(
    shot="hero_34",
    product_motion="spin_360_loop",
    camera_motion="orbit_360_loop",
    lighting="beauty_soft",
    background="cyclorama_studio_grey",
    background_light="soft_wash",
    floor="matte",
    format="16:9",
    look="clean_commercial",
    duration=200
)

# Tweak live
api.set_live(cam_lens=85, light_power=1.2, light_tint=(1, .9, .8))

# Render settings
api.set_render('FINAL', motion_blur=True, fmt='MP4', mode='animation')
```

The API is designed for **Claude + Blender MCP** — give the agent a brief and it drives the add-on for you.

## Companion skill for Claude

**Product Animation Director for Blender** (paid, on Agensi) — an art-director skill that produces a brief & shot list, prepares CAD models, assigns materials, designs lighting & camera, animates with overshoot/settle/weight, grades the look, renders, runs measurable checks, and drives PMS through its API across 12 workflows (brief → prepare → materials → lights → camera → animate → preview → check → critique → variants → render → full spot).

👉 **[Get the skill on Agensi](AGENSI_LINK_ANIMAZIONE)** · the add-on itself stays free and open source.

## Measured quality

- **Motion**: 54 product-motion presets rewritten with absolute-time curves — peak-speed, C² continuity, loop-seam C¹ and floor-penetration violations reduced **169 → 0**
- **Camera**: 25 camera-motion presets with C² ramps, peak-speed caps, no abrupt starts/stops — violations **227 → 0** (declared exceptions: `whip_orbit_finale` ~170°/s, `dolly_zoom`/`rack_focus` change lens, `handheld` noise < 0.9° p-p)
- **Framing**: Product fills **~75% of frame height** in 16:9 across the animation (was 30–70%)
- **Recipes**: All 16 verified in Cycles & Eevee — clipping **≤ 0.5%**, Eevee luminance within **±0.06**
- **Test suite**: **91 automated headless tests pass** (8 test files)

## Known limitations

- Mirror floor in Eevee shows a black band (screen-space reflections miss off-screen geometry) — correct in Cycles
- Metals in Eevee require ray-tracing (enabled automatically on build)
- Coverage check detects geometric voids, not whether the backdrop is *lit* in dark areas
- Very short animations (< 30 frames) can exceed `frame_end` on some motions
- Vertical formats keep wide product groups small (width-limited)

## Roadmap

- More recipe styles (jewellery macro, automotive hero, cosmetic splash…)
- Native Blender Extensions platform packaging (one-click install from Blender's Get Extensions)
- Video tutorials for each workflow

## License

GPL-3.0-or-later — free and open source.

## Author

**Elia Venturi** — [github.com/eliaaventuri](https://github.com/eliaaventuri)

---

⭐ If this add-on saves you time, please **star the repo** and open an issue for bugs or feature requests.