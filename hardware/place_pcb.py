"""
place_pcb.py -- placement for the MPPT controller (run with KiCad's Python):
  flatpak run --command=python3 org.kicad.KiCad place_pcb.py mppt_controller.kicad_pcb

1. Anchors: hand-placed power chain, edge connectors (oriented so the cable entry faces the board edge).
2. Everything else: greedy, highest connection weight to already placed parts first. A part goes to the free spot nearest to
   the pad(s) it connects to (small nets) or to the nearest free IC pad of its net (rails, decoupling), inside its block region.
Top side only (single-sided SMT assembly). Idempotent: re-run make_pcb.py first to start again from the import.
"""
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np
import pcbnew
from pcbnew import VECTOR2I, FromMM as mm, ToMM as tomm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from net2sch import child, parse  # noqa: E402

PATH = sys.argv[1]
NETFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mppt_controller_kicad.net")
W, H = float(os.environ.get("BOARD_W", 175)), float(os.environ.get("BOARD_H", 120))
RES = 0.25
GRID = (int(W / RES) + 1, int(H / RES) + 1)
CLR = 0.35                     # extra clearance around courtyards (mm)
EDGE = 1.2                     # keep-out from the board edge for non-edge parts

b = pcbnew.LoadBoard(PATH)
fps = {f.GetReference(): f for f in b.GetFootprints() if not f.GetReference().startswith("H")}

# ---------------------------------------------------------------- sheets
tree = parse(open(NETFILE, encoding="utf-8").read())
SHEET = {}
for c in child(tree, "components")[1:]:
    sp = child(c, "sheetpath")
    names = str(child(sp, "names")[1]).strip("/") if sp else ""
    SHEET[str(child(c, "ref")[1])] = re.sub(r"_?\d+$", "", names) or "top"

# block regions (x1, y1, x2, y2)
REGION = {
    "pv_input": (1.5, 1.5, 45, 55), "battery": (1.5, 55, 45, 118.5),
    "mppt_stage": (45, 1.5, 105, 66), "mppt_loop": (45, 1.5, 105, 66),
    "load_switch": (45, 66, 75, 118.5), "inverter_feed": (75, 66, 105, 118.5),
    "aux_power": (105, 1.5, 140, 28), "mcu": (105, 28, 150, 70), "flash": (105, 28, 150, 70),
    "ethernet": (130, 58, 173.5, 100), "can": (105, 100, 138, 118.5), "rs485": (138, 100, 173.5, 118.5),
    "usb_uart": (140, 12, 173.5, 58), "display": (105, 1.5, 173.5, 28), "leds": (105, 28, 150, 70),
    "sensing": (1.5, 1.5, 173.5, 118.5), "top": (1.5, 1.5, 173.5, 118.5),
}

# ---------------------------------------------------------------- geometry helpers
def court(fp):
    """Courtyard (or bounding box) rectangle in mm: (x1, y1, x2, y2)."""
    try:
        ps = fp.GetCourtyard(pcbnew.F_CrtYd)
        if ps.OutlineCount() > 0:
            bb = ps.BBox()
            return tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom())
    except Exception:
        pass
    bb = fp.GetBoundingBox(False)
    return tomm(bb.GetLeft()), tomm(bb.GetTop()), tomm(bb.GetRight()), tomm(bb.GetBottom())


def center(fp):
    x1, y1, x2, y2 = court(fp)
    return (x1 + x2) / 2, (y1 + y2) / 2


def move_center(fp, cx, cy):
    c = center(fp)
    p = fp.GetPosition()
    fp.SetPosition(VECTOR2I(p.x + mm(cx - c[0]), p.y + mm(cy - c[1])))


def pad_centroid(fp):
    ps = [p.GetPosition() for p in fp.Pads()]
    return tomm(sum(p.x for p in ps) / len(ps)), tomm(sum(p.y for p in ps) / len(ps))


occ = np.zeros(GRID, bool)


def cells(x1, y1, x2, y2, m=CLR):
    return (max(0, int((x1 - m) / RES)), max(0, int((y1 - m) / RES)),
            min(GRID[0], int((x2 + m) / RES) + 1), min(GRID[1], int((y2 + m) / RES) + 1))


def mark(fp):
    i1, j1, i2, j2 = cells(*court(fp))
    occ[i1:i2, j1:j2] = True


def free(fp, region=None, edge=EDGE):
    x1, y1, x2, y2 = court(fp)
    if x1 < edge or y1 < edge or x2 > W - edge or y2 > H - edge:
        return False
    if region and (x1 < region[0] or y1 < region[1] or x2 > region[2] or y2 > region[3]):
        return False
    i1, j1, i2, j2 = cells(x1, y1, x2, y2)
    return not occ[i1:i2, j1:j2].any()


