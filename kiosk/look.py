"""look: how the setup pages look, the setup page (admin.py) and the Wi-Fi rescue page (rescue.py) alike. A terminal,
drawn with ordinary HTML: a cyan title bar, tabs, panels that are <fieldset>s with their name in the frame, buttons in
[brackets], in the system's monospace font and the kiosk's own colours (kit.py's brand tokens). The brackets and frame
corners are CSS, so a screen reader hears "Pages" and "remove", not box-drawing characters.

No script, no web font and no image, so the pages' CSP stays default-src 'none', and it's one stylesheet, inlined in
each page (about 3 KB): a Zero sends it in a blink, and the rescue page needs no route of its own for it.

The colours are kit.py's, as hex (importing kit would load Pillow into the setup page): the check makes sure they still
match. D, kit's dimmest grey, isn't used for any text: it's too faint to read on the background (2.6:1), so secondary
text is G (8.1:1) and D only draws lines.
"""
import html

BG, PANEL, RULE = "#05060f", "#0a0c1f", "#1b323a"            # Deep Space, Raised Space, the Hairline
INK, DUST, LINE = "#e8ecff", "#9aa3c7", "#4a5270"            # Starlight, Dust, D (lines only)
CYAN, AMBER, RED, GREEN = "#7df9ff", "#ffce6a", "#ff6b6b", "#4ade80"   # Warp Cyan, Booster Amber, the error red, ok

CSS = f"""*{{box-sizing:border-box}}html{{background:{BG}}}
body{{margin:0;padding:12px;background:{BG};color:{INK};font:16px/1.5 ui-monospace,"Cascadia Mono","DejaVu Sans Mono",Menlo,Consolas,monospace}}
.term{{max-width:62rem;margin:0 auto;border:1px solid {RULE};background:{PANEL}}}
header{{display:flex;flex-wrap:wrap;justify-content:space-between;gap:0 2ch;padding:.2em 1ch;background:{CYAN};color:{BG}}}
header h1{{font-size:inherit;margin:0;letter-spacing:.08em}}
nav{{display:flex;flex-wrap:wrap;padding:.3em .5ch;border-bottom:1px solid {RULE}}}
nav a{{color:{DUST};text-decoration:none;padding:.45em 1ch}}nav a:hover{{color:{INK}}}
nav a[aria-current]{{background:{DUST};color:{BG}}}
main{{padding:1ch}}
fieldset{{border:1px solid {LINE};margin:0 0 1.2em;padding:.4em 1ch .8em;min-width:0}}
legend{{color:{CYAN};padding:0 .5ch;letter-spacing:.06em;text-transform:uppercase}}
legend::before{{content:"\\2524\\a0" / ""}}legend::after{{content:"\\a0\\251c" / ""}}
p{{margin:.5em 0}}small,.dim,th{{color:{DUST}}}a{{color:{CYAN}}}
.note{{color:{AMBER}}}.note:empty{{display:none}}.note::before{{content:"! " / ""}}.ok{{color:{GREEN}}}.bad{{color:{RED}}}
button{{font:inherit;color:{CYAN};background:none;border:0;padding:.45em .6ch;min-height:2.75em;cursor:pointer}}
button::before{{content:"[" / ""}}button::after{{content:"]" / ""}}
button:hover{{background:{CYAN};color:{BG}}}button.danger{{color:{RED}}}button.danger:hover{{background:{RED};color:{BG}}}
:focus-visible{{outline:2px solid {AMBER};outline-offset:2px}}
form.go button,button.go{{color:{BG};background:{CYAN};padding:.45em 2ch;margin-top:.6em}}
input,select{{font:inherit;color:{INK};background:{BG};border:1px solid {DUST};padding:.45em 1ch;width:100%;min-height:2.75em}}
input:disabled{{color:{DUST};border-style:dashed}}
label{{display:block;margin:.6em 0 0;color:{DUST}}}label>input,label>select{{margin-top:.2em}}
.check{{display:flex;gap:1ch;align-items:baseline;color:{INK};margin:.4em 0}}.check input{{width:auto;min-height:0;flex:none;accent-color:{CYAN}}}
table{{border-collapse:collapse;width:100%}}th{{text-align:left;font-weight:normal;padding:.3em 2ch .3em 0;vertical-align:top;white-space:nowrap}}
td{{padding:.3em 0;overflow-wrap:anywhere}}
ol,ul{{list-style:none;margin:0;padding:0}}li{{padding:.55em 0;border-bottom:1px dotted {LINE}}}li:last-child{{border:0}}
.item{{display:grid;grid-template-columns:3ch minmax(8ch,auto) 1fr;gap:0 1ch;align-items:baseline}}
.item .n{{color:{DUST}}}.item .name{{font-weight:700}}.item .tag{{justify-self:end;color:{GREEN}}}
.item.off .name{{color:{DUST}}}.item.off .tag{{color:{AMBER}}}
.item small,.item .actions{{grid-column:2/-1}}.item.bare{{grid-template-columns:1fr auto}}
.item.bare small,.item.bare .actions{{grid-column:1/-1}}
.actions{{display:flex;flex-wrap:wrap;align-items:center;gap:0 .5ch;margin-top:.15em}}
form.inline{{display:inline-flex;align-items:center;gap:.5ch;margin:0}}form.inline label{{margin:0}}
form.inline input{{width:7ch;min-height:2.4em;padding:.2em .6ch}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;color:{DUST};margin:.5em 0}}
footer{{max-width:62rem;margin:.5em auto 0;font-size:.85em;padding:0 1ch}}footer a{{color:{DUST}}}
@media (max-width:40rem){{body{{padding:0}}.term{{border:0}}.item{{grid-template-columns:3ch 1fr auto}}.item.bare{{grid-template-columns:1fr auto}}}}"""


def panel(title, inner):
    """one framed panel, its title in the frame"""
    return f"<fieldset><legend>{html.escape(title)}</legend>{inner}</fieldset>"


def check():
    import re, os, sys
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    import kit
    hexed = lambda rgb: "#%02x%02x%02x" % rgb
    for ours, theirs in ((BG, kit.BG), (PANEL, kit.RAISED), (RULE, kit.RULE), (INK, kit.W), (DUST, kit.G),
                         (LINE, kit.D), (CYAN, kit.O), (AMBER, kit.A), (RED, kit.ERROR), (GREEN, kit.GREEN)):
        assert ours == hexed(theirs), f"{ours} isn't kit.py's {hexed(theirs)}"

    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in c]
        return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
    ratio = lambda a, b: (max(lum(a), lum(b)) + .05) / (min(lum(a), lum(b)) + .05)
    for colour in (INK, DUST, CYAN, AMBER, RED, GREEN):   # every colour text comes in, on both backgrounds: WCAG AA
        assert min(ratio(colour, BG), ratio(colour, PANEL)) >= 4.5, f"{colour} is too faint for text"
    assert ratio(BG, CYAN) >= 4.5 and ratio(BG, DUST) >= 4.5, "dark text on the cyan bar and the current tab"
    used = set(re.findall(r"color:(#[0-9a-f]{6})", CSS))
    assert LINE not in used and RULE not in used, "the line colours never colour text"
    assert len(CSS.encode()) < 4096 and "url(" not in CSS and "@import" not in CSS and "@font-face" not in CSS, \
        "small, and nothing fetched: the CSP allows no other source"
    assert panel("<b>", "x") == "<fieldset><legend>&lt;b&gt;</legend>x</fieldset>"
    print("look: ok")
