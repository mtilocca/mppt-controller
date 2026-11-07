"""
route_power.py -- clearance-aware A* router for what Freerouting leaves: the high-current nets (wide), 3V3, and leftover signals.

  flatpak run --command=python3 org.kicad.KiCad route_power.py mppt_controller.kicad_pcb [net ...]

Raster: 0.1 mm cells, one net-id grid per copper layer (F.Cu, In2.Cu, B.Cu); other nets' copper is dilated by clearance + half the
track width (square dilation, so slightly conservative). Every path is searched with the narrow width and emitted wide where the wide
corridor is free (so a 2 mm trunk can taper to 0.3 mm near small pads). High-current nets use F.Cu/B.Cu only.
GND is not routed (outer-layer pours + In1 plane + stitching vias, see post_route.py).
"""
import gc
import heapq
import math
import sys
from collections import defaultdict

import numpy as np
import pcbnew
from pcbnew import VECTOR2I, FromMM as mm, ToMM as tomm

gc.disable()
_keep = []
PCB = sys.argv[1]
ONLY = [a for a in sys.argv[2:] if not a.startswith('--')]
REST = '--rest' in sys.argv
b = pcbnew.LoadBoard(PCB)
RES = 0.1
bb = b.GetBoardEdgesBoundingBox()
BW, BH = tomm(bb.GetRight()), tomm(bb.GetBottom())
NX, NY = int(BW / RES) + 1, int(BH / RES) + 1
CLR = 0.17                   # routing clearance (DRC rule is 0.15)
LAYERS = [pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
LIDX = {l: k for k, l in enumerate(LAYERS)}

HC = ["SW1", "SW2", "VIN_CS", "VOUT", "VIN_PWR", "PV_D", "PV_F", "PV_RAW", "BAT_BUS", "BAT_F", "BAT_NEG", "BAT_RAW",
      "LOAD_SENSE", "LOAD_OUT", "INV_SENSE", "INV_OUT"]
HC_BIG, HC_SMALL = 2.0, 0.3
VIA_HC, VIA_SIG = (0.8, 0.4), (0.6, 0.3)


def short(n):
    return n.split("/")[-1]


netcode = {}
for name, n in b.GetNetsByName().items():
    netcode[str(name)] = n.GetNetCode()
code_name = {v: k for k, v in netcode.items()}

ids = [np.zeros((NX, NY), np.int32) for _ in LAYERS]


def cx(v):
    return int(round(tomm(v) / RES))


def stamp_rect(L, x0, y0, x1, y1, code):
    i0, i1 = max(0, int(math.floor(x0 / RES))), min(NX - 1, int(math.ceil(x1 / RES)))
    j0, j1 = max(0, int(math.floor(y0 / RES))), min(NY - 1, int(math.ceil(y1 / RES)))
    if i1 >= i0 and j1 >= j0:
        sl = ids[L][i0:i1 + 1, j0:j1 + 1]
        sl[:] = np.where((sl == 0) | (sl == code), code, -1)      # two nets on one cell -> hard obstacle


def stamp_seg(L, x0, y0, x1, y1, w, code):
    n = max(1, int(math.hypot(x1 - x0, y1 - y0) / (RES * 0.7)))
    for k in range(n + 1):
        t = k / n
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        stamp_rect(L, x - w / 2, y - w / 2, x + w / 2, y + w / 2, code)


def rasterise():
    for L in ids:
        L[:] = 0
    for p in b.GetPads():
        code = p.GetNetCode() if p.GetNetCode() > 0 else -1
        r = p.GetBoundingBox()
        for k, lay in enumerate(LAYERS):
            if p.IsOnLayer(lay):
                stamp_rect(k, tomm(r.GetX()), tomm(r.GetY()), tomm(r.GetRight()), tomm(r.GetBottom()), code)
    for t in b.GetTracks():
        code = t.GetNetCode() if t.GetNetCode() > 0 else -1
        if t.Type() == pcbnew.PCB_VIA_T:
            q = t.GetPosition()
            d = tomm(t.GetWidth(pcbnew.F_Cu))
            for k in range(len(LAYERS)):
                stamp_rect(k, tomm(q.x) - d / 2, tomm(q.y) - d / 2, tomm(q.x) + d / 2, tomm(q.y) + d / 2, code)
        elif t.GetLayer() in LIDX:
            a, c = t.GetStart(), t.GetEnd()
            stamp_seg(LIDX[t.GetLayer()], tomm(a.x), tomm(a.y), tomm(c.x), tomm(c.y), tomm(t.GetWidth()), code)
    for k in range(len(LAYERS)):                 # board edge
        m = int(0.5 / RES)
        ids[k][:m, :] = -1
        ids[k][-m:, :] = -1
        ids[k][:, :m] = -1
        ids[k][:, -m:] = -1
    for z in b.Zones():                          # keep-out rule areas that forbid tracks
        if z.GetIsRuleArea() and z.GetDoNotAllowTracks():
            r = z.GetBoundingBox()
            for k, lay in enumerate(LAYERS):
                if z.GetLayerSet().Contains(lay):
                    stamp_rect(k, tomm(r.GetX()), tomm(r.GetY()), tomm(r.GetRight()), tomm(r.GetBottom()), -1)


def dilate(mask, r):
    """Square dilation by r cells using an integral image."""
    if r <= 0:
        return mask
    S = np.zeros((NX + 1, NY + 1), np.int32)
    S[1:, 1:] = mask.cumsum(0).cumsum(1)
    i0 = np.clip(np.arange(NX) - r, 0, NX)
    i1 = np.clip(np.arange(NX) + r + 1, 0, NX)
    j0 = np.clip(np.arange(NY) - r, 0, NY)
    j1 = np.clip(np.arange(NY) + r + 1, 0, NY)
    tot = S[np.ix_(i1, j1)] - S[np.ix_(i0, j1)] - S[np.ix_(i1, j0)] + S[np.ix_(i0, j0)]
    return tot > 0


def net_pieces(name):
    """Connected pieces of a net: lists of (layer index or None=all, shape)."""
    items = []
    for p in b.GetPads():
        if p.GetNetname() == name:
            items.append({k: p.GetEffectiveShape(lay) for k, lay in enumerate(LAYERS) if p.IsOnLayer(lay)})
    for t in b.GetTracks():
        if t.GetNetname() != name:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            items.append({k: t.GetEffectiveShape(lay) for k, lay in enumerate(LAYERS)})
        elif t.GetLayer() in LIDX:
            items.append({LIDX[t.GetLayer()]: t.GetEffectiveShape()})
    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a in range(len(items)):
        for c in range(a + 1, len(items)):
            if find(a) == find(c):
                continue
            if any(k in items[c] and items[a][k].Collide(items[c][k], 0) for k in items[a]):
                parent[find(a)] = find(c)
    comp = defaultdict(list)
    for k in range(len(items)):
        comp[find(k)].append(k)
    return items, list(comp.values())


def cells_of(items, members, code):
    out = set()
    for m in members:
        for k, shp in items[m].items():
            bbx = shp.BBox()
            i0, i1 = max(0, int(tomm(bbx.GetX()) / RES) - 1), min(NX - 1, int(tomm(bbx.GetRight()) / RES) + 1)
            j0, j1 = max(0, int(tomm(bbx.GetY()) / RES) - 1), min(NY - 1, int(tomm(bbx.GetBottom()) / RES) + 1)
            sub = ids[k][i0:i1 + 1, j0:j1 + 1]
            for i, j in zip(*np.nonzero(sub == code)):
                out.add((k, i0 + int(i), j0 + int(j)))
    return out


MOVES = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]


