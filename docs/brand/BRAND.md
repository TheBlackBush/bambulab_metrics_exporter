# bambulab_metrics_exporter: brand kit

How to apply this branding in the repo and elsewhere.
The SVG files in `svg/` are the source of truth. Do not redraw, recolor or re-space the mark.

## The mark

Two green slabs split by a black strip, crossed by a black metrics line: a ramp on the left
slab, then a flat run that crosses the strip and spikes once in the middle of the right slab.
The line is clipped to the slabs, so it ends flush with their outer edges.

Exact geometry (viewBox `0 0 400 400`, mark bounds `x 90–310`, `y 60–340`):

```svg
<clipPath id="bme-wave"><rect x="90" y="60" width="220" height="280"/></clipPath>
<rect x="90"  y="60" width="100" height="280" fill="#00AE42"/>  <!-- left slab -->
<rect x="210" y="60" width="100" height="280" fill="#00AE42"/>  <!-- right slab -->
<rect x="190" y="60" width="20"  height="280" fill="#000000"/>  <!-- middle strip -->
<path clip-path="url(#bme-wave)" d="M70 246.57 L174 202 L229 202 L260 148 L291 202 L330 202"
      fill="none" stroke="#000000" stroke-width="16" stroke-linejoin="round"/>
```

If you inline the SVG more than once on a page, give each `clipPath` a unique id.

## Colors

| Token        | Hex       | Use                                              |
|--------------|-----------|--------------------------------------------------|
| `green`      | `#00AE42` | Slabs; primary accent (buttons, links, chart line) |
| `black`      | `#000000` | Strip, metrics line, wordmark                    |
| `tile`       | `#141A17` | App-icon background; dark surfaces               |
| `muted`      | `#4A524E` | Underscores in the wordmark, taglines, secondary text |
| `white`      | `#FFFFFF` | Light backgrounds                                |

CSS variables, if the project has a web UI or docs site:

```css
:root {
  --bme-green: #00AE42;
  --bme-black: #000000;
  --bme-tile:  #141A17;
  --bme-muted: #4A524E;
  --bme-white: #FFFFFF;
}
```

Contrast: black on green ≈ 7.1:1 (passes). White on green ≈ 2.9:1, so use it only for
text 24 px and up, never for body text.

## Typography

- Wordmark and headings: **JetBrains Mono** 700 (Google Fonts, OFL). Fallback: `ui-monospace, Menlo, Consolas, monospace`.
- Body/secondary: JetBrains Mono 500, or the platform's default sans.
- The name is always written lowercase with underscores: `bambulab_metrics_exporter`.
  In the wordmark the underscores are `muted` (#4A524E), the words are black.

## Files

| File                     | Use |
|--------------------------|-----|
| `svg/logo.svg`           | Mark, cropped tight (220×280). README header, docs. |
| `svg/logo-square.svg`    | Mark with padding (400×400). Avatars, social cards. |
| `svg/icon.svg`           | Mark on a dark rounded tile. App/repo icon, Grafana dashboard icon. |
| `svg/favicon.svg`        | Same tile with a thicker line, for 32 px and below. |
| `svg/lockup.svg`         | Mark + wordmark + tagline (1200×320). Uses JetBrains Mono, which must be installed or loaded; prefer the PNG where fonts can't load (e.g. GitHub README). |
| `png/logo-512.png`, `png/logo-1024.png` | Transparent square mark. |
| `png/logo-440x560.png`   | Transparent tight mark at 2×. |
| `png/icon-48/180/192/512.png` | Icon tile (180 = apple-touch-icon, 192/512 = web manifest). |
| `png/favicon-16.png`, `png/favicon-32.png` | Favicons. |
| `png/lockup-2400x640.png`| Lockup at 2×, transparent background. |

## Usage rules

- **Light backgrounds only** for `logo*` and `lockup*`: the black strip and line vanish on dark
  backgrounds. On dark backgrounds (dark-mode README, Grafana dark theme) use `icon.svg`.
- Clear space around the mark: at least the width of the middle strip × 2 (40 units at the 400 scale).
- Minimum size: mark 24 px tall; below 32 px use `favicon.svg` / `favicon-*.png`.
- Don't: recolor the slabs, put the line in green or white, add gradients/shadows/outlines,
  rotate, stretch, or move the spike.
- This is an unofficial community project. State "Not affiliated with Bambu Lab" in the README,
  and don't present the mark as Bambu Lab's own logo.

## Placement in the repo

1. Copy this folder to `docs/brand/` (or `assets/brand/`).
2. README header (renders on GitHub light and dark themes):

   ```html
   <p align="center">
     <picture>
       <source media="(prefers-color-scheme: dark)" srcset="docs/brand/svg/icon.svg">
       <img src="docs/brand/png/lockup-2400x640.png" alt="bambulab_metrics_exporter" width="600">
     </picture>
   </p>
   ```

   Add a line under it: `Not affiliated with Bambu Lab.`
3. If there's a web UI / docs site: `favicon.svg` as `<link rel="icon" type="image/svg+xml">`,
   `favicon-32.png` as the PNG fallback, `icon-180.png` as `apple-touch-icon`,
   `icon-192.png` / `icon-512.png` in the web manifest, and `--bme-*` variables for colors.
4. Grafana dashboards shipped with the exporter: use `#00AE42` as the primary series color.
5. GitHub social preview (Settings → Social preview, 1280×640): place `lockup-2400x640.png`
   centered on white.
