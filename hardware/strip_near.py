"""strip_near.py PCB R1,R2,.. RADIUS -- remove (non-GND) tracks of the nets of those connectors that start/end within RADIUS mm of a pad"""
import sys, math, pcbnew
from pcbnew import ToMM as t_
b = pcbnew.LoadBoard(sys.argv[1]); R = float(sys.argv[3])
pads = []
for r in sys.argv[2].split(","):
    for p in b.FindFootprintByReference(r).Pads():
        pads.append((t_(p.GetPosition().x), t_(p.GetPosition().y), p.GetNetname()))
if len(sys.argv) > 4:                      # also the pad positions of an older board (before the connectors moved)
    o = pcbnew.LoadBoard(sys.argv[4])
    for r in sys.argv[2].split(","):
        for p in o.FindFootprintByReference(r).Pads():
            pads.append((t_(p.GetPosition().x), t_(p.GetPosition().y), p.GetNetname()))
gone = []
for t in b.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T: continue
    n = t.GetNetname()
    if n == "GND": continue
    ends = [(t_(t.GetStart().x), t_(t.GetStart().y)), (t_(t.GetEnd().x), t_(t.GetEnd().y))]
    if any(pn == n and math.hypot(x - px, y - py) <= R for (px, py, pn) in pads for (x, y) in ends):
        gone.append(t.m_Uuid.AsString())
for t in list(b.GetTracks()):
    if t.m_Uuid.AsString() in gone: b.Remove(t)
print("removed", len(gone))
pcbnew.SaveBoard(sys.argv[1], b)