def entry_vector(fp):
    """Direction from the pad centroid towards the body centre (cable entry / connector mouth)."""
    px, py = pad_centroid(fp)
    cx, cy = center(fp)
    return cx - px, cy - py


def orient_to(fp, normal):
    best = None
    for rot in (0, 90, 180, 270):
        fp.SetOrientationDegrees(rot)
        ex, ey = entry_vector(fp)
        score = ex * normal[0] + ey * normal[1]
        if best is None or score > best[0]:
            best = (score, rot)
    fp.SetOrientationDegrees(best[1])


def place_edge(ref, edge, along, inset=0.0):
    fp = fps[ref]
    normal = {"left": (-1, 0), "right": (1, 0), "top": (0, -1), "bottom": (0, 1)}[edge]
    orient_to(fp, normal)
    x1, y1, x2, y2 = court(fp)
    w, h = x2 - x1, y2 - y1
    if edge == "left":
        move_center(fp, w / 2 + inset, along)
    elif edge == "right":
        move_center(fp, W - w / 2 - inset, along)
    elif edge == "top":
        move_center(fp, along, h / 2 + inset)
    else:
        move_center(fp, along, H - h / 2 - inset)
    mark(fp)


def place_at(ref, cx, cy, rot=0):
    fp = fps[ref]
    fp.SetOrientationDegrees(rot)
    move_center(fp, cx, cy)
    mark(fp)


# ---------------------------------------------------------------- 1. anchors
EDGE_PARTS = {
    "J1": ("left", 24), "J2": ("left", 88),
    "J3": ("bottom", 58), "J4": ("bottom", 84), "J5": ("bottom", 100),
    "J8": ("right", 80), "J11": ("right", 30),
    "J9": ("bottom", 122), "J10": ("bottom", 152),
    "J13": ("top", 152),
}
for ref, (edge, along) in EDGE_PARTS.items():
    if ref in fps:
        place_edge(ref, edge, along)

ANCHORS = {   # ref: (cx, cy, rot)
    # power chain
    "F1": (22, 8, 0), "D1": (22, 36, 0), "F2": (24, 68, 0), "D3": (20, 106, 0),
    "C4": (52, 10, 0), "C5": (52, 24, 0), "R2": (65, 5, 0),
    "Q2": (65, 14, 0), "Q3": (65, 23, 0), "L1": (82, 19, 0), "Q4": (101, 14, 0), "Q5": (101, 23, 0),
    "U2": (62, 40, 0), "C16": (78, 46, 0), "C17": (92, 46, 0), "R7": (86, 58, 0),
    "C37": (24, 92, 0), "C38": (39, 92, 0),
    # digital
    "U17": (128, 48, 0), "U14": (112, 12, 0), "L2": (126, 12, 0),
}
for ref, (cx, cy, rot) in ANCHORS.items():
    if ref in fps and ref not in EDGE_PARTS:
        place_at(ref, cx, cy, rot)

# ---------------------------------------------------------------- 2. greedy placement of the rest
pads_of = defaultdict(list)       # net -> [(ref, pad)]
for p in b.GetPads():
    n = p.GetNetname()
    if n:
        pads_of[n].append((p.GetParentFootprint().GetReference(), p))
def pkey(ref, p):
    return (ref, p.GetNumber())


pad_xy = {pkey(r, p): (tomm(p.GetPosition().x), tomm(p.GetPosition().y)) for lst in pads_of.values() for r, p in lst}
SKIP = {"GND", ""}
placed = {r for r in EDGE_PARTS if r in fps} | {r for r in ANCHORS if r in fps}
NETS = {r: {p.GetNetname() for p in fps[r].Pads() if p.GetNetname() and p.GetNetname() not in SKIP} for r in fps}


def is_passive(ref):
    return re.match(r"(R|C|D|L|TP|JP|FB)\d", ref) is not None and not re.match(r"(D1|D3|D9)$", ref)


PASSIVE = {r: is_passive(r) for r in fps}
CEN = {}                                   # placed part -> centre (mm)


def refresh_pad_xy(ref):
    for p in fps[ref].Pads():
        pad_xy[pkey(ref, p)] = (tomm(p.GetPosition().x), tomm(p.GetPosition().y))
    CEN[ref] = center(fps[ref])


for r in placed:
    refresh_pad_xy(r)


def edge_weight(ref, other):
    w = 0.0
    for n in NETS[ref] & NETS[other]:
        k = len(pads_of[n])
        w += 1.0 / (k - 1) if k <= 8 else (0.1 if not PASSIVE[other] else 0.0)
    return w


