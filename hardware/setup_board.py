"""
setup_board.py -- net classes, design rules, inner ground planes, isolation keep-outs (run with KiCad's Python):
  flatpak run --command=python3 org.kicad.KiCad setup_board.py mppt_controller.kicad_pcb
Net classes live in mppt_controller.kicad_pro (edited here as JSON); planes/keep-outs are written into the board.
"""
import json
import os
import sys

import pcbnew
from pcbnew import VECTOR2I, FromMM as mm

PCB = sys.argv[1]
PRO = PCB.replace(".kicad_pcb", ".kicad_pro")
HC = ["PV_RAW", "PV_F", "PV_D", "VIN_PWR", "VIN_CS", "SW1", "SW2", "VOUT", "BAT_RAW", "BAT_F", "BAT_NEG", "BAT_BUS",
      "LOAD_SENSE", "LOAD_OUT", "INV_SENSE", "INV_OUT"]
RAIL = ["3V3", "3V3A", "5V", "VAUX", "VAUX_RAW", "LM5177_VCC", "VBUS", "VBUS_PROT", "ETH_CT", "PHY_VDDCR", "CAN_VISO", "ISO_3V3", "VCAP"]

# ------------------------------------------------------------ project: net classes and rules
p = json.load(open(PRO))
ns = p["net_settings"]
base = dict(ns["classes"][0], clearance=0.15)
ns["classes"] = [base,
                 dict(base, name="Rail", track_width=0.4, via_diameter=0.6, via_drill=0.3, priority=1, clearance=0.15),
                 dict(base, name="Power", track_width=1.0, via_diameter=0.8, via_drill=0.4, priority=0, clearance=0.15)]
ns["netclass_patterns"] = [{"netclass": "Power", "pattern": "*" + n} for n in HC] + \
                          [{"netclass": "Rail", "pattern": "*" + n} for n in RAIL]
ds = p["board"]["design_settings"]
ds["rules"].update({"min_track_width": 0.15, "min_via_diameter": 0.5, "min_through_hole_diameter": 0.3,
                    "min_copper_edge_clearance": 0.4, "min_hole_to_hole": 0.25, "min_clearance": 0.15})
json.dump(p, open(PRO, "w"), indent=2)

# ------------------------------------------------------------ board
b = pcbnew.LoadBoard(PCB)
for z in list(b.Zones()):
    b.Remove(z)
bb = b.GetBoardEdgesBoundingBox()
x1, y1, x2, y2 = (pcbnew.ToMM(v) for v in (bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
IN = 0.4


def rect_outline(z, a, b_, c, d):
    ol = z.Outline()
    ol.NewOutline()
    for x, y in ((a, b_), (c, b_), (c, d), (a, d)):
        ol.Append(mm(x), mm(y))


gnd = b.FindNet("GND")
for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
    z = pcbnew.ZONE(b)
    z.SetLayer(layer)
    z.SetNet(gnd)
    z.SetMinThickness(mm(0.2))
    z.SetThermalReliefGap(mm(0.3))
    z.SetThermalReliefSpokeWidth(mm(0.4))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetLocalClearance(mm(0.3))
    z.SetAssignedPriority(1)
    rect_outline(z, x1 + IN, y1 + IN, x2 - IN, y2 - IN)
    b.Add(z)


def keepout(name, nets, pad_refs, layers):
    """Copper keep-out (no pours) on the given layers around every pad on `nets` plus all pads of pad_refs."""
    xs, ys = [], []
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            n = pad.GetNetname().split("/")[-1]
            if n in nets or (fp.GetReference() in pad_refs and pad.GetNumber() in pad_refs[fp.GetReference()]):
                bb2 = pad.GetBoundingBox()
                xs += [pcbnew.ToMM(bb2.GetLeft()), pcbnew.ToMM(bb2.GetRight())]
                ys += [pcbnew.ToMM(bb2.GetTop()), pcbnew.ToMM(bb2.GetBottom())]
    if not xs:
        return
    m = 1.0
    z = pcbnew.ZONE(b)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowTracks(False)
    z.SetDoNotAllowVias(True)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    ls = pcbnew.LSET()
    for l in layers:
        ls.AddLayer(l)
    z.SetLayerSet(ls)
    z.SetZoneName(name)
    rect_outline(z, min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m)
    b.Add(z)
    print(f"keep-out {name}: x {min(xs) - m:.1f}..{max(xs) + m:.1f} y {min(ys) - m:.1f}..{max(ys) + m:.1f}")


keepout("ISO_CAN", {"CAN_GND", "CAN_VISO", "CANH", "CANL", "CAN_TERM_MID"}, {"U20": {str(i) for i in range(9, 17)}}, [pcbnew.In1_Cu, pcbnew.In2_Cu])
keepout("ISO_485", {"ISO_GND", "ISO_3V3", "RS485_A", "RS485_B", "RS485_TERM_MID"}, {"U21": {str(i) for i in range(9, 17)}}, [pcbnew.In1_Cu, pcbnew.In2_Cu])

# board setup defaults for JLCPCB 4-layer
bds = b.GetDesignSettings()
bds.m_TrackMinWidth = mm(0.15)
bds.m_ViasMinSize = mm(0.5)
bds.m_MinThroughDrill = mm(0.3)
bds.m_CopperEdgeClearance = mm(0.4)
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(PCB, b)
print("planes: In1/In2 GND; zones:", len(list(b.Zones())))
