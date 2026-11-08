"""fix_gnd.py PCB DRC.json -- give every unconnected GND pad a via (to the In1 plane) + short stub; widen sub-minimum tracks.
Run with KiCad's python, then re-run post_route.py --no-import to refill, then DRC again."""
import json, math, sys, pcbnew
from pcbnew import VECTOR2I, FromMM as mm, ToMM as tomm
PCB, DRC = sys.argv[1], sys.argv[2]
b = pcbnew.LoadBoard(PCB); gnd = b.FindNet("GND")
d = json.load(open(DRC))
need = set()
import re
for v in d["unconnected_items"]:
    for i in v["items"]:
        m = re.match(r"(?:PTH )?[Pp]ad (\S+) \[GND\] of (\S+)", i["description"])
        if m: need.add((m.group(2), m.group(1)))
print("GND pads to fix:", len(need))
CLR = 0.2
def seg_d(px, py, ax, ay, cx, cy):
    dx, dy = cx - ax, cy - ay; L = dx * dx + dy * dy
    u = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(ax + u * dx - px, ay + u * dy - py)
tracks = [(t, ) for t in b.GetTracks()]
def clear_pt(x, y, r, net):
    pt = VECTOR2I(mm(x), mm(y)); m = mm(r + CLR)
    for p in b.GetPads():
        if p.GetNetname() == "GND": continue
        bb = p.GetBoundingBox()
        if bb.GetX() - m <= pt.x <= bb.GetRight() + m and bb.GetY() - m <= pt.y <= bb.GetBottom() + m: return False
    for t in b.GetTracks():
        if t.GetNetname() == "GND": continue
        if t.Type() == pcbnew.PCB_VIA_T:
            q = t.GetPosition()
            if math.hypot(tomm(q.x) - x, tomm(q.y) - y) < r + tomm(t.GetWidth(pcbnew.F_Cu)) / 2 + CLR: return False
        else:
            a, c = t.GetStart(), t.GetEnd()
            if seg_d(x, y, tomm(a.x), tomm(a.y), tomm(c.x), tomm(c.y)) < r + tomm(t.GetWidth()) / 2 + CLR: return False
    return True
fixed = 0
for ref, num in sorted(need):
    fp = b.FindFootprintByReference(ref)
    pad = next((p for p in fp.Pads() if p.GetNumber() == num and p.GetNetname() == "GND"), None)
    if pad is None: continue
    px, py = tomm(pad.GetPosition().x), tomm(pad.GetPosition().y); ok = False
    for rad in (0.9, 1.2, 1.6, 2.0, 2.6):
        for k in range(24):
            a = 2 * math.pi * k / 24; x, y = px + rad * math.cos(a), py + rad * math.sin(a)
            if not clear_pt(x, y, 0.3, gnd): continue
            if not all(clear_pt(px + (x - px) * s / 8, py + (y - py) * s / 8, 0.1, gnd) for s in range(2, 8)): continue
            v = pcbnew.PCB_VIA(b); v.SetPosition(VECTOR2I(mm(x), mm(y))); v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetWidth(pcbnew.F_Cu, mm(0.6)); v.SetDrill(mm(0.3)); v.SetNet(gnd); b.Add(v)
            t = pcbnew.PCB_TRACK(b); t.SetStart(pad.GetPosition()); t.SetEnd(VECTOR2I(mm(x), mm(y)))
            t.SetLayer(pcbnew.F_Cu); t.SetWidth(mm(0.2)); t.SetNet(gnd); b.Add(t)
            ok = True; fixed += 1; break
        if ok: break
    if not ok: print("  no room:", ref, num)
for t in b.GetTracks():
    if t.Type() != pcbnew.PCB_VIA_T and t.GetWidth() < mm(0.15): t.SetWidth(mm(0.15))
print("GND vias added:", fixed)
pcbnew.SaveBoard(PCB, b)
