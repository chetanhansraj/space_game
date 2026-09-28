# Imagery

| File | What it is | Source and licence |
|---|---|---|
| `moon_albedo.jpg` | Lunar albedo map, equirectangular, longitude 0 at centre | CesiumJS `Assets/Textures/moonSmall.jpg`, Apache-2.0 (see `LICENSE-cesium.md`). The game adds procedural crater detail on top at runtime. |
| `earth_ne2.jpg` | Earth, equirectangular | Natural Earth II (public domain, naturalearthdata.com), as tiled in CesiumJS `Assets/Textures/NaturalEarthII`, level 2, stitched to 2048 x 1024. |
| `sky/*.jpg` | Star-field cube map | Tycho-2 star catalogue sky box from CesiumJS `Assets/Textures/SkyBox`, Apache-2.0. Real stars; the cube is not yet aligned to the scene's frame, so constellations are not where they would be seen from the Moon. |

All three came from the `@cesium/engine` 26.3.0 npm package. The next upgrade
is NASA's CGI Moon Kit (LRO colour and LOLA elevation, public domain), which
is what lunarark.com's `moon_sim.html` already uses; it was not reachable
from the build environment when this was assembled.
