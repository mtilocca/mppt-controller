#!/usr/bin/env python3
"""netdump.py NET [NET...]: pins on each net, from the KiCad netlist export (_kicad.xml)."""
import sys, xml.etree.ElementTree as ET, os
r = ET.parse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_kicad.xml")).getroot()
val = {c.get("ref"): (c.findtext("value") or "") for c in r.find("components")}
for n in r.find("nets"):
    if n.get("name").split("/")[-1] in sys.argv[1:] or any(a.endswith("*") and n.get("name").lstrip("/").startswith(a[:-1]) for a in sys.argv[1:]):
        print(n.get("name"), "->", "  ".join(f"{x.get('ref')}[{val.get(x.get('ref'),'')[:14]}].{x.get('pinfunction') or x.get('pin')}" for x in n.findall("node")))
