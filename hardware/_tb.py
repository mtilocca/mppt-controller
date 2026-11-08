import pcbnew,math
from pcbnew import ToMM as t
b=pcbnew.LoadBoard("mppt_controller.kicad_pcb")
for r in ("J1","J2","J3","J4","J5","J9","J10"):
    fp=b.FindFootprintByReference(r); pos=fp.GetPosition(); a=math.radians(fp.GetOrientationDegrees()); c,s=math.cos(a),math.sin(a)
    def loc(p): dx,dy=t(p.x-pos.x),t(p.y-pos.y); return (round(dx*c-dy*s,2),round(dx*s+dy*c,2))
    pads=[loc(p.GetPosition()) for p in fp.Pads()]
    cy=fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
    cc=[loc(pcbnew.VECTOR2I(cy.GetX(),cy.GetY())),loc(pcbnew.VECTOR2I(cy.GetRight(),cy.GetBottom()))]
    print(r,fp.GetFPIDAsString(),fp.GetOrientationDegrees(),"pos",round(t(pos.x),1),round(t(pos.y),1),"pads",pads,"court",cc,[ (m.m_Filename.split('/')[-1],m.m_Rotation.z,m.m_Offset.x) for m in fp.Models()])
