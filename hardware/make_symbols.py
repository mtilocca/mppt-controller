#!/usr/bin/env python3
"""Writes mppt_custom.kicad_sym: parts that KiCad has no symbol for (pin numbers from the datasheets)."""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
FONT = "(effects (font (size 1.27 1.27)))"

def symbol(name, ref, desc, fp, left, right, pitch=2.54):
    """left/right: lists of (pin name, number, electrical type) top to bottom."""
    n = max(len(left), len(right))
    h = n * pitch / 2 + pitch
    w = 15.24
    out = [f'\t(symbol "{name}"', '\t\t(pin_names (offset 1.016))',
           '\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)',
           f'\t\t(property "Reference" "{ref}" (at 0 {h + 2.54:.2f} 0) {FONT})',
           f'\t\t(property "Value" "{name}" (at 0 {-h - 2.54:.2f} 0) {FONT})',
           f'\t\t(property "Footprint" "{fp}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
           '\t\t(property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
           f'\t\t(property "Description" "{desc}" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
           f'\t\t(symbol "{name}_0_1"',
           f'\t\t\t(rectangle (start {-w / 2:.2f} {h:.2f}) (end {w / 2:.2f} {-h:.2f}) (stroke (width 0.254) (type default)) (fill (type background)))',
           '\t\t)', f'\t\t(symbol "{name}_1_1"']
    for side, pins, x, ang in (("l", left, -w / 2 - 2.54, 0), ("r", right, w / 2 + 2.54, 180)):
        for k, (pn, num, ty) in enumerate(pins):
            y = h - pitch - k * pitch
            out.append(f'\t\t\t(pin {ty} line (at {x:.2f} {y:.2f} {ang}) (length 2.54)')
            out.append(f'\t\t\t\t(name "{pn}" {FONT})')
            out.append(f'\t\t\t\t(number "{num}" {FONT})')
            out.append('\t\t\t)')
    out += ['\t\t)', '\t)']
    return "\n".join(out)

I, O, P, B, W = "input", "output", "passive", "bidirectional", "power_in"

lm5177 = symbol("LM5177", "U", "TI LM5177 60 V 4-switch buck-boost controller, HTSSOP-38 (DCP), pins from SNVSBU4F Table 4-1",
    "Package_SO:HTSSOP-38-1EP_4.4x9.7mm_P0.5mm_EP2.74x4.75mm",
    [("VIN", "3", W), ("BIAS", "1", P), ("EN/UVLO", "4", I), ("SS/ATRK", "16", B), ("DTRK", "10", I), ("SYNC", "11", I),
     ("MODE", "12", I), ("CFG", "13", P), ("SLOPE", "14", P), ("RT", "15", P), ("COMP", "18", O), ("FB", "19", I),
     ("CSA", "37", I), ("CSB", "38", I), ("ISNSP", "23", I), ("ISNSN", "22", I), ("AGND", "17", W), ("PAD", "39", W)],
    [("VOUT", "20", I), ("HB1", "35", P), ("HO1", "34", O), ("SW1", "36", P), ("LO1", "32", O), ("VCC", "31", P),
     ("PGND", "30", W), ("LO2", "29", O), ("HO2", "27", O), ("HB2", "26", P), ("SW2", "25", P), ("IMONOUT", "6", O),
     ("nFLT", "7", O), ("HO1_LL", "8", O), ("HO2_LL", "9", O),
     ("NC", "2", "no_connect"), ("NC", "5", "no_connect"), ("NC", "21", "no_connect"), ("NC", "24", "no_connect"),
     ("NC", "28", "no_connect"), ("NC", "33", "no_connect")])

cais3062 = symbol("CA-IS3062VW", "U", "Chipanalog isolated CAN transceiver with integrated 5 V DC-DC, SOIC16-WB, separate VCCL logic supply (datasheet v1.04 table 6-1)",
    "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm",
    [("VCC", "1", W), ("VCCL", "7", W), ("GND1", "2", W), ("GND1", "8", W), ("TXD", "3", I), ("RXD", "5", O),
     ("NC", "4", "no_connect"), ("NC", "6", "no_connect"), ("NC", "14", "no_connect")],
    [("VISO", "11", P), ("VISO", "16", P), ("CANH", "13", B), ("CANL", "12", B),
     ("GND2", "9", W), ("GND2", "10", W), ("GND2", "15", W)])

qn = symbol("Q_NMOS_PWR", "Q", "N-channel power MOSFET, TDSON-8 / LFPAK56 pad order: 1-3 source, 4 gate, 5 drain",
    "Package_TO_SOT_SMD:TDSON-8-1",
    [("G", "4", P)], [("D", "5", P), ("S", "1", P), ("S", "2", P), ("S", "3", P)], pitch=2.54)

body = "\t" + open(os.path.join(HERE, "ca3092w_symbol.txt")).read().rstrip()
txt = ('(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "mppt_controller")\n\t(generator_version "1.0")\n'
       + body + "\n" + lm5177 + "\n" + cais3062 + "\n" + qn + "\n)\n")
open(os.path.join(HERE, "mppt_custom.kicad_sym"), "w").write(txt)
print("wrote mppt_custom.kicad_sym")
