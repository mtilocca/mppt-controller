import pcbnew,math
b=pcbnew.LoadBoard("_before_rest.kicad_pcb")
for r in ("J8","J11"):
    fp=b.FindFootprintByReference(r); print(r,fp.GetPosition().x/1e6,fp.GetPosition().y/1e6,fp.GetOrientationDegrees())
    for p in fp.Pads():
        q=p.GetFPRelativePosition(); print(" ",p.GetNumber(),round(q.x/1e6,2),round(q.y/1e6,2),round(p.GetSize().x/1e6,2),round(p.GetSize().y/1e6,2))
