from PIL import Image, ImageDraw

TOP = (255, 143, 171)
BOTTOM = (142, 124, 255)
WHITE = (255, 255, 255)
PINK = (255, 111, 165)
LINE = (217, 207, 255, 255)

def make(size, maskable, path):
    ss = 4
    S = size * ss
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    px = img.load()
    for y in range(S):
        for x in range(S):
            t = (x + y) / (2 * (S - 1))
            r = int(TOP[0] + (BOTTOM[0] - TOP[0]) * t)
            g = int(TOP[1] + (BOTTOM[1] - TOP[1]) * t)
            b = int(TOP[2] + (BOTTOM[2] - TOP[2]) * t)
            px[x, y] = (r, g, b, 255)
    d = ImageDraw.Draw(img)
    scale = 0.58 if maskable else 0.66
    cx = 0.5 * S
    bw = 0.42 * scale * S
    by_top = (0.5 - 0.22 * scale) * S
    by_bot = (0.5 + 0.22 * scale) * S
    page_h = by_bot - by_top
    left = (cx - bw * 0.5, by_top, cx - bw * 0.02, by_bot)
    right = (cx + bw * 0.02, by_top, cx + bw * 0.5, by_bot)
    spine = (cx - 0.03 * S, by_top - 0.02 * S, cx + 0.03 * S, by_bot + 0.02 * S)
    rad = int(0.05 * bw)
    d.rounded_rectangle(left, radius=rad, fill=WHITE)
    d.rounded_rectangle(right, radius=rad, fill=WHITE)
    d.rounded_rectangle(spine, radius=rad, fill=WHITE)
    lw = max(1, int(0.02 * S))
    for off in (0.10, 0.18, 0.26):
        y1 = by_top + off * page_h
        for x0, x1 in ((left[0], left[2]), (right[0], right[2])):
            pad = 0.09 * (x1 - x0)
            d.rounded_rectangle((x0 + pad, y1, x1 - pad, y1 + lw), radius=lw // 2, fill=LINE)
    hx = (right[0] + right[2]) / 2
    hy = by_top + 0.62 * page_h
    hr = 0.05 * S
    d.ellipse((hx - hr, hy - hr * 0.8, hx, hy + hr * 0.2), fill=PINK + (255,))
    d.ellipse((hx, hy - hr * 0.8, hx + hr, hy + hr * 0.2), fill=PINK + (255,))
    d.polygon([(hx - hr, hy - 0.15 * hr), (hx + hr, hy - 0.15 * hr), (hx, hy + 0.9 * hr)], fill=PINK + (255,))
    if not maskable:
        mask = Image.new('L', (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(0.22 * S), fill=255)
        img.putalpha(mask)
    img.resize((size, size), Image.LANCZOS).save(path)
    print('wrote', path)

make(192, False, 'icon-192.png')
make(512, False, 'icon-512.png')
make(512, True, 'icon-512-maskable.png')