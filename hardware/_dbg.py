import sys
sys.argv = ["x", "_rp_test.kicad_pcb", "NONE"]
exec(open("route_power.py").read().split("rasterise()\nnames")[0])
rasterise()
name = [n for n in netcode if short(n) == "SW1"][0]
code = netcode[name]
items, comps = net_pieces(name)
print("pieces", len(comps), [len(c) for c in comps])
for cmp_ in comps:
    cs = cells_of(items, cmp_, code)
    xs = [c[1] for c in cs]; ys = [c[2] for c in cs]
    print(" piece cells", len(cs), "bbox mm", min(xs)*RES, min(ys)*RES, max(xs)*RES, max(ys)*RES, "layers", sorted({c[0] for c in cs}))
# flood from first piece
other = [(ids[k] != 0) & (ids[k] != code) for k in range(3)]
rs = int(math.ceil((0.4/2 + CLR)/RES))
allowed = [~dilate(other[k], rs) for k in (0,1,2)]
src = cells_of(items, comps[0], code)
seen = set(src); st = list(src)
dsts = set()
for cm in comps[1:]: dsts |= cells_of(items, cm, code)
hit = None
while st:
    k,i,j = st.pop()
    if (k,i,j) in dsts: hit=(k,i,j); break
    for di,dj,_ in MOVES:
        n=(k,i+di,j+dj)
        if 0<=n[1]<NX and 0<=n[2]<NY and n not in seen and (allowed[k][n[1],n[2]] or n in dsts):
            seen.add(n); st.append(n)
    if len(seen)>2_000_000: break
print("flood size", len(seen), "hit", hit)