NB = {r: [o for o in fps if o != r and NETS[r] & NETS[o]] for r in fps}
score = defaultdict(float)
for r in placed:
    for o in NB[r]:
        if o not in placed:
            score[o] += edge_weight(o, r)


def target_for(ref):
    pts, wts = [], []
    for p in fps[ref].Pads():
        n = p.GetNetname()
        if not n or n in SKIP:
            continue
        lst = pads_of[n]
        if len(lst) <= 8:
            for r, q in lst:
                if r != ref and r in placed:
                    pts.append(pad_xy[pkey(r, q)])
                    wts.append(1.0 / (len(lst) - 1))
        else:
            cand = [(r, q) for r, q in lst if r != ref and r in placed and not PASSIVE[r]] or \
                   [(r, q) for r, q in lst if r != ref and r in placed]
            if cand:
                me = CEN.get(ref) or (0, 0)

                def load(rq):
                    qx, qy = pad_xy[pkey(*rq)]
                    return sum(1 for r2 in placed if PASSIVE[r2] and abs(CEN[r2][0] - qx) + abs(CEN[r2][1] - qy) < 7)
                best = min(cand, key=load)
                pts.append(pad_xy[pkey(*best)])
                wts.append(0.5)
    if not pts:
        return None
    sw = sum(wts)
    return sum(x * w for (x, _), w in zip(pts, wts)) / sw, sum(y * w for (_, y), w in zip(pts, wts)) / sw


OFFS = {}


def offsets(rmax):
    if rmax not in OFFS:
        step = 0.5
        k = int(rmax / step)
        xs = np.arange(-k, k + 1) * step
        dx, dy = np.meshgrid(xs, xs)
        d = np.hypot(dx, dy)
        m = d <= rmax
        order = np.argsort(d[m])
        OFFS[rmax] = (dx[m][order], dy[m][order], d[m][order])
    return OFFS[rmax]


def table():
    t = np.zeros((GRID[0] + 1, GRID[1] + 1), np.int32)
    t[1:, 1:] = occ.cumsum(0).cumsum(1)
    return t


def find_spot(fp, tgt, region, rmax):
    """Free centre position nearest to tgt for the footprint in its current orientation, or None."""
    x1, y1, x2, y2 = court(fp)
    cx0, cy0 = (x1 + x2) / 2, (y1 + y2) / 2
    hw, hh = (x2 - x1) / 2, (y2 - y1) / 2
    dx, dy, d = offsets(rmax)
    cx, cy = tgt[0] + dx, tgt[1] + dy
    ok = (cx - hw >= EDGE) & (cy - hh >= EDGE) & (cx + hw <= W - EDGE) & (cy + hh <= H - EDGE)
    if region:
        ok &= (cx - hw >= region[0]) & (cy - hh >= region[1]) & (cx + hw <= region[2]) & (cy + hh <= region[3])
    if not ok.any():
        return None
    cx, cy, d = cx[ok], cy[ok], d[ok]
    i1 = np.maximum(0, ((cx - hw - CLR) / RES).astype(int))
    j1 = np.maximum(0, ((cy - hh - CLR) / RES).astype(int))
    i2 = np.minimum(GRID[0], ((cx + hw + CLR) / RES).astype(int) + 1)
    j2 = np.minimum(GRID[1], ((cy + hh + CLR) / RES).astype(int) + 1)
    t = TABLE[0]
    s = t[i2, j2] - t[i1, j2] - t[i2, j1] + t[i1, j1]
    k = np.nonzero(s == 0)[0]
    if len(k) == 0:
        return None
    k = k[0]
    return float(cx[k]), float(cy[k]), float(d[k])


TABLE = [table()]


def try_place(ref, tgt, hard=None):
    fp = fps[ref]
    reg = hard or REGION.get(SHEET.get(ref, "top"))
    rots = (0, 90, 180, 270) if PASSIVE[ref] or re.match(r"(U|Q|SW)\d", ref) else (0, 90)
    for scope, rmax in (((reg, 60),) if hard else ((reg, 40), (None, 90))):
        best = None
        for rot in rots:
            fp.SetOrientationDegrees(rot)
            sp = find_spot(fp, tgt, scope, rmax)
            if sp and (best is None or sp[2] < best[0]):
                best = (sp[2], rot, sp[0], sp[1])
        if best:
            fp.SetOrientationDegrees(best[1])
            move_center(fp, best[2], best[3])
            mark(fp)
            TABLE[0] = table()
            return True
    return False


for ref in list(fps):
    if ref in placed:
        mark(fps[ref])
TABLE[0] = table()
print('occupied fraction after anchors', round(float(occ.mean()),3), flush=True)


