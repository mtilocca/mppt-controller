#!/usr/bin/env python3
"""Print pins of KiCad library symbols: pins.py Lib:Sym [...]"""
import re, sys, os, glob
SYM = glob.glob(os.path.expanduser("~/.local/share/flatpak/runtime/org.kicad.KiCad.Library.Symbols/*/stable/active/files/symbols"))[0]
def pins(lib, name):
    t = open(f"{SYM}/{lib}.kicad_sym").read()
    i = t.index(f'(symbol "{name}"')
    m = re.search(r'\n\t\(symbol "', t[i+10:])
    blk = t[i:i+10+m.start()] if m else t[i:]
    ext = re.search(r'\(extends "([^"]+)"', blk)
    if ext and "(pin " not in blk:
        return pins(lib, ext.group(1))
    return re.findall(r'\(pin (\w+) \w+.*?\(name "([^"]*)".*?\(number "([^"]*)"', blk, re.S)
if __name__ == "__main__":
    for a in sys.argv[1:]:
        lib, n = a.split(":")
        p = pins(lib, n)
        print(f"== {a} ({len(p)})")
        print("  ".join(f"{num}={nm}[{ty[:3]}]" for ty, nm, num in p))
