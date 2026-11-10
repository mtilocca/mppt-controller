"""
post_route.py -- after Freerouting (run with KiCad's Python):
  flatpak run --command=python3 org.kicad.KiCad post_route.py mppt_controller.kicad_pcb _route.ses [--no-import]

1. imports the Specctra session (signal + rail tracks and fanout vias)
2. GND pours on F.Cu and B.Cu (not in the isolation bus-side zones) + stitching vias to the inner GND planes
3. high-current nets: 1.0 mm Power-class tracks are widened with same-net copper areas (buffer of the tracks and pads), and a
   copper area on both outer layers; fills never violate clearance because the zone fill respects other nets
4. refills all zones
Re-runnable: it replaces its own zones and vias (marked locked / named "HC_*", "GND_*").
"""
import math
import sys

import pcbnew
from pcbnew import VECTOR2I, FromMM as mm, ToMM as tomm

PCB = sys.argv[1]
SES = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
NO_IMPORT = "--no-import" in sys.argv
HC = ["PV_RAW", "PV_F", "PV_D", "VIN_PWR", "VIN_CS", "SW1", "SW2", "VOUT", "BAT_RAW", "BAT_F", "BAT_NEG", "BAT_BUS",
      "LOAD_SENSE", "LOAD_OUT", "INV_SENSE", "INV_OUT"]
VD, VDR, CLR = 0.6, 0.3, 0.25
PITCH = 5.0

b = pcbnew.LoadBoard(PCB)
if SES and not NO_IMPORT:
    print("import SES:", pcbnew.ImportSpecctraSES(b, SES))

bb = b.GetBoardEdgesBoundingBox()           # before removing zones (SWIG wrapper quirk)
BW, BH = tomm(bb.GetRight()), tomm(bb.GetBottom())
# ------------------------------------------------------------ remove what an earlier run added
_old_gnd_vias = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.IsLocked() and t.GetNetname() == "GND"]
for z in list(b.Zones()):
    nm = z.GetZoneName()
    if nm.startswith("HC_") or nm.startswith("GND_") or (not z.GetIsRuleArea() and z.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu)):
        b.Remove(z)
for t in _old_gnd_vias:
    b.Remove(t)
pcbnew.SaveBoard(PCB, b)                    # reload: SWIG proxies are stale after Remove()
b = pcbnew.LoadBoard(PCB)

gnd = b.FindNet("GND")

# isolation bus-side areas become keep-outs on the outer layers too (no pours, vias or GND copper); tracks stay allowed
for z in b.Zones():
    if z.GetIsRuleArea() and z.GetZoneName().startswith("ISO_"):
        ls = z.GetLayerSet()
        ls.AddLayer(pcbnew.F_Cu)
        ls.AddLayer(pcbnew.B_Cu)
        z.SetLayerSet(ls)
keepouts = []
for z in b.Zones():
    if z.GetIsRuleArea():
        r = z.GetBoundingBox()
        keepouts.append((tomm(r.GetX()), tomm(r.GetY()), tomm(r.GetRight()), tomm(r.GetBottom())))


def new_zone(layer, net, name, prio, clr=0.25):
    z = pcbnew.ZONE(b)
    z.SetLayer(layer)
    z.SetNet(net)
    z.SetZoneName(name)
    z.SetAssignedPriority(prio)
    z.SetLocalClearance(mm(clr))
    z.SetMinThickness(mm(0.25))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    return z


# ------------------------------------------------------------ high-current copper areas (priority above GND)
def net_geometry(netname):
    """Buffered polygon set (per layer) of the tracks and pads of a net."""
    out = {}
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        ps = pcbnew.SHAPE_POLY_SET()
        n = 0
        for t in b.GetTracks():
            if t.GetNetname().split("/")[-1] != netname or t.Type() == pcbnew.PCB_VIA_T or t.GetLayer() != layer:
                continue
            t.TransformShapeToPolygon(ps, layer, mm(2.2), mm(0.05), pcbnew.ERROR_OUTSIDE)
            n += 1
        for fp in b.GetFootprints():
            for pad in fp.Pads():
                if pad.GetNetname().split("/")[-1] == netname and pad.IsOnLayer(layer):
                    pad.TransformShapeToPolygon(ps, layer, mm(1.2), mm(0.05), pcbnew.ERROR_OUTSIDE)
                    n += 1
        if n:
            ps.Simplify()
            out[layer] = ps
    return out


