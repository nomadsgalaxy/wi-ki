"""{name}: say what the transition looks like here, in a sentence or two.

Made from catalog/new/transition.py with canvas.simple() (docs/make.md has the whole story). You write shown(t), the
parts of the new page showing at t, and simple() plays it. Never flash the whole screen (AGENTS.md).
"""
from .canvas import WIDTH, HEIGHT, simple

SECONDS = 3     # how long it plays (3 if you leave it out)
BLINDS = 12     # strips, opening top to bottom like a blind's slats


def shown(t):
    """t goes from 0 (none of the new page) to 1 (all of it) -> [(x, y, w, h)], the parts of the new page showing"""
    h = -(-HEIGHT // BLINDS)
    return [(0, y, WIDTH, round(t * h)) for y in range(0, HEIGHT, h)]   # whole rows: one copy each


frames = simple(shown)
