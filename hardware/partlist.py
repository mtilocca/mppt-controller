import pcbnew, sys, re
b = pcbnew.LoadBoard(sys.argv[1])
rows = []
for f in b.GetFootprints():
    bb = f.GetBoundingBox(False)
    rows.append((f.GetReference(), f.GetValue(), str(f.GetFPID().GetLibItemName()), round(pcbnew.ToMM(bb.GetWidth()), 1), round(pcbnew.ToMM(bb.GetHeight()), 1), f.IsFlipped()))
rows.sort(key=lambda r: (re.match(r"[A-Za-z]+", r[0]).group(0), int(re.search(r"\d+", r[0]).group(0))))
for r in rows: print("\t".join(map(str, r)))
