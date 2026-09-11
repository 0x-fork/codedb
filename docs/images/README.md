# README artwork

Created with the built-in imagegen tool. Both PNGs are project assets; the root
README selects them with a `picture` element and `prefers-color-scheme`.

- Light: `codedb-map-light.png`
- Dark: `codedb-map-dark.png`

References: [Codegraff](https://codegraff.com/#codedb),
[Codegraff README](https://github.com/justrach/codegraff), and the product-shell
tokens in zigrepper's `frontend/src/app/globals.css`.

Light palette: rice paper `#f6eedf`, rice `#fffaf0`, ink `#1b1714`, cobalt
`#2654d9`, coral `#d45a43`, gold `#f7a63b`.
Dark palette: charcoal `#100f0d` / `#191714`, rice `#f3ecdf`, blue `#91adff`,
coral `#ef8069`, gold `#ffc16b`. Generated illustrations interpret these colors;
they are not exact flat-color swatches.

## Light generation prompt

```text
Use case: illustration-story
Asset type: wide GitHub README hero illustration for codedb, approximately 3:1 landscape.
Primary request: A playful repository cartographer: a clever workshop rat in a cobalt blue work jacket tracing a route across a sprawling paper map of code modules, connected symbols, and callers, with a coral pencil and tiny golden waypoints. Match the handcrafted editorial woodcut/riso print feeling of Codegraff's workshop rat illustrations.
Scene/backdrop: warm rice paper #f6eedf with subtle print grain. A flat tabletop map becomes a miniature landscape of neatly stacked source-code cards, paths and little architectural file blocks.
Style/medium: sophisticated Japanese-inspired woodblock / mid-century risograph illustration, crisp silhouettes, charming expressive rat, restrained grain.
Composition/framing: panoramic full-bleed banner, single coherent composition, rat and map comfortably within frame, generous breathing room, readable at 960px wide.
Color palette: paper #f6eedf and #fffaf0, ink #1b1714, strong cobalt #2654d9, coral #d45a43, small gold #f7a63b accents.
Text: no text, no letters, no watermark. Code cards use abstract short lines and bracket-like shapes, not readable words.
Constraints: code intelligence / exploration only; no editing UI, no robot, no glossy 3D, no gradients, no logos.
```

## Dark edit prompt

```text
Use case: lighting-weather
Asset type: GitHub README dark theme banner.
Edit the supplied codedb cartographer illustration into its matching NIGHT EDITION. Keep the same rat, pose, face, cobalt jacket, pencil, map, code cards, paths, mountains, bridge, compass, framing, aspect ratio, linework and woodcut print character. Change only the lighting and palette: replace warm light background and map paper with warm charcoal #100f0d and #191714; render map linework and edges in luminous rice #f3ecdf, blue highlights #91adff, coral #ef8069 and tiny gold #ffc16b. Retain rich cobalt #2654d9 accents. Make the rat and map readable on the dark background, with a cozy moonlit workshop feeling and restrained print grain. No added objects or text; no glow effects, no gradients, no glossy rendering.
```
