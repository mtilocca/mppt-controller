"""swap_net_tracks.py PCB OLDPCB NET -- replace all tracks/vias of NET in PCB by those of OLDPCB"""
import sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1]); o = pcbnew.LoadBoard(sys.argv[2]); net = sys.argv[3]
new = [t.Duplicate() for t in o.GetTracks() if t.GetNetname().split("/")[-1] == net]
old = [t for t in b.GetTracks() if t.GetNetname().split("/")[-1] == net]
nold = len(old)
for t in old: b.Remove(t)
for c in new: b.Add(c)
print("removed", nold, "added", len(new)); pcbnew.SaveBoard(sys.argv[1], b)
