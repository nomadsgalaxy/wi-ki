# The kiosks' catalog

Written by `catalog/catalog.py --table` from the files beside it; edit those, not this. Same hash, same code.

Installing a pack asks for anything it needs a fresh API token or a server for, and nothing else, plus septa's sfw. Locations and titles have working defaults, so they aren't asked.

**Licences.** Pages and transitions are MIT (`LICENSE-MIT`): everything in `catalog/pages/`, and the theme files in `catalog/transitions/`. A page's code stays MIT while it runs inside the engine. The engine is everything else (`kit.py`, `kiosk.py`, the transitions' `__init__.py` and `canvas.py`, the setup server, updates, feeds and tools), under the Open Community Licence with the Software Attribution add-on, `OCL v1.1 + SWAtt v1` (`LICENSE`, `LICENSE-SWAtt-v1.md`). The engine isn't open source in the OSI sense. SWAtt means anyone distributing a derivative has to show who built it in its UI and in its source (for a kiosk, on the screen), and it forbids systematic or automated text and data mining without permission. The attribution is "Built By NomadsGalaxy", linking to nomadsgalaxy.com, in `kit.py`'s header. Packs run inside the engine, so they don't carry it. Assets keep their own licences, listed per entry.

**Fonts.** The VGA font every page uses, `Uni2-VGA16.psf.gz`, comes from Debian's `console-setup`: Dmitry Bolkhovityanov's u_vga16 under an MIT/X11-style licence, plus legacy console glyphs that console-setup lists as public domain. Its notice is in `kiosk/fonts/LICENSE`. Any new font comes from Google Fonts.

| name | kind | home | what it is | versions | needs | quality |
|---|---|---|---|---|---|---|
| home | page | core | the touch launcher: a tile for every page | one, on main `a64fdd` | touch | unchecked |
| agents | page | public | what a desktop's herdr workspaces are doing, and, if it has KodexBar, how much of each AI plan it's used. Needs the desk feed (feed/deskfeed.py) on that desktop: feed/README.md has the steps. | one, on main `59784f` | asks: feed, render server | unchecked |
| air | page | public | the US air quality index, what's in the air and the UV, now and for the next 24 hours | one, on main `0d70c8` | air-quality-api.open-meteo.com | unchecked |
| around | page | public | the blocks around a place: 311 reports, permits and bike-share stations (Philadelphia's open data by default, a few other cities ready to pick, or any city's Open311 and GBFS feeds) | one, on main `6a3356` | gbfs.bcycle.com, gbfs.bluebikes.com, gbfs.capitalbikeshare.com, gbfs.citibikenyc.com, gbfs.divvybikes.com, gbfs.lyft.com, mobile311.sfgov.org, overpass-api.de, overpass.private.coffee, phl.carto.com | unchecked |
| calendar | page | public | the next two weeks, with each day's weather and events | one, on main `22a5ad` | – | unchecked |
| cfradar | page | public | Pennsylvania's internet traffic, from Cloudflare Radar | one, on main `11c9b3` | api.cloudflare.com, secret: a Cloudflare API token with Radar Read, asks: a Cloudflare API token with Radar Read | unchecked |
| flyers | page | public | how long since the Flyers won the Cup | one, on main `d4286a` | – | unchecked |
| github | page | public | open PRs, issues and recent pushes for you and your orgs (or the owners you name). Needs the desk feed (feed/deskfeed.py) on the desktop whose GitHub it shows: feed/README.md has the steps. | one, on main `59bc45` | asks: feed, render server | unchecked |
| halflife3 | page | public | is Half-Life 3 out yet? | one, on main `5dd971` | store.steampowered.com | unchecked |
| nowplaying | page | public | whatever my desktop is playing, with lyrics and a live spectrum. Needs the now-playing feed (feed/nowplaying.py) on the desktop it shows: feed/README.md has the steps. | one, on main `99983e` | asks: folder, render server | unchecked |
| radar | page | public | what's flying overhead, on a live map | one, on main `2c7435` | api.adsb.lol, api.adsbdb.com, mesonet.agron.iastate.edu, opendata.adsb.fi, overpass-api.de, overpass.private.coffee | unchecked |
| septa | page | public | is SEPTA fucked? Installing it asks whether to say "fcked" (sfw) | one, on main `a54386` | isseptafucked.com, asks: sfw | unchecked |
| sky | page | public | the sky all the way round, as it is now, over a pixel skyline: the sun by day, then the stars, constellations, planets and moon as it gets dark and the windows light up | one, on main `315080` | api.open-meteo.com | unchecked |
| sports | page | public | your teams' scores, next games and records: up to five, from the NFL, MLB, NHL, NBA and MLS | one, on main `9dcb9f` | site.api.espn.com, a.espncdn.com | unchecked |
| system | page | public | my desktop's CPU, GPU, memory and network, live. The owner will pick what it shows, but the code doesn't do that yet. Needs the system feed (feed/sysfeed.py) on the desktop it shows: feed/README.md has the steps. | one, on main `03abe1` | asks: file, render server | unchecked |
| weather | page | public | Philly's skyline playing the real weather, and the forecast | one, on main `cea17c` | api.open-meteo.com | unchecked |
| xkcd | page | public | the latest xkcd comic (or a random one), as big as it fits, with its alt text beside it | one, on main `8fa710` | xkcd.com, imgs.xkcd.com | unchecked |
| cherdenko | transition | public | Premier Cherdenko escapes to space, as a Soviet-era poster: "I'm escaping to the one place not corrupted by capitalism...", a withheld laugh, SPACE!!!!, and the whole poster blasts off on a rocket flame | one, on main `71b5c4` | – | unchecked |
| coreone | transition | public | the page is printed layer by layer by a hotend | one, on main `9f47db` | – | unchecked |
| hackerman | transition | public | a neon terminal hacks time while the page glitches in | one, on main `859d09` | – | unchecked |
| hive76 | transition | public | honeycomb cells fill with honey, and a bee flies past | one, on main `f7f4b1` | – | unchecked |
| johnny5 | transition | public | Johnny 5: a comic page, his head struck by lightning, ZZZAP!, NEED INPUT!, then arms up under NUMBER 5 IS ALIVE! | one, on main `02bc9c` | – | unchecked |
| matrix | transition | public | a curtain of green code rain | one, on main `9d0423` | – | unchecked |
| nomadsgalaxy | transition | public | warp: Warp Cyan beams, and the Drifter flies through | one, on main `fec696` | – | unchecked |
| pacman | transition | public | a maze builds over the old page, and Pac-Man eats his way through it to the new one | one, on main `a9eaef` | – | unchecked |
| swanson | transition | public | oak planks fall into place, pixel-art Ron Swanson rises on the right beside one of his quotes on a pinned card, then he sinks away and the planks fall out below | one, on main `f24be9` | ron-swanson-quotes.herokuapp.com | unchecked |
| tetris | transition | public | the stack fills the screen fast, then an I piece drops in the well: TETRIS! and it all clears to the new page | one, on main `110942` | – | unchecked |
| xkcd_panel | transition | public | a small xkcd comic between pages, in xkcd's look: a sheet of paper slides down with its hand-lettered title and alt text, the comic prints in, then the sheet slides up off the new page | one, on main `87163c` | xkcd.com, imgs.xkcd.com | unchecked |
