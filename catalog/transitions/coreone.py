"""CoreOne: the new page gets printed. A pixel hotend zig-zags up from the bottom of the screen, laying the page down one
40 px layer at a time in as many steps across as the frames allow, and the line it just put down glows orange
while it's hot.

Contract note: a layer takes whole steps, so it plays count // layers steps a layer, and at least one: 65 frames for the
72 asked (within play()'s tolerance), 26 for 36, and 13 for 1 or 2, one step a layer. play() only ever
asks for 72, so the small counts exist for check().

Colours: a printer's orange, #fd5000, and its grey, #808285.
"""
from PIL import Image, ImageDraw

from .canvas import WIDTH, HEIGHT, sprite

ORANGE, GREY, DARK, WHITE = (253, 80, 0), (128, 130, 133), (70, 72, 75), (235, 235, 235)
LAYER = max(40, HEIGHT // 13 // 4 * 4)   # about 13 layers on any screen: 40 px on the bar


def hotend():
    """the hotend, 11x15 pixel art drawn 4x: filament, heatsink fins, the heater block, the nozzle"""
    img = Image.new("RGBA", (11, 15)); d = ImageDraw.Draw(img)
    d.line((5, 0, 5, 2), fill=WHITE)                                   # filament going in
    for y in range(3, 7):
        d.line((1, y, 9, y), fill=GREY if y % 2 else DARK)              # heatsink fins
    d.rectangle((0, 7, 10, 10), fill=ORANGE); d.line((0, 7, 10, 7), fill=(255, 130, 60))   # heater block
    d.line((3, 11, 7, 11), fill=GREY); d.line((4, 12, 6, 12), fill=GREY); d.point((5, 13), fill=WHITE)   # nozzle
    return sprite(img, 4)


NOZZLE = hotend()


def frames(c, count):
    layers = -(-HEIGHT // LAYER)
    segments = max(1, count // layers)   # steps to cross the screen
    nozzle, width = NOZZLE, -(-WIDTH // segments)
    for layer in range(layers):
        y = HEIGHT - (layer + 1) * LAYER
        forward = layer % 2 == 0   # left to right, then back
        for step in range(segments):
            x = (step if forward else segments - 1 - step) * width
            c.reveal(x, y, width, LAYER)
            c.fill(x, y, width, 4, ORANGE)   # the fresh line is still hot
            tip = x + width if forward else x
            c.draw(nozzle, tip - nozzle["w"] // 2, y - nozzle["h"] + 4)
            yield
