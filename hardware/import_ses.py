"""import_ses.py board.kicad_pcb session.ses [out.kicad_pcb]: import a Specctra session (default: in place)."""
import sys
import pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
print("import:", pcbnew.ImportSpecctraSES(b, sys.argv[2]))
pcbnew.SaveBoard(sys.argv[3] if len(sys.argv) > 3 else sys.argv[1], b)
