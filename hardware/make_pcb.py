"""
make_pcb.py -- import the schematic netlist into a new KiCad PCB (what File > Import > Netlist does).

Run with KiCad's own Python so `pcbnew` is available:
  flatpak run --command=python3 org.kicad.KiCad make_pcb.py valve_controller_kicad.net valve_controller.kicad_pcb

The netlist must be the one exported by KiCad from the schematic (kicad-cli sch export netlist),
so every footprint keeps the link to its schematic symbol ("Update PCB from Schematic" keeps working).
Footprints are placed in a staging area to the right of a 70 x 60 mm board outline, one column per block.
"""
import os
import re
import sys
from collections import defaultdict

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from net2sch import child, parse  # noqa: E402

FP_ROOT = "/app/extensions/Library/footprints"
MM = pcbnew.FromMM
BOARD_W, BOARD_H = float(os.environ.get("BOARD_W", 175)), float(os.environ.get("BOARD_H", 120))


def sheet_of(c):
    sp = child(c, "sheetpath")
    names = str(child(sp, "names")[1]).strip("/") if sp else ""
    return re.sub(r"_?\d+$", "", names) or "top"


def main(netfile, out):
    tree = parse(open(netfile, encoding="utf-8").read())
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)

    # board outline
    pts = [(0, 0), (BOARD_W, 0), (BOARD_W, BOARD_H), (0, BOARD_H), (0, 0)]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(pcbnew.VECTOR2I(MM(x1), MM(y1)))
        seg.SetEnd(pcbnew.VECTOR2I(MM(x2), MM(y2)))
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetWidth(MM(0.1))
        board.Add(seg)

    # footprints
    fps, by_sheet, missing = {}, defaultdict(list), []
    for c in child(tree, "components")[1:]:
        ref = str(child(c, "ref")[1])
        fpn = child(c, "footprint")
        if not fpn or not str(fpn[1]):
            missing.append(ref)
            continue
        lib, name = str(fpn[1]).split(":")
        fp = pcbnew.FootprintLoad(os.path.join(FP_ROOT, lib + ".pretty"), name)
        if fp is None:
            missing.append(f"{ref} ({fpn[1]})")
            continue
        fp.SetReference(ref)
        fp.SetValue(str(child(c, "value")[1]))
        sp = child(c, "sheetpath")
        path = (str(child(sp, "tstamps")[1]) if sp else "/") + str(child(c, "tstamps")[1])
        fp.SetPath(pcbnew.KIID_PATH(path))
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        board.Add(fp)
        fps[ref] = fp
        by_sheet[sheet_of(c)].append(ref)

    # nets and pad assignment
    nets, unassigned = 0, []
    for n in child(tree, "nets")[1:]:
        name = str(child(n, "name")[1])
        item = pcbnew.NETINFO_ITEM(board, name)
        board.Add(item)
        nets += 1
        for nd in n[1:]:
            if isinstance(nd, list) and nd[0] == "node":
                ref, pin = str(child(nd, "ref")[1]), str(child(nd, "pin")[1])
                fp = fps.get(ref)
                pads = [p for p in fp.Pads() if p.GetNumber() == pin] if fp else []
                if not pads:
                    unassigned.append(f"{ref}.{pin}")
                for pad in pads:                  # all pads with this number (thermal vias etc.)
                    pad.SetNet(item)

    # staging area: one column per block, to the right of the outline
    x0 = BOARD_W + 15.0
    for col, sheet in enumerate(sorted(by_sheet)):
        y = 0.0
        x = x0 + col * 45.0
        for ref in sorted(by_sheet[sheet], key=lambda r: (re.match(r"[A-Za-z]+", r).group(0), int(re.search(r"\d+", r).group(0)))):
            fp = fps[ref]
            bb = fp.GetBoundingBox()
            w, h = pcbnew.ToMM(bb.GetWidth()), pcbnew.ToMM(bb.GetHeight())
            fp.SetPosition(pcbnew.VECTOR2I(MM(x + w / 2), MM(y + h / 2)))
            y += h + 3.0

    board.BuildListOfNets()
    pcbnew.SaveBoard(out, board)
    print(f"footprints placed: {len(fps)}, nets: {nets}")
    if missing:
        print("missing footprints:", missing)
    if unassigned:
        print("pads not found:", unassigned)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
