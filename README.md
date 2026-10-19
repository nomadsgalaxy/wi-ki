# Wi-Ki

Wide Kiosk: the base OS and catalog for every kiosk I run, from my desks to the screens at Hive76. It's built for a Raspberry Pi Zero W on a 12.6" stretched bar screen (1920×515), and it cycles through pages: the weather, with a pixel-art Philly skyline that plays the real weather, time of day and season; a flight radar of what's overhead; my latest GitHub pushes; my agents and their usage; my desktop's CPU, GPU, memory and network; what's playing, with the cover, synced lyrics and a live spectrum; and more in the catalog.

Every kiosk runs the same code. What makes one kiosk different from another lives on the kiosk itself, in `~/.config/kiosk/`, not in a branch.

## Setting one up

- **[A kiosk](docs/kiosk.md):** from a blank SD card to your pages, set up from a browser.
- **[A render server](docs/server.md):** draws the pages for a kiosk, so a Pi Zero can show the heavy ones smoothly, and
  shows the kiosk in a browser.
- **[Connectors](docs/connectors.md):** your desktop's repos, agents, system and music, and calendar events.
- **[Working on Wi-Ki](docs/develop.md):** writing pages and transitions, the layout, tests and updates.

## What's in it

A kiosk comes with a small core: the weather, radar and calendar pages, and the Nomads Galaxy and Matrix transitions.
Everything else is installed from the setup page's **Install** tab: from the catalog, where every page and transition
has been reviewed, or from someone's GitHub repo. [`catalog/CATALOG.md`](catalog/CATALOG.md) lists everything in the catalog, with what each needs.

Between pages, a transition plays for about 3 seconds. Nothing flashes the whole screen, so they're safe for anyone
sensitive to flicker.

## Credits

The setup page's first-boot passwords use the [EFF short word list](https://www.eff.org/dice) (`kiosk/words.txt`), by the Electronic Frontier Foundation, licensed [CC BY 3.0 US](https://creativecommons.org/licenses/by/3.0/us/). The skyline is traced from [The Philadelphia skyline (cropped)](https://commons.wikimedia.org/wiki/File:The_Philadelphia_skyline_(cropped).jpg) by Mefman00, licensed [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), and the pixel art is shared under the same licence. The text uses the VGA console font from Debian's `console-setup`; its notice is in [`kiosk/fonts/LICENSE`](kiosk/fonts/LICENSE). Forecasts come from [Open-Meteo](https://open-meteo.com), flights from [adsb.lol](https://adsb.lol), or [adsb.fi](https://adsb.fi) when it's away, and routes from [adsbdb.com](https://www.adsbdb.com). The radar's street map is © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL). Every other page's and transition's credits are in its catalog entry.

## Licence

Wi-Ki is built by NomadsGalaxy, and it comes under two licences:

- **The pages and transitions are MIT** ([`LICENSE-MIT`](LICENSE-MIT)): everything in `catalog/pages/` and `catalog/transitions/`.
- **Everything else is the engine,** under the Open Community Licence with the Software Attribution add-on: **OCL v1.1 + SWAtt v1**. That's `kit.py`, `kiosk.py`, the transitions' player and `canvas.py`, the setup and update code, the feeds and the tools.

A page's own code is MIT even though it runs inside the OCL engine; the engine's terms still cover the engine. If you share something built on the engine, say so where people use it and in its source: "Built By NomadsGalaxy", linking to [nomadsgalaxy.com](https://nomadsgalaxy.com). Ours says it at the top of `kiosk/kit.py`. The texts are in [`LICENSE`](LICENSE) and [`LICENSE-SWAtt-v1.md`](LICENSE-SWAtt-v1.md), copied unchanged from [OpenCommunityLicence/OpenCommunityLicence](https://github.com/OpenCommunityLicence/OpenCommunityLicence) (commit `7469fcd`). The assets and data keep their own licences: the skyline's pixel art, for one, stays CC BY-SA 4.0.