# ---------------------------------------------------------------- isolation barriers (CAN, RS485)
ISO_GROUPS = {   # IC: (connector, bus nets, IC bus-side pins, IC x)
    "U20": ("J9", {"CAN_GND", "CAN_VISO", "CANH", "CANL", "CAN_TERM_MID"}, {str(i) for i in range(9, 17)}, 124),
    "U21": ("J10", {"ISO_GND", "ISO_3V3", "RS485_A", "RS485_B", "RS485_TERM_MID"}, {str(i) for i in range(9, 17)}, 154),
}
BARRIERS = []


def orient_bus_down(fp, bus_pins):
    best = None
    for rot in (0, 90, 180, 270):
        fp.SetOrientationDegrees(rot)
        bus = [p.GetPosition() for p in fp.Pads() if p.GetNumber() in bus_pins]
        log = [p.GetPosition() for p in fp.Pads() if p.GetNumber() not in bus_pins and p.GetNumber().isdigit()]
        d = tomm(sum(q.y for q in bus) / len(bus)) - tomm(sum(q.y for q in log) / len(log))
        if best is None or d > best[0]:
            best = (d, rot)
    fp.SetOrientationDegrees(best[1])


for ic, (conn, nets_, pins, ix) in ISO_GROUPS.items():
    if ic not in fps:
        continue
    fp = fps[ic]
    orient_bus_down(fp, pins)
    move_center(fp, ix, 97)
    mark(fp)
    placed.add(ic)
    refresh_pad_xy(ic)
    TABLE[0] = table()
    cx1, cy1, cx2, cy2 = court(fps[conn])
    ix1, iy1, ix2, iy2 = court(fp)
    zone = (min(cx1, ix1) - 3, (iy1 + iy2) / 2 + 1.0, max(cx2, ix2) + 3, H - 1.2)
    members = [r for r in fps if r not in (ic, conn) and r not in placed and
               any(pd.GetNetname().split("/")[-1] in nets_ for pd in fps[r].Pads())]
    for r in sorted(members, key=lambda r: (PASSIVE[r], r)):
        t = target_for(r) or ((zone[0] + zone[2]) / 2, (zone[1] + zone[3]) / 2)
        if try_place(r, t, hard=zone):
            placed.add(r)
            refresh_pad_xy(r)
        else:
            print("ISO FAIL", r, ic)
    BARRIERS.append(zone)
    print(f"barrier {ic}: zone x {zone[0]:.1f}..{zone[2]:.1f} y {zone[1]:.1f}..{zone[3]:.1f}, {len(members)} bus-side parts")
for z_ in BARRIERS:       # nobody else may enter the bus-side zones
    i1, j1, i2, j2 = cells(*z_, m=0)
    occ[i1:i2, j1:j2] = True
TABLE[0] = table()
for r in placed:
    for o in NB[r]:
        pass
score.clear()
for r in placed:
    for o in NB[r]:
        if o not in placed:
            score[o] += edge_weight(o, r)

remaining = [r for r in fps if r not in placed]
failed = []
while remaining:
    ref = max(remaining, key=lambda r: (score[r] > 0, 0 if PASSIVE[r] else 1, score[r]))
    tgt = target_for(ref)
    if tgt is None:
        reg = REGION.get(SHEET.get(ref, "top"))
        tgt = ((reg[0] + reg[2]) / 2, (reg[1] + reg[3]) / 2)
    remaining.remove(ref)
    if os.environ.get('DBG') and len(failed)<3 and not try_place.__defaults__ and False: pass
    if try_place(ref, tgt):
        placed.add(ref)
        refresh_pad_xy(ref)
        for o in NB[ref]:
            if o not in placed:
                score[o] += edge_weight(o, ref)
    else:
        failed.append(ref)
        if len(failed) <= 3:
            print('FAIL', ref, SHEET.get(ref), 'tgt', tgt, 'court', [round(v,1) for v in court(fps[ref])], 'occ', round(float(occ.mean()),3), flush=True)

# mounting holes
for k, (x, y) in enumerate([(4, 4), (W - 4, 4), (4, H - 4), (W - 4, H - 4)], 1):
    ref = f"H{k}"
    h = next((f for f in b.GetFootprints() if f.GetReference() == ref), None)
    if h is None:
        h = pcbnew.FootprintLoad("/app/extensions/Library/footprints/MountingHole.pretty", "MountingHole_3.2mm_M3_Pad_Via")
        h.SetReference(ref)
        b.Add(h)
    h.SetPosition(VECTOR2I(mm(x), mm(y)))

pcbnew.SaveBoard(PATH, b)
print(f"placed {len(placed)} of {len(fps)}; failed: {failed}")