def astar(allowed, bigok, viaok, src, dst, layers_ok):
    dsts = sorted({(c[1], c[2]) for c in dst})
    step = max(1, len(dsts) // 24)
    samp = dsts[::step]

    def hfun(i, j):
        best = 1e18
        for (gi, gj) in samp:
            dx, dy = abs(i - gi), abs(j - gj)
            v = (dx + dy) + (1.414 - 2) * min(dx, dy)
            if v < best:
                best = v
        return best
    dist, prev, heap = {}, {}, []
    for s in src:
        dist[s] = 0
        heapq.heappush(heap, (hfun(s[1], s[2]), 0, s))
    steps = 0
    while heap:
        _, d, s = heapq.heappop(heap)
        if d > dist.get(s, 1e18):
            continue
        if s in dst:
            path = [s]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return path[::-1]
        steps += 1
        if steps > 3_000_000:
            return None
        k, i, j = s
        for di, dj, c in MOVES:
            ni, nj = i + di, j + dj
            if 0 <= ni < NX and 0 <= nj < NY:
                n = (k, ni, nj)
                if n in dst or allowed[k][ni, nj]:
                    cost = c * (1.0 if bigok[k][ni, nj] else 2.2)
                    nd = d + cost
                    if nd < dist.get(n, 1e18):
                        dist[n] = nd
                        prev[n] = s
                        heapq.heappush(heap, (nd + hfun(ni, nj), nd, n))
        if viaok[i, j]:
            for k2 in layers_ok:
                if k2 != k:
                    n = (k2, i, j)
                    nd = d + 12
                    if nd < dist.get(n, 1e18):
                        dist[n] = nd
                        prev[n] = s
                        heapq.heappush(heap, (nd + hfun(i, j), nd, n))
    return None


def snap_pad(netname, cell, w, n, code):
    """Connect a path end to the nearest real copper of the net (pad centre, via, or closest point on a track)."""
    k, i, j = cell
    x, y = i * RES, j * RES
    best = None
    for p in b.GetPads():
        if p.GetNetname() == netname and p.IsOnLayer(LAYERS[k]):
            q = p.GetPosition()
            r = p.GetBoundingBox()
            inside = tomm(r.GetX()) - 0.02 <= x <= tomm(r.GetRight()) + 0.02 and tomm(r.GetY()) - 0.02 <= y <= tomm(r.GetBottom()) + 0.02
            d = 0.0 if inside else math.hypot(tomm(q.x) - x, tomm(q.y) - y)
            if best is None or d < best[0]:
                best = (d, tomm(q.x), tomm(q.y), "pad" if inside else "padc")
    for t in b.GetTracks():
        if t.GetNetname() != netname:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            q = t.GetPosition()
            d = math.hypot(tomm(q.x) - x, tomm(q.y) - y) - tomm(t.GetWidth(pcbnew.F_Cu)) / 2
            cand = (max(d, 0), tomm(q.x), tomm(q.y), "via")
        elif t.GetLayer() == LAYERS[k]:
            a, c = t.GetStart(), t.GetEnd()
            ax, ay, cx_, cy_ = tomm(a.x), tomm(a.y), tomm(c.x), tomm(c.y)
            dx, dy = cx_ - ax, cy_ - ay
            L2 = dx * dx + dy * dy
            u = 0 if L2 == 0 else max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / L2))
            px, py = ax + u * dx, ay + u * dy
            cand = (max(math.hypot(px - x, py - y) - tomm(t.GetWidth()) / 2, 0), px, py, "trk")
        else:
            continue
        if best is None or cand[0] < best[0]:
            best = cand
    if best is None or best[0] > 1.5:
        return
    d, qx, qy, kind = best
    if math.hypot(qx - x, qy - y) > 0.02:
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(VECTOR2I(mm(qx), mm(qy)))
        t.SetEnd(VECTOR2I(mm(x), mm(y)))
        t.SetWidth(mm(min(w, 0.2)))
        t.SetLayer(LAYERS[k])
        t.SetNet(n)
        b.Add(t)
        _keep.append(t)


