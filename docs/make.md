# Making a page or a transition

A page is what a kiosk shows for a while, like the weather or the calendar. A transition is what plays for a few
seconds between two pages. Both are a little Python, and Wi-Ki does the hard parts for you: drawing to the screen,
fetching in the background, and staying up when something goes wrong.

You need a copy of this repo and Python 3 with Pillow (`python3-pil` on Debian). No Pi needed until you want to see it
on one.

## A page

1. **Start it:**
   ```
   python3 -I catalog/catalog.py --new page hello
   ```
   This makes `catalog/pages/hello/` from the template, and its catalog file, `catalog/entries/hello.json`. The page
   works as it is: it shows a heading and a number.

2. **Look at it:**
   ```
   python3 -I kiosk/kiosk.py --png hello hello.png
   ```

3. **Make it yours** in `catalog/pages/hello/page.py`. It's one class, and you only fill in what you need:

   ```python
   class Page(Simple):
       name, seconds = "hello", 20          # its name, and how long it stays up
       every = 600                          # run fetch() every 10 minutes
       SAMPLE = {"title": "HELLO", "count": 42}

       def __init__(self, title=None):      # its settings, each with a default that works
           self.title = title

       def fetch(self):                     # get the data
           ...

       def draw(self, img, now, data):      # draw the page
           ...

       def moving(self, now, t, data):      # optional: anything that moves
           ...
   ```

   - **`draw(img, now, data)`** draws on `img`, a Pillow picture the size of the screen (1920×515 on the bar), already
     cleared to the background. `data` is whatever `fetch()` returned. It runs again when the minute changes or new data
     comes in, so it can take its time.
   - **`fetch()`** gets the data: from the internet with `urllib.request`, from a file, from anywhere. It runs in the
     background every `every` seconds. If it raises, the page keeps the data it had and tries again in a minute. Until
     it works the first time, the page says it's waiting. A page with nothing to fetch leaves out `fetch()` and `every`,
     and its `data` is `None`.
   - **`SAMPLE`** is what `fetch()` returns, written out. The checks and the preview draw with it, so they never touch
     the network.
   - **`moving(now, t, data)`** gives the small things that change every frame, like a blinking cursor or a live dot,
     as `[(picture, (x, y))]`. `t` is seconds since the page came up. Keep them small: each one is copied to the screen
     4 times a second.
   - **Settings** are `__init__`'s arguments. A kiosk's playlist sets them, and so can its setup page once the
     catalog file says how (its `form`, see `kiosk/form.py`).

   `kit.py` has what every page shares: the colours (`O`, `W`, `G`, `C`, `A` and the rest, from the Nomads Galaxy
   brand), the VGA font (`text()`), the page heading (`masthead()`), weather icons, meters and times. Use those rather
   than your own, so it looks like the rest of the kiosk.

4. **Check it:**
   ```
   python3 -I kiosk/kiosk.py --check
   ```
   Every page's `check()` runs. A Simple page's draws `SAMPLE`, the waiting screen, and 20 broken versions of `SAMPLE`
   (fields missing, text empty or huge or in other scripts, numbers of the wrong type), and checks that what moves stays
   on the screen. So write `draw()` for anyone's data: `.get()` with a default, `str()` before you draw a number, and
   `[:n]` on text that could be long. `python3 -I kiosk/fuzz.py hello 200` tries more and shows where it broke.

### Pages like the ones Wi-Ki comes with

Most of the catalog's pages are made this way, so they're the examples. Each thing below is a line or two in the page:

