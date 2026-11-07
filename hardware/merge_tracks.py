"""merge_tracks.py NEW OLD : copy tracks/vias that exist in OLD but are missing in NEW (the SES import drops locked-phase tracks)."""
import sys, pcbnew
new = pcbnew.LoadBoard(sys.argv[1]); old = pcbnew.LoadBoard(sys.argv[2])
def key(t):
    if t.Type() == pcbnew.PCB_VIA_T:
        p = t.GetPosition(); return ("v", p.x, p.y)
    a, c = t.GetStart(), t.GetEnd()
    k = sorted([(a.x, a.y), (c.x, c.y)])
    return ("t", t.GetLayer(), tuple(k[0]), tuple(k[1]))
have = {key(t) for t in new.GetTracks()}
n = 0
for t in list(old.GetTracks()):
    if key(t) in have: continue
    c = t.Duplicate(); c.SetNet(new.FindNet(t.GetNetname())); new.Add(c); n += 1
print("copied", n)
pcbnew.SaveBoard(sys.argv[1], new)