def emit(netname, path, wbig, wsmall, bigok, via_d, via_dr):
    n = b.FindNet(netname)
    code = n.GetNetCode()
    snap_pad(netname, path[0], wsmall, n, code)
    snap_pad(netname, path[-1], wsmall, n, code)
    # split into per-layer runs, choose width per cell
    run = [path[0]]
    runs = []
    for a, c in zip(path, path[1:]):
        if c[0] != a[0]:
            runs.append(run)
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(VECTOR2I(mm(a[1] * RES), mm(a[2] * RES)))
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetWidth(pcbnew.F_Cu, mm(via_d))
            v.SetDrill(mm(via_dr))
            v.SetNet(n)
            b.Add(v)
            _keep.append(v)
            for k in range(len(LAYERS)):
                stamp_rect(k, a[1] * RES - via_d / 2, a[2] * RES - via_d / 2, a[1] * RES + via_d / 2, a[2] * RES + via_d / 2, code)
            run = [c]
        else:
            run.append(c)
    runs.append(run)
    count = 0
    for run in runs:
        k = run[0][0]
        # width of each cell, then merge into straight segments of constant width
        ws = [wbig if bigok[k][i, j] else wsmall for (_, i, j) in run]
        # a wide segment needs both ends wide and its neighbours wide: smooth by erosion of 3 cells
        ws = [wbig if all(w == wbig for w in ws[max(0, x - 3):x + 4]) else wsmall for x in range(len(ws))]
        seg = [run[0]]
        segw = ws[0]
        pieces = []
        for x in range(1, len(run)):
            dirp = (run[x][1] - run[x - 1][1], run[x][2] - run[x - 1][2])
            if len(seg) >= 2:
                dirq = (seg[-1][1] - seg[-2][1], seg[-1][2] - seg[-2][2])
            else:
                dirq = dirp
            if dirp != dirq or ws[x] != segw:
                pieces.append((seg[0], seg[-1], segw))
                seg = [seg[-1], run[x]] if ws[x] == segw or True else [run[x]]
                segw = ws[x]
            else:
                seg.append(run[x])
        pieces.append((seg[0], seg[-1], segw))
        for a, c, w in pieces:
            if (a[1], a[2]) == (c[1], c[2]):
                continue
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(VECTOR2I(mm(a[1] * RES), mm(a[2] * RES)))
            t.SetEnd(VECTOR2I(mm(c[1] * RES), mm(c[2] * RES)))
            t.SetWidth(mm(w))
            t.SetLayer(LAYERS[k])
            t.SetNet(n)
            b.Add(t)
            _keep.append(t)
            stamp_seg(k, a[1] * RES, a[2] * RES, c[1] * RES, c[2] * RES, w, code)
            count += 1
    return count


