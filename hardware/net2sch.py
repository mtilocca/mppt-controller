#!/usr/bin/env python3
"""
net2sch -- build a label-only hierarchical KiCad schematic from a KiCad netlist (.net).

Every pin gets a short stub and a net label, no routed wires, so the drawing can never merge nets
that the netlist keeps apart. Symbols are copied from the KiCad symbol libraries.

Usage: python net2sch.py mppt_controller.net [out_dir]
"""
import glob
import os
import re
import sys
import uuid
from collections import defaultdict

GRID = 1.27
STUB = 2.54
# Power flags: nets that only have power-input pins (no power output) need one for ERC.
FLAG_NETS = ["AUX_VIN", "GND", "3V3", "5V", "3V3A", "VAUX", "VBUS", "ISO_GND", "CAN_GND", "PV_F", "BAT_F", "BAT_BUS", "VIN_PWR"]
SHEET_ORDER = ["pv_input", "mppt_stage", "mppt_loop", "battery", "load_switch", "inverter_feed", "sensing", "aux_power", "mcu", "flash", "ethernet", "can", "rs485", "usb_uart", "display", "leds"]
PAPERS = [("A4", 297, 210), ("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594), ("A0", 1189, 841)]


# ---------------------------------------------------------------- s-expression handling
class Q(str):
    """A quoted string."""


def tokenize(s):
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t\r\n":
            i += 1
        elif c in "()":
            yield c
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while s[j] != '"':
                if s[j] == "\\":
                    j += 1
                buf.append(s[j])
                j += 1
            yield Q("".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and s[j] not in ' \t\r\n()"':
                j += 1
            yield s[i:j]
            i = j


def parse(s):
    stack, cur = [], []
    for t in tokenize(s):
        if t == "(" and not isinstance(t, Q):
            stack.append(cur)
            cur = []
        elif t == ")" and not isinstance(t, Q):
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(t)
    return cur[0] if len(cur) == 1 else cur


def dump(node, depth=0):
    if isinstance(node, Q):
        return '"' + node.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(node, str):
        return node
    inner = [dump(x, depth + 1) for x in node]
    if all(not isinstance(x, list) for x in node):
        return "(" + " ".join(inner) + ")"
    pad = "\t" * (depth + 1)
    head = [dump(x, depth + 1) for x in node if not isinstance(x, list)]
    body = [dump(x, depth + 1) for x in node if isinstance(x, list)]
    return "(" + " ".join(head) + "\n" + "\n".join(pad + b for b in body) + "\n" + "\t" * depth + ")"


def child(node, key):
    for x in node[1:]:
        if isinstance(x, list) and x and x[0] == key:
            return x
    return None


# ---------------------------------------------------------------- symbol libraries
def find_sym_dir():
    for env in ("KICAD10_SYMBOL_DIR", "KICAD_SYMBOL_DIR"):
        if os.environ.get(env):
            return os.environ[env]
    hits = glob.glob(os.path.expanduser(
        "~/.local/share/flatpak/runtime/org.kicad.KiCad.Library.Symbols/*/stable/active/files/symbols"))
    if hits:
        return hits[0]
    raise SystemExit("KiCad symbol library directory not found (set KICAD10_SYMBOL_DIR)")


_lib_text = {}
LIB_VERSION = ["20250114"]


def lib_source(lib):
    if lib not in _lib_text:
        local = os.path.join(os.path.dirname(os.path.abspath(__file__)), lib + ".kicad_sym")
        path = local if os.path.exists(local) else os.path.join(find_sym_dir(), lib + ".kicad_sym")
        with open(path, encoding="utf-8") as f:
            _lib_text[lib] = f.read()
        m = re.search(r"\(version (\d+)\)", _lib_text[lib][:300])
        if m:
            LIB_VERSION[0] = m.group(1)
    return _lib_text[lib]


# Pins whose KiCad ERC type is wrong for this design (they are driven by resistors/caps or by an internal regulator):
# symbol name -> pin numbers forced to "passive" in the copy embedded in the schematic.
PASSIVE_PINS = {
    "LM5069MM-1": {"6", "7"},          # TIMER, PWR (set by a capacitor / resistor)
    "TPS54360DDA": {"1", "2"},         # BOOT (capacitor), VIN (fed through a ferrite)
    "LAN8720A": {"6"},                 # VDDCR (output of the internal 1.2 V regulator, decoupling only)
    "STM32H743ZITx": {"71", "106"},    # VCAP (outputs of the internal LDO)
}


def force_passive(text, name):
    import re as _re
    for num in PASSIVE_PINS.get(name, ()):
        text = _re.sub(r'\(pin \w+ (\w+)((?:(?!\(pin ).)*?\(number "' + num + r'")', lambda m: "(pin passive " + m.group(1) + m.group(2), text, count=1, flags=_re.S)
    return text


def extract_symbol(lib, name):
    return force_passive(_extract_symbol(lib, name), name)


def _extract_symbol(lib, name):
    text = lib_source(lib)
    m = re.search(r'\n\t\(symbol "' + re.escape(name) + r'"', text)
    if not m:
        raise SystemExit(f"symbol {lib}:{name} not found")
    start = m.start() + 2
    depth, i, in_str = 0, start, False
    while True:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1


def load_symbol(lib, name):
    """Parsed, flattened symbol tree (no 'extends')."""
    tree = parse(extract_symbol(lib, name))
    ext = child(tree, "extends")
    if not ext:
        return tree
    parent = load_symbol(lib, str(ext[1]))
    pname = str(ext[1])
    new = [parent[0], Q(name)]
    for item in parent[2:]:
        if isinstance(item, list) and item[0] == "symbol":
            item = [item[0], Q(re.sub("^" + re.escape(pname) + "_", name + "_", str(item[1])))] + item[2:]
        new.append(item)
    for prop in tree[2:]:
        if isinstance(prop, list) and prop[0] == "property":
            for k, old in enumerate(new):
                if isinstance(old, list) and old[0] == "property" and old[1] == prop[1]:
                    new[k] = prop
                    break
            else:
                new.append(prop)
    return new


class Sym:
    def __init__(self, lib, name):
        self.lib, self.name = lib, name
        self.tree = load_symbol(lib, name)
        self.units = defaultdict(list)      # unit -> [(num, pname, x, y, angle)]
        for sub in self.tree[2:]:
            if not (isinstance(sub, list) and sub[0] == "symbol"):
                continue
            m = re.search(r"_(\d+)_(\d+)$", str(sub[1]))
            u, st = (int(m.group(1)), int(m.group(2))) if m else (0, 1)
            if st not in (0, 1):
                continue
            for p in sub[2:]:
                if isinstance(p, list) and p[0] == "pin":
                    at = child(p, "at")
                    self.units[u].append((str(child(p, "number")[1]), str(child(p, "name")[1]),
                                          float(at[1]), float(at[2]), int(float(at[3]))))
        real = sorted(u for u in self.units if u > 0)
        self.unit_ids = real or [1]

    def pins_for(self, unit):
        return self.units.get(0, []) + self.units.get(unit, [])

    def embedded(self):
        t = list(self.tree)
        t[1] = Q(f"{self.lib}:{self.name}")
        return t


# ---------------------------------------------------------------- netlist
def read_netlist(path):
    tree = parse(open(path, encoding="utf-8").read())
    comps = {}
    for c in child(tree, "components")[1:]:
        ref = str(child(c, "ref")[1])
        ls = child(c, "libsource")
        sp = child(c, "sheetpath")
        sheet = str(child(sp, "names")[1]).strip("/") if sp and child(sp, "names") else ""
        sheet = re.sub(r"_?\d+$", "", sheet) or "top"
        fpn = child(c, "footprint")
        comps[ref] = dict(ref=ref, value=str(child(c, "value")[1]),
                          footprint=str(fpn[1]) if fpn else "",
                          lib=str(child(ls, "lib")[1]), part=str(child(ls, "part")[1]), sheet=sheet)
    pin_net = {}
    net_sheets = defaultdict(set)
    for n in child(tree, "nets")[1:]:
        name = str(child(n, "name")[1])
        for nd in n[1:]:
            if isinstance(nd, list) and nd[0] == "node":
                ref, pin = str(child(nd, "ref")[1]), str(child(nd, "pin")[1])
                pin_net[(ref, pin)] = name
                net_sheets[name].add(comps[ref]["sheet"])
    return comps, pin_net, net_sheets


# ---------------------------------------------------------------- output helpers
def uid(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "/".join(map(str, parts))))


def f(v):
    r = round(round(v / GRID) * GRID, 4)
    return f"{r:g}"


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def ref_key(ref):
    m = re.match(r"([A-Za-z#]+)(\d+)", ref)
    order = "U Q L D F J SW R C JP TP".split()
    pre = m.group(1)
    return (order.index(pre) if pre in order else 99, int(m.group(2)))


def out_dir_dirs(pt):
    return pt


class Placed:
    pass


def plan_part(comp, sym, pin_net):
    """Return list of placed units with relative geometry and label extents."""
    placed = []
    for unit in sym.unit_ids:
        pins = sym.pins_for(unit)
        if not pins:
            continue
        xs = [p[2] for p in pins]
        ys = [p[3] for p in pins]
        ml = mr = mt = mb = 2.54 + 3
        for num, pname, x, y, a in pins:
            net = pin_net.get((comp["ref"], num))
            ext = 2.54 + 1.05 * (len(net) if net else 0) + 3
            out = (-1, 0) if a == 0 else (1, 0) if a == 180 else (0, 1) if a == 90 else (0, -1)
            if out == (-1, 0):
                ml = max(ml, ext)
            elif out == (1, 0):
                mr = max(mr, ext)
            elif out == (0, 1):
                mb = max(mb, ext)
            else:
                mt = max(mt, ext)
        mt += 6                                    # room for reference/value text
        pu = Placed()
        pu.unit, pu.pins = unit, pins
        pu.xmin, pu.xmax, pu.ymin, pu.ymax = min(xs), max(xs), min(ys), max(ys)
        pu.ml, pu.mr, pu.mt, pu.mb = ml, mr, mt, mb
        pu.w = pu.xmax - pu.xmin + ml + mr
        pu.h = pu.ymax - pu.ymin + mt + mb
        placed.append(pu)
    return placed


def label_sexp(kind, name, x, y, angle, key):
    just = "left" if angle in (0, 90) else "right"
    if kind == "global":
        return (f'(global_label "{esc(name)}" (shape passive) (at {f(x)} {f(y)} {angle}) '
                f'(effects (font (size 1.27 1.27)) (justify {just})) (uuid "{uid(key)}") '
                f'(property "Intersheetrefs" "${{INTERSHEET_REFS}}" (at {f(x)} {f(y)} 0) '
                f'(effects (font (size 1.27 1.27)) (hide yes))))')
    return (f'(label "{esc(name)}" (at {f(x)} {f(y)} {angle}) '
            f'(effects (font (size 1.27 1.27)) (justify {just})) (uuid "{uid(key)}"))')


def write_sheet(path, sheet, items, symbols, pin_net, net_sheets, root_uuid, sheet_uuid, project, flag_sym):
    # layout: shelf packing, rows by reference prefix
    for name, w, h in PAPERS:
        out = layout(items, symbols, pin_net, w - 30, h - 40)
        if out is not None:
            paper, cells, used_h = name, out, None
            break
    else:
        raise SystemExit(f"sheet {sheet}: does not fit on A0")
    lib_ids, body = set(), []
    for (comp, pu, cx, cy) in cells:
        sym = symbols[(comp["lib"], comp["part"])]
        lib_ids.add((comp["lib"], comp["part"]))
        ox = round((cx + pu.ml - pu.xmin) / GRID) * GRID
        oy = round((cy + pu.mt + pu.ymax) / GRID) * GRID
        ref, key = comp["ref"], f"{sheet}/{comp['ref']}/{pu.unit}"
        is_pwr = comp["ref"].startswith("#")
        tx = ox + (pu.xmin + pu.xmax) / 2
        props = [
            f'(property "Reference" "{esc(ref)}" (at {f(tx)} {f(cy + 2)} 0) (effects (font (size 1.27 1.27))))',
            f'(property "Value" "{esc(comp["value"])}" (at {f(tx)} {f(cy + 4.5)} 0) (effects (font (size 1.27 1.27))))',
            f'(property "Footprint" "{esc(comp["footprint"])}" (at {f(ox)} {f(oy)} 0) (effects (font (size 1.27 1.27)) (hide yes)))',
            f'(property "Datasheet" "" (at {f(ox)} {f(oy)} 0) (effects (font (size 1.27 1.27)) (hide yes)))',
        ]
        pins_s = "".join(f'\n\t\t(pin "{esc(p[0])}" (uuid "{uid(key, "pin", p[0])}"))' for p in pu.pins)
        body.append(
            f'\t(symbol (lib_id "{comp["lib"]}:{comp["part"]}") (at {f(ox)} {f(oy)} 0) (unit {pu.unit})\n'
            f'\t\t(exclude_from_sim no) (in_bom {"no" if is_pwr else "yes"}) (on_board {"no" if is_pwr else "yes"}) (dnp no)\n'
            f'\t\t(uuid "{uid(key)}")\n\t\t' + "\n\t\t".join(props) + pins_s + "\n"
            f'\t\t(instances (project "{project}" (path "/{root_uuid}/{sheet_uuid}" '
            f'(reference "{esc(ref)}") (unit {pu.unit}))))\n\t)')
        for num, pname, x, y, a in pu.pins:
            net = pin_net.get((comp["ref"], num))
            px, py = ox + x, oy - y
            if not net:
                body.append(f'\t(no_connect (at {f(px)} {f(py)}) (uuid "{uid(key, "nc", num)}"))')
                continue
            dx, dy = (-1, 0) if a == 0 else (1, 0) if a == 180 else (0, 1) if a == 90 else (0, -1)
            ex, ey = px + dx * STUB, py + dy * STUB
            ang = {(1, 0): 0, (-1, 0): 180, (0, 1): 270, (0, -1): 90}[(dx, dy)]
            body.append(f'\t(wire (pts (xy {f(px)} {f(py)}) (xy {f(ex)} {f(ey)})) '
                        f'(stroke (width 0) (type default)) (uuid "{uid(key, "w", num)}"))')
            kind = "global" if len(net_sheets[net]) > 1 else "local"
            body.append("\t" + label_sexp(kind, net, ex, ey, ang, f"{key}/l/{num}"))
    libsyms = "\n".join("\t\t" + dump(symbols[k].embedded(), 2) for k in sorted(lib_ids))
    text = (f'(kicad_sch\n\t(version {LIB_VERSION[0]})\n\t(generator "net2sch")\n\t(generator_version "1.0")\n'
            f'\t(uuid "{sheet_uuid}")\n\t(paper "{paper}")\n'
            f'\t(title_block (title "{esc(sheet)}") (comment 1 "Generated by net2sch.py from the netlist: edit the generator (mppt_controller.py), not this file"))\n'
            f'\t(lib_symbols\n{libsyms}\n\t)\n' + "\n".join(body) + "\n\t(sheet_instances (path \"/\" (page \"1\")))\n)\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def layout(items, symbols, pin_net, max_w, max_h):
    cells, x, y, row_h, last_pre = [], 10.0, 15.0, 0.0, None
    for comp in items:
        sym = symbols[(comp["lib"], comp["part"])]
        pre = re.match(r"[A-Za-z#]+", comp["ref"]).group(0)
        for pu in plan_part(comp, sym, pin_net):
            if (x > 10.0 and x + pu.w > max_w) or (last_pre and pre != last_pre and x > 10.0):
                x, y, row_h = 10.0, y + row_h + 4, 0.0
            cells.append((comp, pu, x, y))
            x += pu.w + 2
            row_h = max(row_h, pu.h)
            last_pre = pre
    if y + row_h > max_h:
        return None
    return cells


def main(netfile, out_dir=None):
    out_dir = out_dir or os.path.dirname(os.path.abspath(netfile))
    project = os.path.splitext(os.path.basename(netfile))[0]
    comps, pin_net, net_sheets = read_netlist(netfile)

    # PWR_FLAG helpers (one per flagged net, placed in the sheet where the net is used)
    n_flag = 0
    for net in FLAG_NETS:
        if net in net_sheets:
            n_flag += 1
            ref = f"#FLG{n_flag:02d}"
            sheet = sorted(net_sheets[net])[0]
            comps[ref] = dict(ref=ref, value="PWR_FLAG", footprint="", lib="power", part="PWR_FLAG", sheet=sheet)
            pin_net[(ref, "1")] = net
            net_sheets[net].add(sheet)

    symbols = {}
    for c in comps.values():
        key = (c["lib"], c["part"])
        if key not in symbols:
            symbols[key] = Sym(*key)

    by_sheet = defaultdict(list)
    for c in comps.values():
        by_sheet[c["sheet"]].append(c)
    order = [s for s in SHEET_ORDER if s in by_sheet] + sorted(s for s in by_sheet if s not in SHEET_ORDER)

    root_uuid = uid("root", project)
    sheet_blocks, files = [], []
    for i, sheet in enumerate(order):
        items = sorted(by_sheet[sheet], key=lambda c: ref_key(c["ref"]))
        s_uuid = uid("sheet", sheet)
        fname = f"{project}_{sheet}.kicad_sch"
        write_sheet(os.path.join(out_dir, fname), sheet, items, symbols, pin_net, net_sheets,
                    root_uuid, s_uuid, project, None)
        files.append(fname)
        col, row = i % 3, i // 3
        sx, sy = 20 + col * 85, 30 + row * 30
        sheet_blocks.append(
            f'\t(sheet (at {f(sx)} {f(sy)}) (size 70 15)\n\t\t(stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0))\n'
            f'\t\t(uuid "{s_uuid}")\n'
            f'\t\t(property "Sheetname" "{sheet}" (at {f(sx)} {f(sy - 1)} 0) (effects (font (size 1.27 1.27)) (justify left bottom)))\n'
            f'\t\t(property "Sheetfile" "{fname}" (at {f(sx)} {f(sy + 16)} 0) (effects (font (size 1.27 1.27)) (justify left top)))\n'
            f'\t\t(instances (project "{project}" (path "/{root_uuid}" (page "{i + 2}"))))\n\t)')
    root = (f'(kicad_sch\n\t(version {LIB_VERSION[0]})\n\t(generator "net2sch")\n\t(generator_version "1.0")\n'
            f'\t(uuid "{root_uuid}")\n\t(paper "A4")\n'
            f'\t(title_block (title "MPPT charge controller (STM32H743, LM5177, 0-50 V PV, 12-48 V battery)") '
            f'(comment 1 "Label-only schematic generated from the netlist: nets connect by name between sheets"))\n'
            f'\t(lib_symbols)\n' + "\n".join(sheet_blocks) + '\n\t(sheet_instances (path "/" (page "1")))\n)\n')
    with open(os.path.join(out_dir, f"{project}.kicad_sch"), "w", encoding="utf-8") as fh:
        fh.write(root)
    pro = os.path.join(out_dir, f"{project}.kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w") as fh:
            fh.write('{\n  "meta": {\n    "filename": "%s.kicad_pro",\n    "version": 3\n  }\n}\n' % project)
    print(f"wrote {len(order)} sheets + root in {out_dir}: {', '.join(order)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
