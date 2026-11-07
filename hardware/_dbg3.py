import sys
sys.argv = ["x", "mppt_controller.kicad_pcb", "NONE"]
exec(open("route_power.py").read().split("rasterise()\nnames")[0])
name=[n for n in netcode if short(n)=="SW1"][0]
items, comps = net_pieces(name)
print("pieces", len(comps), "items", len(items))
tr=[t for t in b.GetTracks() if t.GetNetname()==name]
print("tracks", len(tr), "vias", sum(1 for t in tr if t.Type()==pcbnew.PCB_VIA_T))
import collections
print(collections.Counter((round(tomm(t.GetStart().x),1),round(tomm(t.GetStart().y),1),round(tomm(t.GetEnd().x),1),round(tomm(t.GetEnd().y),1),round(tomm(t.GetWidth()),2)) for t in tr if t.Type()!=pcbnew.PCB_VIA_T).most_common(4))
for cm in comps:
    xs=[]
    for m in cm:
        for k,shp in items[m].items():
            bx=shp.BBox(); xs.append((round(tomm(bx.GetX()),1),round(tomm(bx.GetY()),1),k))
    print(len(cm), xs[:3])