def escape_stubs(name):
    """Straight 0.9 mm stubs out of fine-pitch IC pins so that the grid router can leave the pad."""
    n = b.FindNet(name)
    code = n.GetNetCode()
    made = 0
    for p in b.GetPads():
        if p.GetNetname() != name:
            continue
        fp = p.GetParentFootprint()
        r = p.GetBoundingBox()
        w, h = tomm(r.GetWidth()), tomm(r.GetHeight())
        if min(w, h) >= 0.45 or not fp.GetReference().startswith(("U", "J")) or not p.IsOnLayer(pcbnew.F_Cu):
            continue
        c = fp.GetPosition()
        q = p.GetPosition()
        if w > h:      # long axis x
            d = (1 if q.x >= c.x else -1, 0)
        else:
            d = (0, 1 if q.y >= c.y else -1)
        # the footprint origin is not always the body centre: use the body bbox centre
        bb2 = fp.GetBoundingBox(False)
        cxm, cym = tomm(bb2.GetX() + bb2.GetWidth() // 2), tomm(bb2.GetY() + bb2.GetHeight() // 2)
        px, py = tomm(q.x), tomm(q.y)
        d0 = ((1 if px >= cxm else -1), 0) if w > h else (0, (1 if py >= cym else -1))
        for (L, sgn) in ((0.9, 1), (0.6, 1), (0.9, -1), (0.6, -1), (0.4, 1)):
            d = (d0[0] * sgn, d0[1] * sgn)
            ex, ey = px + d[0] * L, py + d[1] * L
            xs0, xs1 = sorted((px, ex))
            ys0, ys1 = sorted((py, ey))
            i0, i1 = int((xs0 - 0.05) / RES), int((xs1 + 0.05) / RES) + 1
            j0, j1 = int((ys0 - 0.05) / RES), int((ys1 + 0.05) / RES) + 1
            blk = ids[0][i0:i1 + 1, j0:j1 + 1]
            if not ((blk != 0) & (blk != code)).any():
                t = pcbnew.PCB_TRACK(b)
                t.SetStart(q)
                t.SetEnd(VECTOR2I(mm(ex), mm(ey)))
                t.SetWidth(mm(0.15 if min(w, h) < 0.3 else 0.2))
                t.SetLayer(pcbnew.F_Cu)
                t.SetNet(n)
                b.Add(t)
                _keep.append(t)
                stamp_seg(0, px, py, ex, ey, 0.2, code)
                made += 1
                break
    return made


def route_net(name):
    hc = short(name) in HC
    wbig, wsmall = (HC_BIG, HC_SMALL) if hc else (0.4, 0.25) if short(name) in ("3V3", "3V3A", "5V", "VAUX", "VAUX_RAW") else (0.25, 0.2)
    via_d, via_dr = VIA_HC if hc else VIA_SIG
    layers_ok = [0, 2] if hc else [0, 1, 2]
    code = netcode[name]
    done = fail = 0
    escape_stubs(name)
    blacklist = set()
    for _ in range(300):
        items, comps = net_pieces(name)
        if len(comps) <= 1:
            break
        comps.sort(key=len)
        cand = None
        for cm in comps:
            key = tuple(sorted(cells_of(items, cm, code)))[:1]
            if key not in blacklist:
                cand = (cm, key)
                break
        if cand is None:
            break
        cm, key = cand
        src_cells = cells_of(items, cm, code)
        dst_cells = set()
        for cmp_ in comps:
            if cmp_ is not cm:
                dst_cells |= cells_of(items, cmp_, code)
        dst_cells -= src_cells
        if not src_cells or not dst_cells:
            blacklist.add(key)
            fail += 1
            continue
        other = [(ids[k] != 0) & (ids[k] != code) for k in range(len(LAYERS))]
        rb = int(math.ceil((wbig / 2 + CLR) / RES))
        rv = int(math.ceil((via_d / 2 + CLR) / RES))
        bigok = [~dilate(other[k], rb) for k in range(len(LAYERS))]
        viaok = ~np.logical_or.reduce([dilate(other[k], rv) for k in range(len(LAYERS))])
        path = None
        for wsm in (wsmall, 0.2, 0.15):
            rs = int(math.ceil((wsm / 2 + CLR) / RES))
            allowed = []
            for k in range(len(LAYERS)):
                ds = dilate(other[k], rs)
                allowed.append(~ds if k in layers_ok else np.zeros_like(ds))
            path = astar(allowed, bigok, viaok, src_cells, dst_cells, layers_ok)
            if path:
                wsmall_used = wsm
                break
        if not path:
            sx = sorted({(c[1], c[2]) for c in src_cells})
            print(f"   {short(name)}: no path from piece near {sx[0][0] * RES:.1f},{sx[0][1] * RES:.1f} ({len(src_cells)} cells)", flush=True)
            blacklist.add(key)
            fail += 1
            continue
        emit(name, path, wbig, wsmall_used, bigok, via_d, via_dr)
        done += 1
        _, comps_after = net_pieces(name)
        if len(comps_after) >= len(comps):
            a, c = path[0], path[-1]
            print(f"   {short(name)}: path ({a[1] * RES:.1f},{a[2] * RES:.1f},L{a[0]}) -> ({c[1] * RES:.1f},{c[2] * RES:.1f},L{c[0]}) did not join", flush=True)
            blacklist.add(key)
            fail += 1
    return done, fail


rasterise()
names = [n for n in netcode if n and n != "GND"]
if ONLY:
    targets = [n for n in names if short(n) in ONLY]
else:
    order = {h: i for i, h in enumerate(HC)}
    targets = sorted([n for n in names if short(n) in order], key=lambda n: order[short(n)])
    targets += [n for n in names if short(n) in ("3V3", "3V3A", "5V", "VAUX", "VAUX_RAW")]
    # leftover open signal nets (only with --rest)
    rest = []
    for n in (names if REST else []):
        if n in targets:
            continue
        items, comps = net_pieces(n)
        if len(comps) > 1:
            rest.append(n)
    targets += rest
tot = 0
for n in targets:
    d, f = route_net(n)
    tot += d
    print(f"{short(n):24s} connections routed: {d:3d}" + (f"  FAILED: {f}" if f else ""), flush=True)
pcbnew.SaveBoard(PCB, b)
print("saved; connections added:", tot)