prio = 10
for name in HC:
    for layer, ps in net_geometry(name).items():
        net = next((n for n in b.GetNetsByName().values() if n.GetNetname().split("/")[-1] == name), None)
        if net is None:
            continue
        for i in range(ps.OutlineCount()):
            z = new_zone(layer, net, f"HC_{name}", prio, 0.25)
            ol = z.Outline()
            ol.AddOutline(ps.COutline(i))
            for h in range(ps.HoleCount(i)):
                ol.AddHole(ps.CHole(i, h))
            b.Add(z)
    prio += 1

# ------------------------------------------------------------ GND pours
for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
    z = new_zone(layer, gnd, "GND_" + ("F" if layer == pcbnew.F_Cu else "B"), 1, 0.25)
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)
    z.SetThermalReliefGap(mm(0.3))
    z.SetThermalReliefSpokeWidth(mm(0.4))
    o = z.Outline()
    o.NewOutline()
    for (x, y) in ((0.4, 0.4), (BW - 0.4, 0.4), (BW - 0.4, BH - 0.4), (0.4, BH - 0.4)):
        o.Append(mm(x), mm(y))
    b.Add(z)
pcbnew.ZONE_FILLER(b).Fill(b.Zones())


# ------------------------------------------------------------ stitching vias
def free(x, y, r):
    if not (1.0 <= x <= BW - 1.0 and 1.0 <= y <= BH - 1.0):
        return False
    for (a, c, d, e) in keepouts:
        if a - 0.6 <= x <= d + 0.6 and c - 0.6 <= y <= e + 0.6:
            return False
    m = mm(r + CLR)
    for p in b.GetPads():
        pb = p.GetBoundingBox()
        if pb.GetX() - m <= mm(x) <= pb.GetRight() + m and pb.GetY() - m <= mm(y) <= pb.GetBottom() + m:
            return False
    for t in b.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            q = t.GetPosition()
            if math.hypot(tomm(q.x) - x, tomm(q.y) - y) < r + tomm(t.GetWidth(pcbnew.F_Cu)) / 2 + CLR + 0.1:
                return False
            continue
        a, c = t.GetStart(), t.GetEnd()
        ax, ay, cx, cy = tomm(a.x), tomm(a.y), tomm(c.x), tomm(c.y)
        dx, dy = cx - ax, cy - ay
        L2 = dx * dx + dy * dy
        u = 0 if L2 == 0 else max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / L2))
        if math.hypot(ax + u * dx - x, ay + u * dy - y) < r + tomm(t.GetWidth()) / 2 + CLR:
            return False
    # high-current copper areas (other nets) on either layer
    pt = VECTOR2I(mm(x), mm(y))
    for z in b.Zones():
        if z.GetZoneName().startswith("HC_") and z.HitTestFilledArea(z.GetLayer(), pt, mm(r + CLR)):
            return False
    return True


def add_via(x, y):
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(VECTOR2I(mm(x), mm(y)))
    v.SetViaType(pcbnew.VIATYPE_THROUGH)
    v.SetWidth(pcbnew.F_Cu, mm(VD))
    v.SetDrill(mm(VDR))
    v.SetNet(gnd)
    v.SetLocked(True)
    b.Add(v)


placed = 0
cands = []
j = 1
while j * PITCH < BH:
    i = 1
    while i * PITCH < BW:
        cands.append((i * PITCH + 2.5 * (j % 2), j * PITCH))
        i += 1
    j += 1
t_ = 3.0
while t_ < max(BW, BH) - 3:
    cands += [(t_, 1.4), (t_, BH - 1.4), (1.4, t_), (BW - 1.4, t_)]
    t_ += 3.0
for (x, y) in cands:
    if free(x, y, VD / 2):
        add_via(x, y)
        placed += 1
print("stitching vias placed:", placed, "of", len(cands), "candidates")
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(PCB, b)
print("saved; zones:", len(list(b.Zones())))
