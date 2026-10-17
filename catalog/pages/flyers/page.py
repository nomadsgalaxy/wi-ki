"""The Flyers page: how long since the Philadelphia Flyers won the Stanley Cup. They won it in 1974 and again on
27 May 1975, 2-0 over the Buffalo Sabres in Game 6, and not since. Dressed as a night at the arena: the Cup, the days
on the scoreboard in orange lights, the two championship banners in the rafters, the boards and the ice with a stick and
a puck, and Gritty. An orange header with the jersey's white and black stripes and a winged P. In the Flyers' orange,
black and white (only this page uses them).

Options (in playlist.json): won, the date of the last Cup as YYYY-MM-DD (default 1975-05-27), for the happy day it
needs changing. It sets the clock only. The banners (CUPS) are hardcoded, so a new win needs both: the option (or LAST)
and a new year in CUPS.
"""
from datetime import date, datetime
from PIL import Image, ImageDraw

from kit import SCREEN, W, G, text, clock, packed, since

ORANGE, BLACK, SILVER, SHADE, SHINE = (0xf7, 0x49, 0x02), (0, 0, 0), (205, 210, 220), (130, 136, 150), (250, 252, 255)
ARENA, LED_OFF, ICE, BOARDS = (12, 12, 16), (40, 18, 8), (214, 228, 238), (236, 238, 242)
LAST = "1975-05-27"   # the last Cup win. On a new one, update this AND CUPS below: the clock and the banners are separate
CUPS = ("1974", "1975")   # the banners in the rafters. Hardcoded on purpose: they're history, not the option
ICE_Y = SCREEN[1] - 80   # the top of the boards


def sprite(rows, palette):
    """a pixel map (one character a pixel; a space is clear) in the palette's colours, RGBA"""
    img = Image.new("RGBA", (max(map(len, rows)), len(rows)))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != " ":
                img.putpixel((x, y), palette[ch] + (255,))
    return img


def cup(scale):
    """the Stanley Cup in pixels, after the 1975 photographs: the rounded bowl with its flared lip, the narrow collar,
    three little shoulder tiers, then the tall barrel of bands, slightly wider at the foot, lit from the left, RGBA"""
    img = Image.new("RGBA", (40, 72)); d = ImageDraw.Draw(img)
    d.ellipse((8, 0, 31, 5), fill=SHINE)                                        # the lip
    d.chord((10, -8, 29, 13), 0, 180, fill=SILVER); d.ellipse((10, 1, 29, 4), fill=SHADE)   # the bowl, and inside it
    for x in (13, 16, 19, 22, 25):
        d.line((x, 6, x + 1, 11), fill=SHADE)                                   # its fluting
    d.line((12, 5, 14, 10), fill=SHINE)
    d.rectangle((17, 12, 22, 15), fill=SHADE); d.rectangle((17, 12, 18, 15), fill=SILVER)   # the collar
    for top, half in ((15, 6), (18, 8), (21, 10)):                              # the shoulder tiers
        d.rectangle((20 - half, top, 19 + half, top + 2), fill=SILVER)
        d.line((20 - half, top + 2, 19 + half, top + 2), fill=SHADE); d.point((21 - half, top + 1), fill=SHINE)
    for i, top in enumerate(range(24, 66, 8)):                                  # the barrel's bands
        half = 12 + i // 2
        d.rectangle((20 - half, top, 19 + half, top + 7), fill=SILVER)
        d.line((20 - half, top + 7, 19 + half, top + 7), fill=SHADE)            # the seam
        d.line((21 - half, top + 1, 21 - half, top + 5), fill=SHINE)            # the shine
        d.line((19 + half, top, 19 + half, top + 6), fill=SHADE)                # the shadow
        for row in (top + 2, top + 4):
            for nx in range(23 - half, 18 + half, 3):
                d.point((nx, row), fill=SHADE)                                  # the engraved names
    d.rectangle((5, 66, 34, 69), fill=SHADE); d.line((5, 66, 34, 66), fill=SILVER)   # the foot
    return img.resize((40 * scale, 72 * scale), Image.NEAREST)


def scoreboard(s, dot=12):
    """s in lights: each pixel of the VGA font a round lamp, lit orange or dark, RGB"""
    glyphs = Image.new("L", (len(s) * 8, 16)); text_img = Image.new("RGB", glyphs.size); text(text_img, (0, 0), s, W, scale=1)
    lit = text_img.convert("L")
    img = Image.new("RGB", (lit.width * dot, lit.height * dot), BLACK); d = ImageDraw.Draw(img)
    for y in range(lit.height):
        for x in range(lit.width):
            d.ellipse((x * dot + 1, y * dot + 1, x * dot + dot - 2, y * dot + dot - 2), fill=ORANGE if lit.getpixel((x, y)) > 127 else LED_OFF)
    return img


