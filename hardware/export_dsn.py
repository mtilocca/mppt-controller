"""export_dsn.py board.kicad_pcb out.dsn: Specctra export with the high-current nets taken out (they become copper pours).
The board file on disk is NOT modified. In1.Cu is marked as a power plane (GND); In2.Cu is a routing layer."""
import re, sys
import pcbnew
HC = ["GND", "PV_RAW", "PV_F", "PV_D", "VIN_PWR", "VIN_CS", "SW1", "SW2", "VOUT", "BAT_RAW", "BAT_F", "BAT_NEG", "BAT_BUS",
      "LOAD_SENSE", "LOAD_OUT", "INV_SENSE", "INV_OUT"]
PHASE2 = "--phase2" in sys.argv
b = pcbnew.LoadBoard(sys.argv[1])
n0 = 0
if PHASE2:                       # round 2: keep routed tracks/vias, route only what is still open (3V3, high-current nets)
    HC[:] = ["GND"]
    for t in b.GetTracks():
        t.SetLocked(True)
for p in b.GetPads():
    if p.GetNetname().split("/")[-1] in HC:
        p.SetNetCode(0)
        n0 += 1
ok = pcbnew.ExportSpecctraDSN(b, sys.argv[2])
t = open(sys.argv[2]).read()
t = re.sub(r"\(layer (In1\.Cu)\s*\(type signal\)", r"(layer \1 (type power)", t)
open(sys.argv[2], "w").write(t)
print("export", ok, "pads detached from high-current nets:", n0)
