import sys,pcbnew
pcb,ref,path,ox,oy,oz,rz=sys.argv[1],sys.argv[2],sys.argv[3],*map(float,sys.argv[4:8])
b=pcbnew.LoadBoard(pcb); fp=b.FindFootprintByReference(ref)
while len(fp.Models()): fp.Models().pop()
m=pcbnew.FP_3DMODEL(); m.m_Filename=path
m.m_Offset.x,m.m_Offset.y,m.m_Offset.z=ox,oy,oz
m.m_Rotation.x,m.m_Rotation.y,m.m_Rotation.z=0,0,rz
m.m_Scale.x=m.m_Scale.y=m.m_Scale.z=1.0
fp.Add3DModel(m); pcbnew.SaveBoard(pcb,b)