| what the page needs | how | like |
|---|---|---|
| data from the internet, fetched once for every screen a render server draws | `fetch()` and `every`. The data goes in a cache file every renderer shares, one for each set of options; `cache = "..."` names it yourself | septa, cfradar |
| to fetch more often while something's on | `every` as a `@property` | sports (every 30 s during a game) |
| data a desktop or another program writes | `file = "..."`: read again whenever it changes | github, agents, system, now playing |
| to check data before drawing it | `clean(data)` returns the data as `draw()` wants it, or `None` to keep what it had | sports, system, weather |
| to say why the data's missing | `self.problem` is why the last fetch failed: raise an exception that says it the way the page should | septa, cfradar |
| to show how old the data is | `self.updated` (a time) and `self.age()` (seconds) | weather, system |
| to redraw less often than every minute | `redraw_on(now)`: return what the picture depends on, like `now.date()` | halflife3 |
| smooth animation | `fps = 20`, and `moving()` handing back pictures packed ahead of time (`kit.packed()`), or whole rows of raw bytes | now playing, septa's train |
| to animate part of its own picture | `self.drawn` is the packed picture showing now, to crop from | now playing, agents |
| to sit out the rotation | `active()`: return `False` when there's nothing to show (call `self.load()` first for the latest data) | now playing, github |
| touches | `touch(x, y)`, then `self.redraw()` | around (which writes the full interface) |
| more than one shape (TVs, phones) | `shapes = ("bar", "16-9", "9-16")`, and draw to `img.size` | radar (which writes the full interface) |
| anything else in the background, like logos | your own thread, then `self.redraw()` when it's done | sports |

In tests, `Page.showing(data)` is the page drawing that data, never fetching or reading.

**What `Simple` doesn't do yet:** a page with several sources, each fetched on its own clock, like radar (planes,
routes, a street map and the rain) or around (311 reports, bikes and streets). Those two, and the home page, still
write the whole page interface themselves.

## A transition

1. **Start it:**
   ```
   python3 -I catalog/catalog.py --new transition blinds
   ```
   This makes `catalog/transitions/blinds.py` and its catalog file. The template opens the new page like a blind.

2. **Look at it:** `python3 -I kiosk/kiosk.py --png blinds blinds.png` makes a sheet of eight frames.

3. **Make it yours.** A transition is one function, `shown(t)`: given how far along it is, from 0 (none of the new page)
   to 1 (all of it), it returns the parts of the new page that are showing, as rectangles `(x, y, w, h)`:

   ```python
   def shown(t):
       h = -(-HEIGHT // BLINDS)
       return [(0, y, WIDTH, round(t * h)) for y in range(0, HEIGHT, h)]

   frames = simple(shown)
   ```

   A part stays showing once it's shown, so you can return everything that's showing each time. `SECONDS` sets how long
   it plays (3 if you leave it out).

4. **Keep it quick on a Pi Zero.** Every rectangle is a copy each frame, and a rectangle narrower than the screen is a
   copy for every row of it. A frame should stay under about 600 copies. Rectangles the whole width of the screen are
   the cheapest.

5. **Never flash the whole screen.** No full-screen flicker faster than about 3 times a second: it's a seizure risk.

`kiosk.py --check` plays every transition and checks that it starts from the old page, shows the new one along the way,
moves, and ends on the new page.

A transition that draws things on top (a sprite flying past, a glow) is more work. Start from the ones in
`catalog/transitions/` instead: they write `frames(canvas, count)` themselves, with `canvas.py`'s `reveal()`, `draw()`
and `fill()`.

## Getting it onto a kiosk

- **Into the catalog,** for everyone: fill in its catalog file (`python3 -I catalog/catalog.py --check` says what's
  missing, like what it's `about` and the hosts it contacts), then open a pull request. Once it's merged, every kiosk
  can install it from its setup page.
- **From your own repo:** put the page folder or the transition's file in a GitHub repo of yours, and install it from
  the kiosk's setup page, under **Install**. [develop.md](develop.md#publishing-a-page-or-transition-from-your-own-repo) says how the repo has to be laid out.
- **Straight to a Pi you're working on:** `deploy/deploy.sh` copies your working copy over.

`AGENTS.md` has the rules every page and transition keeps, and [develop.md](develop.md) the rest of working on Wi-Ki.
A page that needs more than `Simple` gives, like the radar's map or now playing's 20 frames a second, can write the
whole page interface itself: `kiosk/kiosk.py`'s docstring describes it.
