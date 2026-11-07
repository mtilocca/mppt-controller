#!/bin/bash
# render.sh [layers] [out.png] [dpi]: quick PNG of the board (F.Cu + fab + edge by default)
L=${1:-"F.Cu,F.Fab,Edge.Cuts"}; O=${2:-_view}; D=${3:-120}
flatpak run --command=kicad-cli org.kicad.KiCad pcb export pdf --mode-single --layers "$L" -o "$O.pdf" --scale 0 --sp mppt_controller.kicad_pcb >/dev/null 2>&1
pdftoppm -r $D -png -singlefile "$O.pdf" "$O" && echo "$O.png"
