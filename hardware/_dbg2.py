import sys
sys.argv = ["x", "mppt_controller.kicad_pcb", "NONE"]
exec(open("route_power.py").read().split("rasterise()\nnames")[0])
rasterise()
for p in b.GetPads():
    if p.GetParentFootprint().GetReference()=="U2" and p.GetNumber() in ("36","25"):
        r=p.GetBoundingBox(); fp=p.GetParentFootprint()
        bb2=fp.GetBoundingBox(False)
        print(p.GetNumber(), p.GetNetname(), "bbox w,h", tomm(r.GetWidth()), tomm(r.GetHeight()), "pos", tomm(p.GetPosition().x), tomm(p.GetPosition().y),
              "body c", tomm(bb2.GetX()+bb2.GetWidth()//2), tomm(bb2.GetY()+bb2.GetHeight()//2), "orient", fp.GetOrientationDegrees())
        px,py=tomm(p.GetPosition().x),tomm(p.GetPosition().y)
        code=p.GetNetCode()
        for dx in (-0.9,0.9):
            i0,i1=sorted((int(px/RES),int((px+dx)/RES)))
            j0,j1=int((py-0.2)/RES),int((py+0.2)/RES)
            blk=ids[0][i0:i1+1,j0:j1+1]
            print("  dx",dx,"blocked cells", int(((blk!=0)&(blk!=code)).sum()), "of", blk.size, np.unique(blk)[:6])
