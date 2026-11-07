"""make_3d.py -- simple parametric VRML bodies for parts that have no stock 3D model; assigns models to the board.
Run with KiCad's python. Bodies are boxes/cylinders sized from the datasheet outline (approximate, for fit checking)."""
import os, sys, math, pcbnew
from pcbnew import ToMM as tomm
PCB = sys.argv[1]; OUT = os.path.abspath("../3d"); os.makedirs(OUT, exist_ok=True)
b = pcbnew.LoadBoard(PCB)
STOCK = "${KICAD10_3DMODEL_DIR}/"
# ref -> (kind, dims (w,h,height mm) or stock model, colour)
SPEC = {
 "L1": ("cyl", (24.6, 15.5, 15.5), (0.15, 0.15, 0.17)),       # vertical toroid: use footprint extents
 "F2": ("box", None, (0.9, 0.2, 0.2), 19.0),
 "J8": ("box", None, (0.75, 0.75, 0.78), 13.1),               # HR911105A
 "J11": ("box", None, (0.7, 0.7, 0.72), 3.3),                 # USB-C receptacle
 "L2": ("box", (12.5, 12.5, 4.8), (0.1, 0.1, 0.12), 4.8),     # SRP1245A
}
def local_bbox(fp):
    pos = fp.GetPosition(); ang = fp.GetOrientationDegrees(); xs = []; ys = []
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    for p in fp.Pads():
        d = p.GetPosition() - pos; x, y = tomm(d.x), tomm(d.y)
        lx, ly = x * c - y * s, x * s + y * c            # rotate back by +ang (KiCad angle is CCW, y down)
        w, h = tomm(p.GetSize().x), tomm(p.GetSize().y)
        xs += [lx - w / 2, lx + w / 2]; ys += [ly - h / 2, ly + h / 2]
    cy = fp.GetCourtyard(pcbnew.F_CrtYd)
    if cy.OutlineCount():
        bb = cy.BBox()
        pass
    return min(xs), max(xs), min(ys), max(ys)
def box_wrl(path, x0, x1, y0, y1, h, col):
    cx, cy_, sx, sy = (x0 + x1) / 2, -(y0 + y1) / 2, x1 - x0, y1 - y0   # VRML y up in footprint plane = -y
    open(path, "w").write(f"""#VRML V2.0 utf8
Transform {{ translation {cx} {cy_} {h/2} children Shape {{
 appearance Appearance {{ material Material {{ diffuseColor {col[0]} {col[1]} {col[2]} }} }}
 geometry Box {{ size {sx} {sy} {h} }} }} }}
""")
def cyl_wrl(path, cx, cy_, r, h, col):
    open(path, "w").write(f"""#VRML V2.0 utf8
Transform {{ translation {cx} {-cy_} {h/2} rotation 1 0 0 1.5708 children Shape {{
 appearance Appearance {{ material Material {{ diffuseColor {col[0]} {col[1]} {col[2]} }} }}
 geometry Cylinder {{ radius {r} height {h} }} }} }}
""")
def attach(fp, path):
    for m in list(fp.Models()): fp.Models().remove(m) if hasattr(fp.Models(), "remove") else None
    m = pcbnew.FP_3DMODEL(); m.m_Filename = path; fp.Add3DModel(m)
for fp in b.GetFootprints():
    ref = fp.GetReference()
    if ref == "U2":                      # LM5177 HTSSOP-38 4.4x9.7: stock TSSOP-38 body, same outline
        while len(fp.Models()): fp.Models().pop()
        m = pcbnew.FP_3DMODEL(); m.m_Filename = STOCK + "Package_SO.3dshapes/TSSOP-38_4.4x9.7mm_P0.5mm.step"
        m.m_Scale.x = m.m_Scale.y = m.m_Scale.z = 1.0; fp.Add3DModel(m)
        continue
    if ref not in SPEC: continue
    kind, dims, col = SPEC[ref][:3]
    x0, x1, y0, y1 = local_bbox(fp)
    p = f"{OUT}/{ref}.wrl"
    if ref == "L1":
        cx, cy_ = (x0 + x1) / 2, (y0 + y1) / 2
        box_wrl(p, cx - 12.3, cx + 12.3, cy_ - 12.3, cy_ + 12.3, 15.5, col)
    else:
        h = SPEC[ref][3]
        if dims: w, d = dims[0], dims[1]; cx, cy_ = (x0 + x1) / 2, (y0 + y1) / 2; x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy_ - d / 2, cy_ + d / 2
        else:
            ex = 1.0 if ref != "J8" else 3.0; x0 -= ex; x1 += ex; y0 -= ex; y1 += ex
        box_wrl(p, x0, x1, y0, y1, h, col)
    while len(fp.Models()): fp.Models().pop()
    m = pcbnew.FP_3DMODEL(); m.m_Filename = "${KIPRJMOD}/../3d/%s.wrl" % ref
    m.m_Scale.x = m.m_Scale.y = m.m_Scale.z = 1 / 2.54; fp.Add3DModel(m)   # KiCad VRML unit = 0.1 inch
    print(ref, "->", p, "bbox", round(x0,1), round(x1,1), round(y0,1), round(y1,1))
pcbnew.SaveBoard(PCB, b)
