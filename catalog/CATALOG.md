# The kiosks' catalog

Written by `catalog/catalog.py --table` from the files beside it; edit those, not this. Same hash, same code.

Installing a pack asks for anything it needs a fresh API token or a server for, and nothing else, plus septa's sfw. Locations and titles have working defaults, so they aren't asked.

**Licences.** Pages and transitions are MIT (`LICENSE-MIT`): everything in `catalog/pages/`, and the theme files in `catalog/transitions/`. A page's code stays MIT while it runs inside the engine. The engine is everything else (`kit.py`, `kiosk.py`, the transitions' `__init__.py` and `canvas.py`, the setup server, updates, feeds and tools), under the Open Community Licence with the Software Attribution add-on, `OCL v1.1 + SWAtt v1` (`LICENSE`, `LICENSE-SWAtt-v1.md`). The engine isn't open source in the OSI sense. SWAtt means anyone distributing a derivative has to show who built it in its UI and in its source (for a kiosk, on the screen), and it forbids systematic or automated text and data mining without permission. The attribution is "Built By NomadsGalaxy", linking to nomadsgalaxy.com, in `kit.py`'s header. Packs run inside the engine, so they don't carry it. Assets keep their own licences, listed per entry.

**Fonts.** The VGA font every page uses, `Uni2-VGA16.psf.gz`, comes from Debian's `console-setup`: Dmitry Bolkhovityanov's u_vga16 under an MIT/X11-style licence, plus legacy console glyphs that console-setup lists as public domain. Its notice is in `kiosk/fonts/LICENSE`. Any new font comes from Google Fonts.

| name | kind | home | what it is | versions | needs | quality |
|---|---|---|---|---|---|---|
| home | page | core | the touch launcher: a tile for every page | one, on main `d883df` | touch | unchecked |
| agents | page | public | what a desktop's herdr workspaces are doing, and, if it has KodexBar, how much of each AI plan it's used. Needs the desk feed (feed/deskfeed.py) on that desktop: feed/README.md has the steps. | one, on main `f25d4e` | asks: feed, render server | unchecked |
| around | page | public | the blocks around a place: 311 reports, permits and bike-share stations (Hive76 and Philadelphia's open data by default, a few other cities ready to pick, or any city's Open311 and GBFS feeds) | one, on main `5ce517` | gbfs.bcycle.com, gbfs.bluebikes.com, gbfs.capitalbikeshare.com, gbfs.citibikenyc.com, gbfs.divvybikes.com, gbfs.lyft.com, mobile311.sfgov.org, overpass-api.de, overpass.private.coffee, phl.carto.com | unchecked |
| calendar | page | public | the next two weeks, with each day's weather and events | one, on main `9a33ff` | – | unchecked |
| cfradar | page | public | Pennsylvania's internet traffic, from Cloudflare Radar | one, on main `70adfa` | api.cloudflare.com, secret: a Cloudflare API token with Radar Read, asks: a Cloudflare API token with Radar Read | unchecked |
| flyers | page | public | how long since the Flyers won the Cup | one, on main `1846e5` | – | unchecked |
| github | page | public | open PRs, issues and recent pushes for you and your orgs (or the owners you name). Needs the desk feed (feed/deskfeed.py) on the desktop whose GitHub it shows: feed/README.md has the steps. | one, on main `bbec1f` | asks: feed, render server | unchecked |
| halflife3 | page | public | is Half-Life 3 out yet? | one, on main `ed36be` | store.steampowered.com | unchecked |
| nowplaying | page | public | whatever my desktop is playing, with lyrics and a live spectrum. Needs the now-playing feed (feed/nowplaying.py) on the desktop it shows: feed/README.md has the steps. | one, on main `ce7ed4` | asks: folder, render server | unchecked |
| radar | page | public | what's flying overhead, on a live map | one, on main `7e79d9` | api.adsb.lol, api.adsbdb.com, mesonet.agron.iastate.edu, opendata.adsb.fi, overpass-api.de, overpass.private.coffee | unchecked |
| septa | page | public | is SEPTA fucked? Installing it asks whether to say "fcked" (sfw) | one, on main `a3f531` | isseptafucked.com, asks: sfw | unchecked |
| sports | page | public | your teams' scores, next games and records: up to five, from the NFL, MLB, NHL, NBA and MLS | one, on main `584ba4` | site.api.espn.com, a.espncdn.com | unchecked |
| system | page | public | my desktop's CPU, GPU, memory and network, live. The owner will pick what it shows, but the code doesn't do that yet. Needs the system feed (feed/sysfeed.py) on the desktop it shows: feed/README.md has the steps. | one, on main `0a244e` | asks: file, render server | unchecked |
| weather | page | public | Philly's skyline playing the real weather, and the forecast | one, on main `1cf98a` | api.open-meteo.com | unchecked |
| cherdenko | transition | public | Premier Cherdenko escapes to space, as a Soviet-era poster: "I'm escaping to the one place not corrupted by capitalism...", a withheld laugh, SPACE!!!!, and the whole poster blasts off on a rocket flame | one, on main `e1c72b` | – | unchecked |
| coreone | transition | public | the page is printed layer by layer by a hotend | one, on main `9f47db` | – | unchecked |
| hackerman | transition | public | a neon terminal hacks time while the page glitches in | one, on main `859d09` | – | unchecked |
| hive76 | transition | public | honeycomb cells fill with honey, and a bee flies past | one, on main `f7f4b1` | – | unchecked |
| johnny5 | transition | public | Johnny 5: a comic page, his head struck by lightning, ZZZAP!, NEED INPUT!, then arms up under NUMBER 5 IS ALIVE! | one, on main `02bc9c` | – | unchecked |
| matrix | transition | public | a curtain of green code rain | one, on main `9d0423` | – | unchecked |
| nomadsgalaxy | transition | public | warp: Warp Cyan beams, and the Drifter flies through | one, on main `fec696` | – | unchecked |
