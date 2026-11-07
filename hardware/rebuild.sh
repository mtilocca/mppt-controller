#!/bin/bash
# rebuild.sh: schematic netlist -> fresh PCB -> placement -> setup (planes, rules). Run from hardware/.
set -e
K="flatpak run --command=python3 org.kicad.KiCad"
.venv/bin/python mppt_controller.py > /dev/null 2>&1
flatpak run --command=kicad-cli org.kicad.KiCad sch export netlist --format kicadsexpr -o mppt_controller_kicad.net mppt_controller.kicad_sch > /dev/null 2>&1
$K make_pcb.py mppt_controller_kicad.net mppt_controller.kicad_pcb 2>&1 | tail -1
$K place_pcb.py mppt_controller.kicad_pcb 2>&1 | tail -1
$K setup_board.py mppt_controller.kicad_pcb 2>&1 | grep -v "swig/python" | tail -3
