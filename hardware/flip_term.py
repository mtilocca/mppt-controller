"""flip_term.py PCB -- rotate the MKDS screw terminals 180 deg about their courtyard centre and strip the copper that touched
their old pads (stub chains up to the first via/junction), so they can be re-routed."""
import sys, math, pcbnew
from pcbnew import VECTOR2I, FromMM as mm, ToMM as tomm
b = pcbnew.LoadBoard(sys.argv[1])
refs = ["J1", "J2", "J3", "J4"]
def pads_xy(fp): return [(p.GetPosition().x, p.GetPosition().y, p.GetNetname()) for p in fp.Pads()]
old = {}
for r in refs:
    fp = b.FindFootprintByReference(r); old[r] = pads_xy(fp)
    cy = fp.GetCourtyard(pcbnew.F_CrtYd).BBox(); cx, cyy = (cy.GetLeft() + cy.GetRight()) // 2, (cy.GetTop() + cy.GetBottom()) // 2
    fp.Rotate(VECTOR2I(cx, cyy), pcbnew.EDA_ANGLE(180, pcbnew.DEGREES_T))
    print(r, "orient", fp.GetOrientationDegrees())
# strip chains that touched old pad positions (pad is now elsewhere)
def near(px, py, x, y, tol=mm(0.15)): return abs(px - x) <= tol and abs(py - y) <= tol
T = []   # plain data: (uuid, net, is_via, x1, y1, x2, y2)
for t in b.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        q = t.GetPosition(); T.append((t.m_Uuid.AsString(), t.GetNetname(), True, q.x, q.y, q.x, q.y))
    else:
        s_, e_ = t.GetStart(), t.GetEnd(); T.append((t.m_Uuid.AsString(), t.GetNetname(), False, s_.x, s_.y, e_.x, e_.y))
gone = set()
for r in refs:
    for (x, y, net) in old[r]:
        frontier = [(x, y)]
        while frontier:
            fx, fy = frontier.pop(); segs = []; vias = 0
            for (u, n, isv, x1, y1, x2, y2) in T:
                if n != net or u in gone: continue
                if isv:
                    if near(x1, y1, fx, fy): vias += 1
                elif near(x1, y1, fx, fy): segs.append((u, x2, y2))
                elif near(x2, y2, fx, fy): segs.append((u, x1, y1))
            if vias or len(segs) != 1: continue
            gone.add(segs[0][0]); frontier.append((segs[0][1], segs[0][2]))
for t in list(b.GetTracks()):
    if t.m_Uuid.AsString() in gone: b.Remove(t)
removed = len(gone)
print("removed track segments:", removed)
pcbnew.SaveBoard(sys.argv[1], b)