def banner(year):
    """a championship banner for the rafters: orange, trimmed in white and black, RGB"""
    img = Image.new("RGB", (150, 280), ORANGE); d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 149, 279), outline=W, width=6); d.rectangle((8, 8, 141, 271), outline=BLACK, width=3)
    d.polygon([(0, 279), (75, 240), (149, 279)], fill=ARENA)                   # the notch at the bottom
    logo = winged_p().resize((LOGO_W * 2, LOGO_H * 2), Image.NEAREST); img.paste(logo, ((150 - logo.width) // 2, 22), logo)
    for i, word in enumerate(("STANLEY CUP", "CHAMPIONS")):
        text(img, ((150 - len(word) * 8) // 2, 120 + i * 20), word, BLACK, scale=1)
    text(img, ((150 - 4 * 24) // 2, 168), year, W, scale=3)
    return img


# Gritty, from a bead pattern of him (kandipad.com, project pp38490): his fur (g gold, r the red-orange edge), his face
# (o), the helmet (k black, h its grey), eyes (W white, p peach), mouth (m) and tongue (t)
GRITTY = (
    "                    kkkkkkkkkkkkkk                   ",
    "                  kkkhkWkkkkkkkhkkkk                 ",
    "                kkkkkkhkWkkkkkhkkkkkkk               ",
    "               kkkkkkkkhkWkkkhkkWkkkkkk              ",
    "              kkkkkkkkkhkWkkkhkWkkkkkkkk             ",
    "              kkkkkkkkkhkWkkkhkkWWkkkkkk             ",
    "              kkkkkkkkhkWkkkkkhkkkkkkkkk             ",
    "              khhhhhhhkkkkkkkkkhhhhhhhhk             ",
    "              kkkkrrkkkkkkkkkkkkkkrrkkkk r           ",
    "            rrkhhrgrhrrhhhhhhhrrhhrgrhhrrr rr        ",
    "         rrrgrrhhrgrrgrhhhhhhrrgrrgggrrgrrrr         ",
    "          rgrrgrrrggggrrrkkkkkrrgrggrrggrggrrr       ",
    "       rrrrggrgggrgggggggrrorrrggggggggrggggr        ",
    "        rgggggrgggkkkgggrrooorgggkkkgggggggggr       ",
    "         rggggggkkWWWkkgggrorggkkWWWkkggggggrr       ",
    "        rggggggkppppWWWkgrorggkWWWWWWWkggggggrr      ",
    "       rrgggggkppkkWpWWWkroorkWWWWppppWkggggrgr      ",
    "      rggrgggkWpkkWWpWWWkooookWWWppkkWpWkgggrgr      ",
    "     rrgrrggrkWpkkkkpWWWkooookWWWpkkWWpWkrggrggr     ",
    "     rggrgrrooWppkkppWWWooooooWWWpkkkkpWoorrgrggr    ",
    "    rggrggroooWWppppWWWWooooooWWWppkkppWooorggggr    ",
    "   rgggggggoooWWWWWWWWWWooooooWWWWppppWWoooggggggr   ",
    "   rrrgggggooooWWWWWWWWooooooooWWWWWWWWoooogggggggr  ",
    "  rrrrgggggooooooWWWWooooooooooooWWWWooooooggggrggr  ",
    " rrrrggggggooooooooooooooooooooooooooooooooggggrrggr ",
    "rr  rggggggoooooooooooooooooooooooooooooooogggggrrgr ",
    "   rgrgggggoommmoooooooooooooooooooooommmooggggggrrgr",
    "  rgrrgggggoommmmmmmmoooooooooooommmmmmmmoogggggggrrr",
    "  rrrggggggoommmmmmmmmmmmmmmmmmmmmmmmmmmmooggrgggggr ",
    "  rrrggrgggooommmmmmmmmmmmmmmmmmmmmmmmmmooogggrgrggr ",
    " rrrrggrggggooommmmmmmmmmmmmmmmmmmmmmmmmooogggrgrrgr ",
    " rrrgggrgggggoooommmmmmtmmmmmmmmtmmmmmmoooggggrgrrgrr",
    " r rggrrggggggoooommmmmmttmmmmttmmmmmmooogggggrrgrgrr",
    "   rggrggggggggoooooommmmmttttmmmmmoooooggggggrrgrggr",
    "   rgrrggggggggggoooooommmmmmmmmmoooooogggggggrrgrrgr",
    "   rgrrggggggggggggoooooooooooooooooogggggggggrrrrrgr",
    "   rrrrgggggggggggggggoooooooooooogggggggggggggrrrrgr",
    "   rrrrggggggggggggggggggggggggggggggggggggggggrrrrr ",
    "   r rrggggggggggggggggggggggggggggggggggggggggrr rr ",
    "      rggggggggggggggggggggggggggggggggggggggggrr  r ",
    "      rggggrggggggggggggggggggggggggggggggggrggrrr r ",
    "     rrgggrrgggggggggggggggggggggggggrggggggrggrrr r ",
    "     rrgggrrggggrggggggggggggggggggggrggrggrrgggrr   ",
    "     rrgggrrrgggrggggggggggggggggggggrggrggrrrggr    ",
    "     rrggrrrrgggrgggggggggggggggggggrrggrggrrrgrr    ",
    "      rrgrrrrgggrgggggggggggggggggggrrggrggrrrgrr    ",
    "      rrgrrrrggrrgggrggggrggggrrgggrrrrgrrgr rrr     ",
    "      rrgrr rrgrrggrrrggrrrgggrrgggrrrrgrrgr rr      ",
    "       rrrr rrgrrggrrrggrrrgggrrrgrr rrrrrrr r       ",
    "        rrr rrrrrrgrrrggrrrrgrrrrgrr  rrrrrr         ",
    "         rr rrrrrrgrrrrgrrrrgrrrrgr   rr rr          ",
    "          r  rrrrrrr rrrrrrrgr rrrr   r  r           ",
    "             rr  rrr  rrr rrrr rrrr                  ",
    "                 rr     r rrr  rr                    ",
    "                rr        rr  rr                     ",
    "                          r                          ",
)
GRITTY_COLOURS = {"g": (241, 173, 23), "r": (230, 91, 69), "o": (245, 100, 38), "k": (58, 59, 61), "h": (82, 84, 88),
                  "W": (249, 249, 249), "p": (245, 163, 107), "m": (133, 58, 75), "t": (220, 112, 160)}

# the Flyers' winged P, scaled down from the club's own mark to black (k), white (W) and the orange dot (o)
LOGO = (
    "kkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkk",
    "kWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWkkkk",
    "kWkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkWWWkk",
    "kWkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkWWkkk",
    "kWkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkWWkk",
    "kWWkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkWkk",
    "kkWkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkWkk",
    " kWWkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkWWkk",
    " kkWWkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkWWk",
    "kkkkWWWkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkWkk",
    "kWWWWWWWWWWWWWWWWWWWWWWkkkkkkkkkkkkWWWWWWkkkkkkkkkkkkWk",
    "kWkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkWWWWWWWWWkkkkkkkkkkWk",
    "kWkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkWWWWWWWWWWWWkkkkkkkkkWkk",
    "kWkkkkkkkkkkkkkkkkkkkkkkkkkkkkkkWWWWWoooWWWWWkkkkkkkkkWk",
    "kWWkkkkkkkkkkkkkkkkkkkkkkkkkkkkWWWWooooooWWWWkkkkkkkkkWk",
    "kkWkkkkkkkkkkkkkkkkkkkkkkkkkkkWWWWooooooooWWWWkkkkkkkkWk",
    " kWWkkkkkkkkkkkkkkkkkkkkkkkkkkWWWWooooooooWWWWkkkkkkkkWk",
    " kkWWkkkkkkkkkkkkkkkkkkkkkkkkWWWWWoooooooooWWWkkkkkkkkWk",
    "kkkkWWWkkkkkkkkkkkkkkkkkkkkkkWWWWWoooooooooWWWkkkkkkkkWk",
    "kWWWWWWWWWWWWWWWWWkkkkkkkkkkWkkWWWooooooooWWWWkkkkkkkkWk",
    "kWkkkkkkkkkkkkkkkkkkkkkkkkkWWkkWWWWoooooooWWWkkkkkkkkkWk",
    "kWkkkkkkkkkkkkkkkkkkkkkkkkkWkkkWWWWWoooooWWWWkkkkkkkkkWk",
    "kWkkkkkkkkkkkkkkkkkkkkkkkkWkkkkkWWWWWWWWWWWWkkkkkkkkkWWk",
    "kWWkkkkkkkkkkkkkkkkkkkkkkkWkkkkkkWWWWWWWWWWkkkkkkkkkkWkk",
    "kkWkkkkkkkkkkkkkkkkkkkkkkWkkkkkkkkWWWWWWWWkkkkkkkkkkkWk",
    " kWWkkkkkkkkkkkkkkkkkkkkWWkkkkkkkkkkkkkkkkkkkkkkkkkkWkk",
    " kkWWkkkkkkkkkkkkkkkkkkkWkkkkkkkkkkkkkkkkkkkkkkkkkkkWk",
    "kkkkWWWkkkkkkkkkkkkkkkkWWkkkkkkkkkkkkkkkkkkkkkkkkkkWkk",
    "kWWWWWWWWWWWWkkkkkkkkkkWkWkkkkkkkkkkkkkkkkkkkkkkkkWkk",
    "kWkkkkkkkkkkkkkkkkkkkkWkkkWkkkkkkkkkkkkkkkkkkkkkkWkk",
    "kWkkkkkkkkkkkkkkkkkkkWWk kkWkkkkkkkkkkkkkkkkkkkkWkk",
    "kWkkkkkkkkkkkkkkkkkkkWkk  kkWWkkkkkkkkkkkkkkkkWWkk",
    "kWWkkkkkkkkkkkkkkkkkWkk    kkkWWkkkkkkkkkkkkWWWkk",
    "kkWkkkkkkkkkkkkkkkkkWk       kkkWWWkkkkkkWWWWkkk",
    " kWWkkkkkkkkkkkkkkkWkk         kkkkWWWWWWkkkkk",
    " kkWWkkkkkkkkkkkkkWWk             kkkkkkkk",
    "  kkWWWkkkkkkkkkkkWkk",
    "   kkkWWWWWWWWWWWWkk",
    "     kkkkkkkkkkkkkk",
)
LOGO_COLOURS = {"k": BLACK, "W": (255, 255, 255), "o": ORANGE}   # the mark's pure white, not the kiosk's
LOGO_W, LOGO_H = max(map(len, LOGO)), len(LOGO)


GRITTY_W = max(map(len, GRITTY))


def gritty():
    return sprite(GRITTY, GRITTY_COLOURS)


def winged_p():
    return sprite(LOGO, LOGO_COLOURS)


WOOD, WOOD_DARK, TAPE_GREY = (204, 158, 100), (146, 100, 56), (70, 70, 76)


def stick():
    """a hockey stick leaning on the boards, 64x24 pixels, RGBA: the wooden shaft running down from its white knob tape,
    the heel's bend, and the blade flat on the ice, taller than the shaft, taped black, its toe curling up"""
    img = Image.new("RGBA", (64, 24)); d = ImageDraw.Draw(img)
    d.line((4, 0, 45, 19), fill=WOOD, width=3)                                 # the shaft
    d.line((5, 2, 45, 21), fill=WOOD_DARK)                                     # its shaded edge
    d.line((4, 0, 11, 3), fill=W, width=3)                                     # the knob tape
    d.polygon([(44, 18), (48, 19), (48, 23), (43, 22)], fill=WOOD)              # the heel
    d.polygon([(47, 19), (60, 19), (63, 16), (63, 18), (61, 23), (47, 23)], fill=BLACK)   # the blade, taped, toe up
    for x in (50, 54, 58):
        d.line((x, 19, x - 1, 23), fill=TAPE_GREY)                             # the tape's wraps
    return img


def puck():
    """a puck on the ice, seen from the side and a little above, 10x5 pixels, RGBA"""
    img = Image.new("RGBA", (10, 5)); d = ImageDraw.Draw(img)
    d.ellipse((0, 0, 9, 3), fill=TAPE_GREY); d.rectangle((0, 2, 9, 3), fill=BLACK); d.ellipse((0, 2, 9, 4), fill=BLACK)
    return img


def wait(last, today):
    """(days, words) since last; a date still to come is 0 days and "coming up", never a negative count"""
    return (max(0, (today - last).days), since(last, today)) if last <= today else (0, "coming up")


def draw(now, won=LAST):
    """the whole page, RGB at the screen's size"""
    last = date.fromisoformat(won)
    img = Image.new("RGB", SCREEN, ARENA); d = ImageDraw.Draw(img)
    # the header: orange, the winged P, and the jersey's stripes under it
    d.rectangle((0, 0, SCREEN[0], 52), fill=ORANGE)
    for y, colour in ((52, W), (58, BLACK), (64, W)):
        d.rectangle((0, y, SCREEN[0], y + 5), fill=colour)
    logo = winged_p(); img.paste(logo, (24, 7), logo)
    text(img, (100, 10), "PHILADELPHIA FLYERS", BLACK, scale=2)
    text(img, (100 + 20 * 16, 10), "· STANLEY CUP WATCH", W, scale=2)
    text(img, (SCREEN[0] - 24, 10), clock(now), BLACK, scale=2, right=True)
    # the boards and the ice
    d.rectangle((0, ICE_Y, SCREEN[0], ICE_Y + 34), fill=BOARDS)
    d.rectangle((0, ICE_Y + 24, SCREEN[0], ICE_Y + 34), fill=ORANGE)           # the kick plate
    d.rectangle((0, ICE_Y + 34, SCREEN[0], SCREEN[1]), fill=ICE)
    d.rectangle((0, ICE_Y + 44, SCREEN[0], ICE_Y + 48), fill=(196, 40, 40))     # the red line
    st = stick().resize((64 * 4, 24 * 4), Image.NEAREST); img.paste(st, (360, SCREEN[1] - 12 - st.height), st)   # against the boards
    pk = puck().resize((10 * 4, 5 * 4), Image.NEAREST); img.paste(pk, (360 + st.width + 30, SCREEN[1] - 14 - pk.height), pk)
    # the Cup
    trophy = cup(5)
    img.paste(trophy, (60, ICE_Y - trophy.height + 4), trophy)
    # the scoreboard
    days, words = wait(last, now.date())
    lights = scoreboard(f"{days:,}", dot=9)
    X, Y, title = 340, 92, "DAYS SINCE THE FLYERS WON THE STANLEY CUP"
    inner = max(lights.width, len(title) * 16)   # as wide as the lights or the title, whichever's wider
    d.rectangle((X, Y, X + inner + 48, Y + 56 + lights.height + 24), fill=BLACK, outline=ORANGE, width=4)
    text(img, (X + 24, Y + 18), title, ORANGE, scale=2)
    img.paste(lights, (X + 24 + (inner - lights.width) // 2, Y + 56))
    text(img, (X, Y + 56 + lights.height + 36), f"{words} · {last.day} {last.strftime('%B %Y')}", W, scale=2)
    if won == LAST:
        text(img, (X, Y + 56 + lights.height + 70), "2-0 over Buffalo, Game 6", G, scale=2)
    # the rafters: a girder and the banners hanging from it
    d.rectangle((1190, 70, 1540, 78), fill=(40, 40, 48))
    for i, year in enumerate(CUPS):
        img.paste(banner(year), (1200 + i * 175, 78))
    # Gritty, over the boards
    g = gritty().resize((GRITTY_W * 6, len(GRITTY) * 6), Image.NEAREST)
    img.paste(g, (SCREEN[0] - g.width - 30, ICE_Y + 30 - g.height), g)
    d.rectangle((SCREEN[0] - g.width - 50, ICE_Y, SCREEN[0], ICE_Y + 34), fill=BOARDS)   # the boards in front of him
    d.rectangle((SCREEN[0] - g.width - 50, ICE_Y + 24, SCREEN[0], ICE_Y + 34), fill=ORANGE)
    return img


class Page:
    """the wait, as a page of the kiosk's cycle"""
    name, seconds = "flyers", 15

    def __init__(self, won=LAST):
        date.fromisoformat(won)   # a bad date in the playlist fails here, so the page is left out and says why
        self.won, self.bg = won, (None, None)

    def start(self, now):
        pass

    def background(self, now):
        key = (now.date(), now.minute)
        if key != self.bg[0]:
            self.bg = (key, packed(draw(now, self.won)))
        return self.bg

    def regions(self, now, t):
        return []


def check():
    now = datetime(2026, 10, 15, 16, 30)
    assert (now.date() - date(1975, 5, 27)).days == 18769 and since(date(1975, 5, 27), now.date()) == "51 years, 141 days"
    assert cup(1).size == (40, 72) and cup(1).getbbox() is not None and gritty().getbbox() and stick().getbbox() and puck().getbbox()
    assert winged_p().getbbox() and winged_p().getpixel((LOGO_W // 2, 0))[3] == 255
    assert all(ch in GRITTY_COLOURS for row in GRITTY for ch in row if ch != " "), "every bead has a colour"
    assert scoreboard("1").size == (8 * 12, 16 * 12) and banner("1975").size == (150, 280)
    assert wait(date(2027, 6, 14), now.date()) == (0, "coming up") and wait(date(1975, 5, 27), now.date())[0] == 18769
    for won in (LAST, "2027-06-14"):
        assert draw(now, won).size == SCREEN
    page = Page()
    key, bg = page.background(now)
    assert bg.mode == "LA" and page.background(now)[0] == key and page.regions(now, 0) == []
    try:
        Page("someday"); raise AssertionError("a bad date should fail")
    except ValueError:
        pass


def preview(now=None):
    """the page, for the emulator and kiosk.py --png"""
    import kit
    return kit.unpack(Page().background(now or datetime(2026, 10, 15, 16, 30))[1])
