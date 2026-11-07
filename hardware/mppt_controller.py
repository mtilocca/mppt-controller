#!/usr/bin/env python3
"""
MPPT charge controller (STM32H743, LM5177 4-switch buck-boost) -- SKiDL netlist/schematic generator.

PV 0-50 V, battery 12-48 V nominal (58.5 V hardware charge cap), load + inverter DC feed with LM5069 hot-swap switches.
Run:  .venv/bin/python mppt_controller.py     (needs `pip install skidl`, KiCad 10 libraries, pinmap.json from pinmap.py)
Out:  mppt_controller.net and the label-only schematic (via net2sch.py)

Datasheet checks are asserted at the end: a wrong pin map stops the build.
Design values marked TUNE are starting points taken from the vendor reference design and must be tuned on the bench.
"""
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SYM = glob.glob(os.path.expanduser(
    "~/.local/share/flatpak/runtime/org.kicad.KiCad.Library.Symbols/*/stable/active/files/symbols"))
FPD = glob.glob(os.path.expanduser(
    "~/.local/share/flatpak/runtime/org.kicad.KiCad.Library.Footprints/*/stable/active/files/footprints"))
if SYM:
    for v in ("KICAD10_SYMBOL_DIR", "KICAD_SYMBOL_DIR"):
        os.environ.setdefault(v, SYM[0])

from skidl import Part, Net, Pin, Group, generate_netlist, ERC, lib_search_paths, KICAD  # noqa: E402

lib_search_paths[KICAD].append(HERE)        # mppt_custom.kicad_sym: LM5177, CA-IS3062VW, CA-IS3092W, Q_NMOS_PWR

PM = json.load(open(os.path.join(HERE, "pinmap.json")))      # STM32 pin allocation (pinmap.py)

_cur = [None]
_NETS = {}


def N(name):
    """Named net, created once: SKiDL's Net(name) makes a NEW net on every call."""
    if name not in _NETS:
        _NETS[name] = Net(name)
    return _NETS[name]


def section(name):
    """Start a hierarchical group so SKiDL places each block as its own sheet."""
    if _cur[0] is not None:
        _cur[0].__exit__(None, None, None)
    _cur[0] = Group(name)
    _cur[0].__enter__()


FP_DIR = FPD[0] if FPD else None
MISSING_FP = []


def fp(name):
    """Return a footprint 'Lib:Name', recording it if the file is not in the KiCad library."""
    if FP_DIR:
        lib, fn = name.split(":")
        if not os.path.exists(os.path.join(FP_DIR, lib + ".pretty", fn + ".kicad_mod")):
            MISSING_FP.append(name)
    return name


R0603 = "Resistor_SMD:R_0603_1608Metric"
R1206 = "Resistor_SMD:R_1206_3216Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
C1210 = "Capacitor_SMD:C_1210_3225Metric"
CPOL = "Capacitor_SMD:CP_Elec_10x10.5"
SHUNT = "Resistor_SMD:R_2512_6332Metric"
LED0603 = "LED_SMD:LED_0603_1608Metric"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
SOD123 = "Diode_SMD:D_SOD-123"
SMA = "Diode_SMD:D_SMA"
SMC = "Diode_SMD:D_SMC"
MSOP10 = "Package_SO:MSOP-10_3x3mm_P0.5mm"
TDSON = "Package_TO_SOT_SMD:TDSON-8-1"
TERM = "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-2-5.08_1x02_P5.08mm_Horizontal"
PINHDR = "Connector_PinHeader_2.54mm:PinHeader_1x{n:02d}_P2.54mm_Vertical"
BTN = "Button_Switch_SMD:SW_SPST_PTS645Sx43SMTR92"
SJ = "Jumper:SolderJumper-2_P1.3mm_Open_Pad1.0x1.5mm"


def R(value, foot=R0603):
    return Part("Device", "R", value=value, footprint=fp(foot))


def C(value, foot=C0603):
    return Part("Device", "C", value=value, footprint=fp(foot))


def cap_between(a, b, value, foot=C0603, n=1):
    for _ in range(n):
        c = C(value, foot)
        a += c[1]
        b += c[2]


def res_between(a, b, value, foot=R0603):
    r = R(value, foot=foot)
    a += r[1]
    b += r[2]
    return r


def led(net_from, colour, rv="1k"):
    d = Part("Device", "LED", value=colour, footprint=fp(LED0603))
    mid = N(net_from.name + "_A")
    res_between(net_from, mid, rv)
    mid += d["A"]
    return d


def header(nets, value, foot=None):
    n = len(nets)
    h = Part("Connector_Generic", f"Conn_01x{n:02d}", value=value, footprint=fp((foot or PINHDR).format(n=n)))
    for i, net in enumerate(nets, 1):
        net += h[i]
    return h


def tp(net, value="TP"):
    t = Part("Connector", "TestPoint", value=value, footprint=fp("TestPoint:TestPoint_Pad_D1.5mm"))
    net += t[1]


def nfet(drain, gate, source, value="BSC046N10NS3"):
    q = Part("mppt_custom", "Q_NMOS_PWR", value=value, footprint=fp(TDSON))
    drain += q["D"]
    gate += q["G"]
    source += q["S"]
    return q


def ina228(name, vin_p, vin_n, vbus, a1, a0, rfilt="10"):
    """INA228 across a high-side shunt. a1/a0 are nets (GND, V3, SDA or SCL)."""
    global V3, GND, SDA, SCL, ALERT
    u = Part("Sensor_Energy", "INA228", value=f"INA228 {name}", footprint=fp(MSOP10))
    p, n = N(f"{name}_SNS_P"), N(f"{name}_SNS_N")
    res_between(vin_p, p, rfilt)
    res_between(vin_n, n, rfilt)
    p += u["Vin+"]
    n += u["Vin-"]
    cap_between(p, n, "100n")
    vbus += u["Vbus"]
    V3 += u["VS"]
    GND += u["GND"]
    SDA += u["SDA"]
    SCL += u["SCL"]
    ALERT += u["~{Alert}"]
    a1 += u["A1"]
    a0 += u["A0"]
    cap_between(V3, GND, "100n")
    return u


# --------------------------------------------------------------------------------------
# Nets
# --------------------------------------------------------------------------------------
GND = N("GND")
V3, V5, VAUX = N("3V3"), N("5V"), N("VAUX")          # VAUX: 9 V from the battery bus (LM5177 BIAS, 5 V/3V3 bucks, fan)
V3A = N("3V3A")
VBUS_USB = N("VBUS")
SDA, SCL, ALERT = N("I2C_SDA"), N("I2C_SCL"), N("INA_ALERT")

PV_RAW, PV_F, PV_D = N("PV_RAW"), N("PV_F"), N("PV_D")   # terminal, after fuse+TVS, after ideal diode
VIN_PWR = N("VIN_PWR")                                       # converter input rail (after PV shunt)
VIN_CS = N("VIN_CS")                                         # after the LM5177 peak-current sense resistor
SW1, SW2 = N("SW1"), N("SW2")
VOUT = N("VOUT")                                             # converter output (before charge shunt)
BAT_RAW, BAT_F, BAT_NEG = N("BAT_RAW"), N("BAT_F"), N("BAT_NEG")
BAT_BUS = N("BAT_BUS")                                       # main battery bus: charger, load switch, inverter switch

# --------------------------------------------------------------------------------------
# 1. PV input: fuse, TVS, ideal diode (blocks battery back-feed because the LM5177 is bidirectional), PV shunt
# --------------------------------------------------------------------------------------
section("pv_input")
j_pv = Part("Connector", "Screw_Terminal_01x02", value="J_PV (+, -)", footprint=fp(TERM))
j_pv[1] += PV_RAW
j_pv[2] += GND
f_pv = Part("Device", "Fuse", value="15A blade", footprint=fp("Fuse:Fuseholder_Blade_Mini_Keystone_3568"))
PV_RAW += f_pv[1]
PV_F += f_pv[2]
tvs_pv = Part("Device", "D", value="SMCJ51A", footprint=fp(SMC))      # Vwm 51 V, clamp 82 V < LM5177 VIN abs max 85 V
PV_F += tvs_pv["K"]
GND += tvs_pv["A"]
# LM74700 ideal diode: ANODE = FET source (input), CATHODE = FET drain (load). EN tied to ANODE (always on).
u_pvd = Part("Power_Management", "LM74700", value="LM74700-Q1", footprint=fp("Package_TO_SOT_SMD:SOT-23-6"))
q_pvd = nfet(PV_D, N("PVD_GATE"), PV_F, value="100V NFET (BSC046N10NS3)")
PV_F += u_pvd["ANODE"], u_pvd["EN"]
PV_D += u_pvd["CATHODE"]
N("PVD_GATE").__iadd__((u_pvd["GATE"]))
GND += u_pvd["GND"]
N("PVD_VCAP").__iadd__(u_pvd["VCAP"])
cap_between(N("PVD_VCAP"), PV_F, "100n", C0805)
cap_between(PV_F, GND, "10u", C1210, n=2)
rs_pv = Part("Device", "R", value="2m 1% 3W", footprint=fp(SHUNT))      # PV current shunt (15 A -> 30 mV)
PV_D += rs_pv[1]
VIN_PWR += rs_pv[2]
tp(PV_F, "TP_PV_F")

# --------------------------------------------------------------------------------------
# 2. LM5177 power stage
# --------------------------------------------------------------------------------------
section("mppt_stage")
u1 = Part("mppt_custom", "LM5177", value="LM5177", footprint=fp("Package_SO:HTSSOP-38-1EP_4.4x9.7mm_P0.5mm_EP2.74x4.75mm"))
EN_MPPT, VCC, FB = N("MPPT_EN_UVLO"), N("LM5177_VCC"), N("LM5177_FB")
SS, COMP, MPPT_NFLT = N("LM5177_SS"), N("LM5177_COMP"), N("MPPT_NFLT")
IMON = N("LM5177_IMON")

# input bulk, current sense (peak), half bridges
for _ in range(2):
    c = Part("Device", "C_Polarized", value="150u 80V", footprint=fp(CPOL))
    VIN_PWR += c[1]
    GND += c[2]
cap_between(VIN_PWR, GND, "10u 100V", C1210, n=2)
rcs = Part("Device", "R", value="2m 1% 3W (RCS, 2x 4m parallel)", footprint=fp(SHUNT))
VIN_PWR += rcs[1]
VIN_CS += rcs[2]
cap_between(VIN_CS, GND, "10u 100V", C1210, n=4)
cap_between(VIN_CS, GND, "100n 100V", C0805, n=2)
q1 = nfet(VIN_CS, N("HO1_G"), SW1, "Q1 100V")
q2 = nfet(SW1, N("LO1_G"), GND, "Q2 100V")
q3 = nfet(VOUT, N("HO2_G"), SW2, "Q3 100V")
q4 = nfet(SW2, N("LO2_G"), GND, "Q4 100V")
for gate, pin in (("HO1_G", "HO1"), ("LO1_G", "LO1"), ("HO2_G", "HO2"), ("LO2_G", "LO2")):
    gnet = N(gate + "_IC")
    gnet += u1[pin]
    res_between(gnet, N(gate), "2.2")
l1 = Part("Device", "L", value="10u 32A Isat, DCR<=4m", footprint=fp("Inductor_THT:L_Toroid_Vertical_L24.6mm_W15.5mm_P11.44mm_Pulse_KM-4"))
SW1 += l1[1]
SW2 += l1[2]
# bootstrap
cap_between(N("HB1"), SW1, "100n 35V", C0603)
cap_between(N("HB2"), SW2, "100n 35V", C0603)
N("HB1").__iadd__((u1["HB1"]))
N("HB2").__iadd__((u1["HB2"]))
SW1 += u1["SW1"]
SW2 += u1["SW2"]
# output side
for _ in range(2):
    c = Part("Device", "C_Polarized", value="150u 80V", footprint=fp(CPOL))
    VOUT += c[1]
    GND += c[2]
cap_between(VOUT, GND, "10u 100V", C1210, n=4)
cap_between(VOUT, GND, "100n 100V", C0805, n=2)
# charge shunt: also the LM5177 current-limiter sense (4 mOhm -> about 11-12 A limit with 45-50 mV threshold)
rs_chg = Part("Device", "R", value="4m 1% 3W (RISNS)", footprint=fp(SHUNT))
VOUT += rs_chg[1]
BAT_BUS += rs_chg[2]
VOUT += u1["ISNSP"], u1["VOUT"]
BAT_BUS += u1["ISNSN"]
# peak-current sense filter (datasheet: 10 ohm + CDIFF)
for src, pin in ((VIN_PWR, "CSA"), (VIN_CS, "CSB")):
    mid = N("CS_" + pin)
    res_between(src, mid, "10")
    mid += u1[pin]
cap_between(N("CS_CSA"), N("CS_CSB"), "180p")
# supply
VIN_PWR += u1["VIN"]
cap_between(VIN_PWR, GND, "1u 100V", C0805)
VAUX += u1["BIAS"]
cap_between(VAUX, GND, "1u 25V", C0603)
VCC += u1["VCC"]
cap_between(VCC, GND, "47u 10V", C1206)
GND += u1["PGND"], u1["AGND"], u1["PAD"]
# enable / UVLO (start about 12 V) and MCU disable (gate pulled up -> converter disabled until the MCU releases it)
res_between(VIN_PWR, EN_MPPT, "90.9k")
res_between(EN_MPPT, GND, "10k")
EN_MPPT += u1["EN/UVLO"]
q_en = Part("Transistor_FET", "2N7002", value="2N7002", footprint=fp(SOT23))
EN_MPPT += q_en["D"]
GND += q_en["S"]
MPPT_NEN = N("MPPT_NEN")                 # MCU: low = converter allowed to run (reset/boot state = high = off)
q_en["G"] += MPPT_NEN
res_between(MPPT_NEN, V3, "10k")
# configuration: CFG 36.5k = DRSS on, hiccup SCP on, PSM threshold 15 %, current limit on (Table 7-1, row 16)
res_between(u1["CFG"], GND, "36.5k")
res_between(u1["RT"], GND, "200k")          # fsw about 151 kHz (RRT = (1/fsw - 20 ns) x 30.3 GOhm)
res_between(u1["SLOPE"], GND, "200k")       # RSLOPE = 50e6 x L/RCS x 0.8 for L = 10 uH, RCS = 2 mOhm
SYNC, MODE = N("LM5177_SYNC"), N("LM5177_MODE")
SYNC += u1["SYNC"]
res_between(SYNC, VCC, "100k")              # high at enable = positive current-limit direction (charging)
MODE += u1["MODE"]
res_between(MODE, GND, "100k")              # PSM: no reverse inductor current (the PV side is blocked by the ideal diode)
jp_fpwm = Part("Jumper", "SolderJumper_2_Open", value="JP_FPWM", footprint=fp(SJ))
MODE += jp_fpwm["A"]
VCC += jp_fpwm["B"]
GND += u1["DTRK"]
# current-limiter loop network on IMONOUT (TI example, TUNE)
IMON += u1["IMONOUT"]
mid = N("IMON_RC")
res_between(IMON, mid, "82k")
cap_between(mid, GND, "2.2n")
# soft start / analog output tracking: DAC CV target through 1k, 18 nF soft-start cap
SS += u1["SS/ATRK"]
cap_between(SS, GND, "18n 50V")
res_between(SS, N("DAC_CV"), "1k")
# error amp compensation (TI example values, TUNE for L = 10 uH / larger COUT)
COMP += u1["COMP"]
mid = N("COMP_RC")
res_between(COMP, mid, "1.91k")
cap_between(mid, GND, "47n")
cap_between(COMP, GND, "1.8n")
# output divider: 71.5k / 1.24k -> 58.66 V hardware cap
FB += u1["FB"]
res_between(VOUT, FB, "71.5k")
res_between(FB, GND, "1.24k 0.1%")
cap_between(FB, GND, "10p")
# fault output
MPPT_NFLT += u1["nFLT"]
res_between(MPPT_NFLT, V3, "10k")
tp(VOUT, "TP_VOUT")
tp(SW1, "TP_SW1")
tp(SW2, "TP_SW2")
tp(COMP, "TP_COMP")

# --------------------------------------------------------------------------------------
# 3. MPPT input-voltage loop: op-amp pulls COMP down through a Schottky when VIN_PWR falls below the DAC target
# --------------------------------------------------------------------------------------
section("mppt_loop")
u_oa = Part("Amplifier_Operational", "TLV9061xDBV", value="TLV9061", footprint=fp("Package_TO_SOT_SMD:SOT-23-5"))
VPV_DIV, VMPP_REF, OA_OUT = N("VPV_DIV"), N("DAC_VMPP"), N("MPPT_OA_OUT")
res_between(VIN_PWR, VPV_DIV, "301k 0.1%")
res_between(VPV_DIV, GND, "10k 0.1%")
cap_between(VPV_DIV, GND, "22n")
VPV_DIV += u_oa[3]
vref_n = N("MPPT_REF_N")
res_between(VMPP_REF, vref_n, "10k")
cap_between(VMPP_REF, GND, "100n")
vref_n += u_oa[4]
fb_mid = N("MPPT_FB_MID")
res_between(OA_OUT, fb_mid, "100k")        # PI error amp: Rf + Cf (TUNE by simulation/bench)
cap_between(fb_mid, vref_n, "1n")
OA_OUT += u_oa[1]
V5 += u_oa[5]
GND += u_oa[2]
cap_between(V5, GND, "100n")
d_comp = Part("Device", "D_Schottky", value="BAT54", footprint=fp(SOD123))
COMP += d_comp["A"]
OA_OUT += d_comp["K"]
tp(OA_OUT, "TP_MPPT_OA")

# --------------------------------------------------------------------------------------
# 4. Battery: terminal, fuse, TVS, low-side reverse-polarity FETs, battery shunt
# --------------------------------------------------------------------------------------
section("battery")
j_bat = Part("Connector", "Screw_Terminal_01x02", value="J_BAT (+, -)", footprint=fp(TERM))
j_bat[1] += BAT_RAW
j_bat[2] += BAT_NEG
f_bat = Part("Device", "Fuse", value="30A blade", footprint=fp("Fuse:Fuseholder_Blade_ATO_Littelfuse_Pudenz_2_Pin"))
BAT_RAW += f_bat[1]
BAT_F += f_bat[2]
tvs_bat = Part("Device", "D", value="SMCJ58A", footprint=fp(SMC))
BAT_F += tvs_bat["K"]
GND += tvs_bat["A"]
# low-side N-FETs: drain to the battery negative terminal, source to system GND, gate pulled up to the battery positive
RP_GATE = N("BAT_RP_GATE")
for i in (1, 2):
    nfet(BAT_NEG, RP_GATE, GND, value=f"Q_RP{i} 100V")
res_between(BAT_F, RP_GATE, "47k", R1206)
z_rp = Part("Device", "D_Zener", value="BZT52C12 12V", footprint=fp(SOD123))
RP_GATE += z_rp["K"]
GND += z_rp["A"]
rs_bat = Part("Device", "R", value="2m 1% 3W", footprint=fp(SHUNT))     # battery current, bidirectional
BAT_F += rs_bat[1]
BAT_BUS += rs_bat[2]
for _ in range(2):
    c = Part("Device", "C_Polarized", value="150u 80V", footprint=fp(CPOL))
    BAT_BUS += c[1]
    GND += c[2]
cap_between(BAT_BUS, GND, "10u 100V", C1210, n=2)
tp(BAT_BUS, "TP_BAT_BUS")
tp(BAT_F, "TP_BAT_F")

# --------------------------------------------------------------------------------------
# 5. Load and inverter feed: LM5069 hot-swap switches (current limit, power limit, inrush control, fault timer)
# --------------------------------------------------------------------------------------
LOAD_OUT, INV_OUT = N("LOAD_OUT"), N("INV_OUT")


def hot_swap(tag, out_net, nen_net, pgd_net, lim_value="3m"):
    """LM5069MM-1 (latch off after a fault) high-side switch from BAT_BUS to out_net."""
    global BAT_BUS, GND, V3
    sec = N(f"{tag}_SENSE")
    u = Part("Power_Management", "LM5069MM-1", value="LM5069-1", footprint=fp(MSOP10))
    rs = Part("Device", "R", value=f"{lim_value} 1% 3W (50 mV = 17 A limit)", footprint=fp(SHUNT))
    BAT_BUS += rs[1]
    sec += rs[2]
    BAT_BUS += u["VIN"]
    sec += u["SENSE"]
    gate = N(f"{tag}_GATE")
    q = nfet(sec, N(f"{tag}_QG"), out_net, value=f"Q_{tag} 100V")
    res_between(gate, N(f"{tag}_QG"), "10")
    gate += u["GATE"]
    out_net += u["OUT"]
    GND += u["GND"]
    res_between(N(f"{tag}_PWR"), GND, "150k")           # TUNE: power limit (SOA)
    N(f"{tag}_PWR").__iadd__((u["PWR"]))
    cap_between(N(f"{tag}_TIMER"), GND, "470n")         # TUNE: fault time-out about 22 ms
    N(f"{tag}_TIMER").__iadd__((u["TIMER"]))
    # UVLO about 9.7 V on, OVLO about 63 V off (2.5 V thresholds)
    uv = N(f"{tag}_UVLO")
    res_between(BAT_BUS, uv, "309k")
    res_between(uv, GND, "105k")
    uv += u["UVLO"]
    ov = N(f"{tag}_OVLO")
    res_between(BAT_BUS, ov, "453k")
    res_between(ov, GND, "18.2k")
    ov += u["OVLO"]
    # MCU control: NFET pulls UVLO low (switch off); gate pulled up so reset/boot = off
    qc = Part("Transistor_FET", "2N7002", value="2N7002", footprint=fp(SOT23))
    uv += qc["D"]
    GND += qc["S"]
    nen_net += qc["G"]
    res_between(nen_net, V3, "10k")
    pgd_net += u["PGD"]
    res_between(pgd_net, V3, "100k")
    z = Part("Device", "D_Zener", value="BZT52C15 15V", footprint=fp(SOD123))   # gate-source protection
    N(f"{tag}_QG").__iadd__((z["K"]))
    out_net += z["A"]
    cap_between(out_net, GND, "10u 100V", C1210, n=2)
    return u, rs


section("load_switch")
LOAD_NEN, LOAD_PGD = N("LOAD_NEN"), N("LOAD_PGD")
u_load, rs_load = hot_swap("LOAD", LOAD_OUT, LOAD_NEN, LOAD_PGD)
j_load = Part("Connector", "Screw_Terminal_01x02", value="J_LOAD (+, -)", footprint=fp(TERM))
j_load[1] += LOAD_OUT
j_load[2] += GND
tvs_load = Part("Device", "D", value="SMCJ58A", footprint=fp(SMC))
LOAD_OUT += tvs_load["K"]
GND += tvs_load["A"]
tp(LOAD_OUT, "TP_LOAD_OUT")

section("inverter_feed")
INV_NEN, INV_PGD = N("INV_NEN"), N("INV_PGD")
u_inv, rs_inv = hot_swap("INV", INV_OUT, INV_NEN, INV_PGD)
j_inv = Part("Connector", "Screw_Terminal_01x02", value="J_INV DC (+, -)", footprint=fp(TERM))
j_inv[1] += INV_OUT
j_inv[2] += GND
tvs_inv = Part("Device", "D", value="SMCJ58A", footprint=fp(SMC))
INV_OUT += tvs_inv["K"]
GND += tvs_inv["A"]
# control port to the external 220 V inverter: dry-contact remote ON/OFF out, optocoupled fault/status in
INV_REMOTE, INV_FAULT = N("INV_REMOTE"), N("INV_FAULT")
INV_RC_A, INV_RC_B = N("INV_REMOTE_A"), N("INV_REMOTE_B")
u_oc1 = Part("Isolator", "PC817", value="PC817", footprint=fp("Package_DIP:SMDIP-4_W9.53mm"))
res_between(INV_REMOTE, N("INV_REMOTE_LED"), "330")
u_oc1[1] += N("INV_REMOTE_LED")
u_oc1[2] += GND
u_oc1[4] += INV_RC_A
u_oc1[3] += INV_RC_B
INV_FIN_A, INV_FIN_K = N("INV_STATUS_P"), N("INV_STATUS_N")
u_oc2 = Part("Isolator", "PC817", value="PC817", footprint=fp("Package_DIP:SMDIP-4_W9.53mm"))
res_between(INV_FIN_A, N("INV_STATUS_LED"), "2.2k")
u_oc2[1] += N("INV_STATUS_LED")
u_oc2[2] += INV_FIN_K
u_oc2[4] += INV_FAULT
u_oc2[3] += GND
res_between(INV_FAULT, V3, "10k")
j_invctl = header([INV_RC_A, INV_RC_B, INV_FIN_A, INV_FIN_K], "J_INV_CTL (REMOTE A/B, STATUS +/- 5-24 V)",
                  "TerminalBlock_Phoenix:TerminalBlock_Phoenix_PT-1,5-4-3.5-H_1x04_P3.50mm_Horizontal")
tp(INV_OUT, "TP_INV_OUT")

# --------------------------------------------------------------------------------------
# 6. Current/voltage monitors (INA228 x5 on one I2C bus; addresses 0x40..0x44)
# --------------------------------------------------------------------------------------
section("sensing")
ina228("PV", PV_D, VIN_PWR, VIN_PWR, GND, GND)             # 0x40
ina228("CHG", VOUT, BAT_BUS, BAT_BUS, GND, V3)              # 0x41 (charge current, shares the LM5177 ISNS shunt)
ina228("BAT", BAT_F, BAT_BUS, BAT_BUS, GND, SDA)            # 0x42 (battery current, bidirectional)
ina228("LOAD", BAT_BUS, N("LOAD_SENSE"), LOAD_OUT, GND, SCL)       # 0x43
ina228("INV", BAT_BUS, N("INV_SENSE"), INV_OUT, V3, GND)           # 0x44
res_between(SDA, V3, "2.2k")
res_between(SCL, V3, "2.2k")
res_between(ALERT, V3, "10k")
# external DAC: Vmpp setpoint and CV target (default outputs after power-up are safe: converter held off by MPPT_NEN)
u_dac = Part("Analog_DAC", "MCP4728", value="MCP4728", footprint=fp("Package_SO:MSOP-10_3x3mm_P0.5mm"))
V3 += u_dac["VDD"]
GND += u_dac["VSS"]
GND += u_dac["~{LDAC}"]
SDA += u_dac["SDA"]
SCL += u_dac["SCL"]
N("DAC_VMPP").__iadd__((u_dac["VOUTA"]))
N("DAC_CV").__iadd__((u_dac["VOUTB"]))
N("DAC_SPARE_C").__iadd__((u_dac["VOUTC"]))
N("DAC_SPARE_D").__iadd__((u_dac["VOUTD"]))
cap_between(V3, GND, "100n")
cap_between(V3, GND, "10u", C0805)
tp(N("DAC_SPARE_C"), "TP_DAC_C")
tp(N("DAC_SPARE_D"), "TP_DAC_D")
# redundant ADC voltage dividers (60 V full scale -> 1.93 V) and NTCs
VPV_ADC, VBAT_ADC, VLOAD_ADC = N("ADC_VPV"), N("ADC_VBAT"), N("ADC_VLOAD")
for src, adc in ((VIN_PWR, VPV_ADC), (BAT_BUS, VBAT_ADC), (LOAD_OUT, VLOAD_ADC)):
    res_between(src, adc, "301k 0.1%")
    res_between(adc, GND, "10k 0.1%")
    cap_between(adc, GND, "100n")
for nm in ("NTC_PWR", "NTC_BAT", "NTC_AUX"):
    adc = N("ADC_" + nm)
    res_between(V3A, adc, "10k 1%")
    cap_between(adc, GND, "100n")
    if nm == "NTC_BAT":
        header([adc, GND], "J_NTC_BAT (external 10k NTC)")
    else:
        ntc = Part("Device", "Thermistor_NTC", value="10k NTC", footprint=fp(R0603))
        adc += ntc[1]
        GND += ntc[2]

# --------------------------------------------------------------------------------------
# 7. Auxiliary power: bus -> 9 V (TPS54360) -> 5 V (AP63205) and 3.3 V (AP63203)
# --------------------------------------------------------------------------------------
section("aux_power")
u_aux = Part("Regulator_Switching", "TPS54360DDA", value="TPS54360", footprint=fp("Package_SO:HSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.1mm"))
AUX_VIN, AUX_SW, AUX_FB, AUX_EN = N("AUX_VIN"), N("AUX_SW"), N("AUX_FB"), N("AUX_EN")
fb_aux = N("AUX_COMP")
ferrite = Part("Device", "FerriteBead", value="600R 3A", footprint=fp("Inductor_SMD:L_1206_3216Metric"))
BAT_BUS += ferrite[1]
AUX_VIN += ferrite[2]
AUX_VIN += u_aux["VIN"]
cap_between(AUX_VIN, GND, "2.2u 100V", C1210, n=2)
cap_between(AUX_VIN, GND, "100n 100V", C0805)
# EN divider: start about 9.5 V, stop about 7.5 V (R1 523k hysteresis from the TI example scaled)
res_between(AUX_VIN, AUX_EN, "845k")
res_between(AUX_EN, GND, "162k")
AUX_EN += u_aux["EN"]
res_between(u_aux["RT/CLK"], GND, "200k")                   # about 500 kHz
cap_between(N("AUX_BOOT"), AUX_SW, "100n")
N("AUX_BOOT").__iadd__((u_aux["BOOT"]))
AUX_SW += u_aux["SW"]
d_aux = Part("Device", "D_Schottky", value="B560C 60V 5A", footprint=fp(SMC))
AUX_SW += d_aux["K"]
GND += d_aux["A"]
l_aux = Part("Device", "L", value="33u 3A Isat", footprint=fp("Inductor_SMD:L_Bourns_SRP1245A"))
AUX_SW += l_aux[1]
VAUX_RAW = N("VAUX_RAW")                                    # TPS54360 output, before the OR-ing diodes
VAUX_RAW += l_aux[2]
cap_between(VAUX_RAW, GND, "22u 25V", C1210, n=3)
res_between(VAUX_RAW, AUX_FB, "110k")                       # 0.8 V x (1 + 110k/10.2k) = 9.45 V, about 9.1 V after the diode
d_or_bat = Part("Device", "D_Schottky", value="SS14", footprint=fp(SMA))
VAUX_RAW += d_or_bat["A"]
VAUX += d_or_bat["K"]                                       # blocks back-feed into the TPS54360 / battery bus in USB-only mode
cap_between(VAUX, GND, "10u 25V", C1206, n=2)
res_between(AUX_FB, GND, "10.2k")
AUX_FB += u_aux["FB"]
cap_between(AUX_FB, VAUX_RAW, "39p")
mid = N("AUX_COMP_RC")
res_between(u_aux["COMP"], mid, "13k")
cap_between(mid, GND, "6800p")
cap_between(u_aux["COMP"], GND, "39p")
GND += u_aux["GND"], u_aux["GNDPAD"]


def ap_buck(name, symname, outnet, label):
    global VAUX, GND
    u = Part("Regulator_Switching", symname, value=symname, footprint=fp("Package_TO_SOT_SMD:TSOT-23-6"))
    VAUX += u["IN"]
    VAUX += u["EN"]
    GND += u["GND"]
    sw = N(name + "_SW")
    sw += u["SW"]
    cap_between(N(name + "_BST"), sw, "100n")
    N(name + "_BST").__iadd__((u["BST"]))
    l = Part("Device", "L", value="4.7u 3A", footprint=fp("Inductor_SMD:L_Bourns_SRP5030T"))
    sw += l[1]
    outnet += l[2]
    outnet += u["FB"]
    cap_between(outnet, GND, "22u 10V", C1206, n=2)
    cap_between(VAUX, GND, "10u 25V", C1206)
    return u


ap_buck("B5", "AP63205WU", V5, "5V")
ap_buck("B3", "AP63203WU", V3, "3V3")
fb3 = Part("Device", "FerriteBead", value="600R", footprint=fp("Inductor_SMD:L_0603_1608Metric"))
V3 += fb3[1]
V3A += fb3[2]
cap_between(V3A, GND, "10u", C0805)
cap_between(V3A, GND, "100n")
for n_, v in ((VAUX, "TP_9V"), (V5, "TP_5V"), (V3, "TP_3V3")):
    tp(n_, v)

# --------------------------------------------------------------------------------------
# 8. STM32H743ZIT6 (LQFP-144)
# --------------------------------------------------------------------------------------
section("mcu")
mcu = Part("MCU_ST_STM32H7", "STM32H743ZITx", value="STM32H743ZIT6", footprint=fp("Package_QFP:LQFP-144_20x20mm_P0.5mm"))


def mp(label):
    """MCU pin by function label from pinmap.json (addressed by LQFP-144 pin number)."""
    return mcu[PM[label]["lqfp"]]


_SIG_DONE = set()


def sig(label):
    """Net named after an STM32 signal, with its pin attached (once)."""
    n = N(label)
    if label not in _SIG_DONE:
        _SIG_DONE.add(label)
        n += mp(label)
    return n


V3 += mcu["VDD"], mcu["VBAT"], mcu["VDD33_USB"], mcu["PDR_ON"]
GND += mcu["VSS"], mcu["VSSA"]
V3A += mcu["VDDA"], mcu["VREF+"]
VCAP = N("VCAP")
for _p in mcu["VCAP"]:
    _p.func = Pin.types.PASSIVE        # two VCAP pins, both outputs of the internal LDO: tie together
VCAP += mcu["VCAP"]
cap_between(VCAP, GND, "2.2u", C0603, n=2)                  # LDO mode: 2 x 2.2 uF on the two VCAP pins
for _ in range(11):
    cap_between(V3, GND, "100n")
cap_between(V3, GND, "4.7u", C0805, n=2)
cap_between(V3A, GND, "1u")
cap_between(V3A, GND, "100n")
# reset, boot
NRST = N("NRST")
NRST += mcu["NRST"]
cap_between(NRST, GND, "100n")
sw_rst = Part("Switch", "SW_Push", value="RESET", footprint=fp(BTN))
NRST += sw_rst[1]
GND += sw_rst[2]
BOOT0 = N("BOOT0")
BOOT0 += mcu["BOOT0"]
res_between(BOOT0, GND, "10k")
sw_boot = Part("Switch", "SW_Push", value="BOOT0", footprint=fp(BTN))
BOOT0 += sw_boot[1]
res_between(sw_boot[2], V3, "1k")
# HSE 25 MHz, LSE 32.768 kHz
xt = Part("Device", "Crystal_GND24", value="25MHz 8pF", footprint=fp("Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm"))
OSC_IN, OSC_OUT = N("OSC_IN"), N("OSC_OUT")
OSC_IN += mcu["PH0"], xt[1]
OSC_OUT += mcu["PH1"], xt[3]
GND += xt[2], xt[4]
cap_between(OSC_IN, GND, "12p")
cap_between(OSC_OUT, GND, "12p")
xl = Part("Device", "Crystal", value="32.768kHz 6pF", footprint=fp("Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm"))
LSE_IN, LSE_OUT = N("LSE_IN"), N("LSE_OUT")
LSE_IN += mcu["PC14"], xl[1]
LSE_OUT += mcu["PC15"], xl[2]
cap_between(LSE_IN, GND, "8p")
cap_between(LSE_OUT, GND, "8p")
# SWD
j_swd = Part("Connector_Generic", "Conn_02x05_Odd_Even", value="J_SWD (Cortex 1.27 mm)",
             footprint=fp("Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical"))
SWDIO, SWCLK = N("SWDIO"), N("SWCLK")
SWDIO += mcu["PA13"]
SWCLK += mcu["PA14"]
V3 += j_swd[1]
SWDIO += j_swd[2]
GND += j_swd[3], j_swd[5], j_swd[9]
SWCLK += j_swd[4]
NRST += j_swd[10]

# --------------------------------------------------------------------------------------
# 9. QSPI flash 16 MB (W25Q128JV)
# --------------------------------------------------------------------------------------
section("flash")
u_fl = Part("Memory_Flash", "W25Q128JVS", value="W25Q128JVSIQ", footprint=fp("Package_SO:SOIC-8_5.3x5.3mm_P1.27mm"))
V3 += u_fl["VCC"]
GND += u_fl["GND"]
q_cs, q_clk = sig("QSPI_NCS"), sig("QSPI_CLK")
q_cs += u_fl["~{CS}"]
q_clk += u_fl["CLK"]
sig("QSPI_IO0").__iadd__(u_fl["DI/IO_{0}"])
sig("QSPI_IO1").__iadd__(u_fl["DO/IO_{1}"])
sig("QSPI_IO2").__iadd__(u_fl["~{WP}/IO_{2}"])
sig("QSPI_IO3").__iadd__(u_fl["~{HOLD}/~{RESET}/IO_{3}"])
res_between(q_cs, V3, "10k")
cap_between(V3, GND, "100n")

# --------------------------------------------------------------------------------------
# 10. Ethernet: LAN8720A RMII (REF_CLK-out mode from a 25 MHz crystal) + RJ45 with magnetics
# --------------------------------------------------------------------------------------
section("ethernet")
phy = Part("Interface_Ethernet", "LAN8720A", value="LAN8720A", footprint=fp("Package_DFN_QFN:QFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm"))
V3 += phy["VDD1A"], phy["VDD2A"], phy["VDDIO"]
GND += phy["VSS"]
VDDCR = N("PHY_VDDCR")
VDDCR += phy["VDDCR"]
cap_between(VDDCR, GND, "1u")
cap_between(VDDCR, GND, "470p")
cap_between(V3, GND, "100n", n=3)
res_between(phy["RBIAS"], GND, "12.1k 1%")
xp = Part("Device", "Crystal_GND24", value="25MHz 20pF", footprint=fp("Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm"))
X1, X2 = N("PHY_XTAL1"), N("PHY_XTAL2")
X1 += phy["XTAL1/CLKIN"], xp[1]
X2 += phy["XTAL2"], xp[3]
GND += xp[2], xp[4]
cap_between(X1, GND, "22p")
cap_between(X2, GND, "22p")
# straps: nINTSEL low = REF_CLK-out mode (nINT unavailable), REGOFF floating = internal 1.2 V regulator
res_between(phy["LED2/~{INTSEL}"], GND, "10k")
# nINT/REFCLKO pin drives ETH_REF_CLK (PA1) with a 33 R series resistor
REFCLK = N("ETH_REF_CLK")
res_between(phy["~{INT}/REFCLKO"], REFCLK, "33")
REFCLK += mp("ETH_REF_CLK")
for pin_label, phy_pin in (("ETH_MDIO", "MDIO"), ("ETH_MDC", "MDC"), ("ETH_CRS_DV", "CRS_DV/MODE2"),
                           ("ETH_RXD0", "RXD0/MODE0"), ("ETH_RXD1", "RXD1/MODE1"),
                           ("ETH_TX_EN", "TXEN"), ("ETH_TXD0", "TXD0"), ("ETH_TXD1", "TXD1")):
    n = sig(pin_label)
    n += phy[phy_pin]
res_between(N("ETH_MDIO"), V3, "1.5k")
ETH_NRST = sig("ETH_NRST")
ETH_NRST += phy["~{RST}"]
res_between(ETH_NRST, V3, "10k")
phy["RXER/PHYAD0"] += N("PHY_RXER")
res_between(N("PHY_RXER"), GND, "10k")
# RJ45 jack with integrated magnetics (Hanrun HR911105A): TD+/TD-/RD+/RD-, centre taps to 3V3, LEDs always on
j_eth = Part("Connector", "RJ45_Hanrun_HR911105A_Horizontal", value="J_ETH HR911105A",
             footprint=fp("Connector_RJ:RJ45_Hanrun_HR911105A_Horizontal"))
phy["TXP"] += j_eth["TD+"]
phy["TXN"] += j_eth["TD-"]
phy["RXP"] += j_eth["RD+"]
phy["RXN"] += j_eth["RD-"]
CT = N("ETH_CT")
CT += j_eth["TCT"], j_eth["RCT"]
fct = Part("Device", "FerriteBead", value="600R", footprint=fp("Inductor_SMD:L_0603_1608Metric"))
V3 += fct[1]
CT += fct[2]
cap_between(CT, GND, "100n", n=2)
cap_between(CT, GND, "10u", C0805)
j_eth["SH"] += N("ETH_SHIELD")
res_between(N("ETH_SHIELD"), GND, "1M")
cap_between(N("ETH_SHIELD"), GND, "4.7n 2kV", C1206)

# --------------------------------------------------------------------------------------
# 11. CAN (isolated, CA-IS3062VW: integrated 5 V isolated supply)
# --------------------------------------------------------------------------------------
section("can")
u_can = Part("mppt_custom", "CA-IS3062VW", value="CA-IS3062VW", footprint=fp("Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm"))
V5 += u_can["VCC"]
V3 += u_can["VCCL"]
GND += u_can["GND1"]
sig("CAN_TX").__iadd__(u_can["TXD"])
sig("CAN_RX").__iadd__(u_can["RXD"])
CAN_GND, CAN_VISO = N("CAN_GND"), N("CAN_VISO")
CAN_GND += u_can["GND2"]
CAN_VISO += u_can["VISO"]                                     # both VISO pins tied together
CANH, CANL = N("CANH"), N("CANL")
CANH += u_can["CANH"]
CANL += u_can["CANL"]
cap_between(V5, GND, "100n")
cap_between(V5, GND, "10u", C0805)
cap_between(V3, GND, "100n")
cap_between(CAN_VISO, CAN_GND, "100n")
cap_between(CAN_VISO, CAN_GND, "10u", C0805)
tvs_can = Part("Diode", "SM712_SOT23", value="SM712", footprint=fp(SOT23))
CANH += tvs_can["A1"]
CANL += tvs_can["A2"]
CAN_GND += tvs_can["common"]
jp_can = Part("Jumper", "SolderJumper_2_Open", value="JP_CAN_TERM", footprint=fp(SJ))
mid = N("CAN_TERM_MID")
res_between(CANH, mid, "120")
mid += jp_can["A"]
CANL += jp_can["B"]
header([CANH, CANL, CAN_GND], "J_CAN (H, L, GND)", "TerminalBlock_Phoenix:TerminalBlock_Phoenix_PT-1,5-3-3.5-H_1x03_P3.50mm_Horizontal")

# --------------------------------------------------------------------------------------
# 12. RS485 (isolated, CA-IS3092W, same as the valve controller)
# --------------------------------------------------------------------------------------
section("rs485")
u485 = Part("mppt_custom", "CA-IS3092W", value="CA-IS3092W", footprint=fp("Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm"))
ISO_GND, ISO_3V3 = N("ISO_GND"), N("ISO_3V3")
RS_A, RS_B = N("RS485_A"), N("RS485_B")
V3 += u485["VCC"]
GND += u485["GNDA"]
ISO_GND += u485["GNDB"]
ISO_3V3 += u485["VISO"]
sig("RS485_RX").__iadd__(u485["RO"])
sig("RS485_TX").__iadd__(u485["DI"])
rs_de = sig("RS485_DE")
rs_de += u485["DE"]
rs_nre = sig("RS485_NRE")
rs_nre += u485["~{RE}"]
RS_A += u485["A"]
RS_B += u485["B"]
cap_between(V3, GND, "100n")
cap_between(V3, GND, "10u", C0805)
cap_between(ISO_3V3, ISO_GND, "100n")
cap_between(ISO_3V3, ISO_GND, "10u", C0805)
tvs485 = Part("Diode", "SM712_SOT23", value="SM712", footprint=fp(SOT23))
RS_A += tvs485["A1"]
RS_B += tvs485["A2"]
ISO_GND += tvs485["common"]
jp = Part("Jumper", "SolderJumper_2_Open", value="JP_485_TERM", footprint=fp(SJ))
mid = N("RS485_TERM_MID")
res_between(RS_A, mid, "120")
mid += jp["A"]
RS_B += jp["B"]
header([RS_A, RS_B, ISO_GND], "J_485 (A, B, GND)", "TerminalBlock_Phoenix:TerminalBlock_Phoenix_PT-1,5-3-3.5-H_1x03_P3.50mm_Horizontal")

# --------------------------------------------------------------------------------------
# 13. USB-C (device, DFU/CDC) and UART header
# --------------------------------------------------------------------------------------
section("usb_uart")
USB_DP, USB_DN = N("USB_DP"), N("USB_DN")
USB_DP_C, USB_DN_C = N("USB_DP_CONN"), N("USB_DN_CONN")
j_usb = Part("Connector", "USB_C_Receptacle_USB2.0_16P", value="J_USB", footprint=fp("Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12"))
for p in ("A4", "A9", "B4", "B9"):
    VBUS_USB += j_usb[p]
for p in ("A1", "A12", "B1", "B12"):
    GND += j_usb[p]
res_between(j_usb["A5"], GND, "5.1k")
res_between(j_usb["B5"], GND, "5.1k")
USB_DP_C += j_usb["A6"], j_usb["B6"]
USB_DN_C += j_usb["A7"], j_usb["B7"]
res_between(j_usb["SH"], GND, "1M")
cap_between(j_usb["SH"], GND, "4.7n")
u_esd = Part("Power_Protection", "USBLC6-2SC6", value="USBLC6-2SC6", footprint=fp("Package_TO_SOT_SMD:SOT-23-6"))
USB_DP_C += u_esd[1]
USB_DP += u_esd[6]
USB_DN_C += u_esd[3]
USB_DN += u_esd[4]
GND += u_esd[2]
VBUS_USB += u_esd[5]
cap_between(VBUS_USB, GND, "10u", C1206)
USB_DP += mcu[PM["USB_DP"]["lqfp"]]
USB_DN += mcu[PM["USB_DM"]["lqfp"]]
# USB power path: 500 mA PTC, Schottky into VAUX (about 4.6 V); the 3V3 buck still runs, the 5 V rail sags (CAN supply may not start)
USB_PF = N("VBUS_PROT")
f_usb = Part("Device", "Polyfuse", value="PTC 0.5A 6V", footprint=fp("Fuse:Fuse_1206_3216Metric"))
VBUS_USB += f_usb[1]
USB_PF += f_usb[2]
d_usb = Part("Device", "D_Schottky", value="SS14", footprint=fp(SMA))
USB_PF += d_usb["A"]
VAUX += d_usb["K"]
tp(USB_PF, "TP_USB_PWR")
# VBUS detect (divider to a GPIO)
vb = sig("USB_VBUS")
res_between(VBUS_USB, vb, "10k")
res_between(vb, GND, "20k")
# UART console / ROM bootloader (USART3)
header([GND, sig("CON_TX"), sig("CON_RX"), V3], "J_UART (GND, TX, RX, 3V3)")

# --------------------------------------------------------------------------------------
# 14. Display: 40-pin FPC (RGB565 / LTDC, backlight, touch I2C) + SPI header
# --------------------------------------------------------------------------------------
section("display")
# 4.3" 480x272 RGB TFT with resistive touch, 40-pin 0.5 mm FPC, "AT043TN24-style" pinout (VERIFY against the chosen panel datasheet):
# 1 LEDK, 2 LEDA, 3 GND, 4 VDD, 5-12 R0-R7, 13-20 G0-G7, 21-28 B0-B7, 29 GND, 30 DCLK, 31 DISP, 32 HSYNC, 33 VSYNC, 34 DE,
# 35 NC, 36 GND, 37 XR, 38 YD, 39 XL, 40 YU. LTDC drives RGB565 on the upper bits; the lower bits are tied to GND.
j_lcd = Part("Connector_Generic", "Conn_01x40", value="J_LCD 40-pin 0.5 mm FPC (4.3in RGB)",
             footprint=fp("Connector_FFC-FPC:Hirose_FH12-40S-0.5SH_1x40-1MP_P0.50mm_Horizontal"))
BL_A, BL_K = N("LCD_BL_A"), N("LCD_BL_K")
j_lcd[1] += BL_K
j_lcd[2] += BL_A
j_lcd[3] += GND
j_lcd[4] += V3
for pin_, lab in zip(range(5, 13), [None, None, None, "LCD_R3", "LCD_R4", "LCD_R5", "LCD_R6", "LCD_R7"]):
    j_lcd[pin_] += (sig(lab) if lab else GND)
for pin_, lab in zip(range(13, 21), [None, None, "LCD_G2", "LCD_G3", "LCD_G4", "LCD_G5", "LCD_G6", "LCD_G7"]):
    j_lcd[pin_] += (sig(lab) if lab else GND)
for pin_, lab in zip(range(21, 29), [None, None, None, "LCD_B3", "LCD_B4", "LCD_B5", "LCD_B6", "LCD_B7"]):
    j_lcd[pin_] += (sig(lab) if lab else GND)
j_lcd[29] += GND
j_lcd[30] += sig("LCD_CLK")
lcd_disp = sig("LCD_RST")                         # panel DISP (high = display on)
j_lcd[31] += lcd_disp
res_between(lcd_disp, GND, "100k")
j_lcd[32] += sig("LCD_HSYNC")
j_lcd[33] += sig("LCD_VSYNC")
j_lcd[34] += sig("LCD_DE")
j_lcd[36] += GND
TP_XR, TP_YD, TP_XL, TP_YU = N("TOUCH_XR"), N("TOUCH_YD"), N("TOUCH_XL"), N("TOUCH_YU")
j_lcd[37] += TP_XR
j_lcd[38] += TP_YD
j_lcd[39] += TP_XL
j_lcd[40] += TP_YU
# resistive touch controller on the shared SPI2 bus
u_ts = Part("Driver_Display", "XPT2046TS", value="XPT2046", footprint=fp("Package_SO:TSSOP-16_4.4x5mm_P0.65mm"))
V3 += u_ts["VCC"], u_ts["IOVDD"], u_ts["VBAT"]
GND += u_ts["GND"], u_ts["IN"]
cap_between(V3, GND, "100n", n=2)
cap_between(u_ts["VREF"], GND, "100n")
TP_XR += u_ts["XP"]
TP_YU += u_ts["YP"]
TP_XL += u_ts["XN"]
TP_YD += u_ts["YN"]
sck, mosi, miso = sig("SPI_SCK"), sig("SPI_MOSI"), sig("SPI_MISO")
sck += u_ts["DCLK"]
mosi += u_ts["DIN"]
miso += u_ts["DOUT"]
tcs = sig("TOUCH_CS")
tcs += u_ts["~{CS}"]
res_between(tcs, V3, "10k")
tint = sig("TOUCH_INT")
tint += u_ts["~{PENIRQ}"]
res_between(tint, V3, "10k")
# backlight: MT3608 boost from 5 V, LED current set by a sense resistor on FB (0.6 V / 30 ohm = 20 mA; VERIFY panel LED current/voltage)
u_bl = Part("Regulator_Switching", "MT3608", value="MT3608", footprint=fp("Package_TO_SOT_SMD:SOT-23-6"))
BL_SW = N("BL_SW")
V5 += u_bl["IN"]
GND += u_bl["GND"]
BL_SW += u_bl["SW"]
cap_between(V5, GND, "10u 25V", C1206)
l_bl = Part("Device", "L", value="22u 1.5A", footprint=fp("Inductor_SMD:L_Bourns_SRP5030T"))
V5 += l_bl[1]
BL_SW += l_bl[2]
d_bl = Part("Device", "D_Schottky", value="SS14", footprint=fp(SMA))
BL_SW += d_bl["A"]
BL_A += d_bl["K"]
cap_between(BL_A, GND, "10u 50V", C1206)
z_bl = Part("Device", "D_Zener", value="BZT52C27 27V (OVP)", footprint=fp(SOD123))
BL_A += z_bl["K"]
GND += z_bl["A"]
BL_K += u_bl["FB"]
res_between(BL_K, GND, "30 1%")
BL_PWM = sig("LCD_BL_PWM")
BL_PWM += u_bl["EN"]
res_between(BL_PWM, GND, "100k")
# SPI header for a small OLED/TFT: GND, 3V3, SCK, MOSI, MISO, CS, DC, RST
header([GND, V3, sig("SPI_SCK"), sig("SPI_MOSI"), sig("SPI_MISO"), sig("SPI_CS"), sig("SPI_DC"), sig("SPI_RST")],
       "J_SPI_LCD (GND, 3V3, SCK, MOSI, MISO, CS, DC, RST)")
# fan output (9 V, low-side N-FET PWM)
FAN_PWM = sig("FAN_PWM")
q_fan = Part("Transistor_FET", "2N7002", value="2N7002", footprint=fp(SOT23))
FAN_K = N("FAN_K")
FAN_K += q_fan["D"]
GND += q_fan["S"]
FAN_PWM += q_fan["G"]
res_between(FAN_PWM, GND, "100k")
d_fan = Part("Device", "D_Schottky", value="SS14", footprint=fp(SMA))
FAN_K += d_fan["A"]
VAUX += d_fan["K"]
header([VAUX, FAN_K], "J_FAN (9 V, GND-switched)")

# --------------------------------------------------------------------------------------
# 15. LEDs and remaining MCU control signals
# --------------------------------------------------------------------------------------
section("leds")
for i, colour in enumerate(("green CHARGE", "yellow LOAD", "blue COMM", "red FAULT"), 1):
    n = sig(f"LED{i}")
    d = led(n, colour.split()[0])
    GND += d["K"]
# control nets from the MCU
MPPT_NEN += mp("MPPT_EN")
LOAD_NEN += mp("LOAD_EN")
INV_NEN += mp("INV_EN")
LOAD_PGD += mp("LOAD_PGD")
INV_PGD += mp("INV_PGD")
MPPT_NFLT += mp("MPPT_FLT")
INV_REMOTE += mp("INV_REMOTE")
INV_FAULT += mp("INV_FAULT")
ALERT += mp("INA_ALERT")
SDA += mp("I2C_SDA")
SCL += mp("I2C_SCL")
for lab, net in (("ADC_VPV", VPV_ADC), ("ADC_VBAT", VBAT_ADC), ("ADC_VLOAD", VLOAD_ADC),
                 ("ADC_NTC_PWR", N("ADC_NTC_PWR")), ("ADC_NTC_BAT", N("ADC_NTC_BAT")), ("ADC_NTC_AUX", N("ADC_NTC_AUX"))):
    net += mp(lab)

# --------------------------------------------------------------------------------------
# Datasheet checks: pin numbers that the footprints depend on. A mismatch stops the build.
# --------------------------------------------------------------------------------------
def pin_numbers(part, name):
    return sorted(str(p.num) for p in part.pins if p.name == name)


CHECKS = [
    # LM5177 (TI SNVSBU4F, DCP038 table 4-1)
    (u1, {"BIAS": ["1"], "VIN": ["3"], "EN/UVLO": ["4"], "IMONOUT": ["6"], "nFLT": ["7"], "DTRK": ["10"], "SYNC": ["11"],
          "MODE": ["12"], "CFG": ["13"], "SLOPE": ["14"], "RT": ["15"], "SS/ATRK": ["16"], "AGND": ["17"], "COMP": ["18"],
          "FB": ["19"], "VOUT": ["20"], "ISNSN": ["22"], "ISNSP": ["23"], "SW2": ["25"], "HB2": ["26"], "HO2": ["27"],
          "LO2": ["29"], "PGND": ["30"], "VCC": ["31"], "LO1": ["32"], "HO1": ["34"], "HB1": ["35"], "SW1": ["36"],
          "CSA": ["37"], "CSB": ["38"]}),
    # CA-IS3062VW (Chipanalog v1.04, table 6-1), SOIC16-WB
    (u_can, {"VCC": ["1"], "GND1": ["2", "8"], "TXD": ["3"], "RXD": ["5"], "VCCL": ["7"], "GND2": ["10", "15", "9"],
             "VISO": ["11", "16"], "CANL": ["12"], "CANH": ["13"]}),
    # CA-IS3092W (Chipanalog v1.11), SOIC16-WB
    (u485, {"VCC": ["1"], "GNDA": ["2", "8"], "RO": ["3"], "~{RE}": ["4"], "DE": ["5"], "DI": ["6"],
            "GNDB": ["15", "9"], "SEL": ["10"], "A": ["12"], "B": ["13"], "VISO": ["16"]}),
    # LM74700-Q1 SOT-23-6: 1 VCAP, 2 GND, 3 EN, 4 CATHODE, 5 GATE, 6 ANODE
    (u_pvd, {"VCAP": ["1"], "GND": ["2"], "EN": ["3"], "CATHODE": ["4"], "GATE": ["5"], "ANODE": ["6"]}),
    # LM5069MM VSSOP-10
    (u_load, {"SENSE": ["1"], "VIN": ["2"], "UVLO": ["3"], "OVLO": ["4"], "GND": ["5"], "TIMER": ["6"], "PWR": ["7"],
              "PGD": ["8"], "OUT": ["9"], "GATE": ["10"]}),
    # TPS54360DDA: 1 BOOT, 2 VIN, 3 EN, 4 RT/CLK, 5 FB, 6 COMP, 7 GND, 8 SW, 9 PowerPAD
    (u_aux, {"BOOT": ["1"], "VIN": ["2"], "EN": ["3"], "RT/CLK": ["4"], "FB": ["5"], "COMP": ["6"], "GND": ["7"], "SW": ["8"]}),
    # LAN8720A QFN-24: 1 VDD2A ... 15 nRST, 16 TXEN, 17 TXD0, 18 TXD1, 19 VDD1A, 24 RBIAS, 25 VSS (EP)
    (phy, {"VDD2A": ["1"], "XTAL2": ["4"], "XTAL1/CLKIN": ["5"], "VDDCR": ["6"], "VDDIO": ["9"], "MDIO": ["12"], "MDC": ["13"],
           "~{RST}": ["15"], "TXEN": ["16"], "TXD0": ["17"], "TXD1": ["18"], "VDD1A": ["19"], "RBIAS": ["24"], "VSS": ["25"]}),
    # W25Q128JVS SOIC-8 208 mil: 1 /CS, 2 DO, 3 /WP, 4 GND, 5 DI, 6 CLK, 7 /HOLD, 8 VCC
    (u_fl, {"~{CS}": ["1"], "GND": ["4"], "CLK": ["6"], "VCC": ["8"]}),
]
for part, want in CHECKS:
    for name, nums in want.items():
        got = pin_numbers(part, name)
        assert sorted(got) == sorted(nums), f"{part.name} pin {name}: symbol has {got}, datasheet says {nums}"

# STM32: every mapped signal must be on a pin that has that alternate function (ST open pin data)
AF = json.load(open(os.path.join(HERE, "h743zit_af.json")))["af"]
for lab, v in PM.items():
    if v["signal"] != "GPIO":
        assert v["signal"] in AF[v["pin"]], f"{lab}: {v['pin']} has no {v['signal']}"
    names = pin_numbers(mcu, v["pin"])
    assert names == [v["lqfp"]] or str(mcu[v["lqfp"]].name).startswith(v["pin"]), \
        f"{lab}: LQFP pin {v['lqfp']} is {mcu[v['lqfp']].name}, expected {v['pin']}"

# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    os.chdir(HERE)
    if _cur[0] is not None:
        _cur[0].__exit__(None, None, None)
    ERC()
    generate_netlist(file_="mppt_controller.net")
    import net2sch
    net2sch.main("mppt_controller.net")      # label-only hierarchical schematic from the netlist
    if MISSING_FP:
        print("Footprints not found in the KiCad library:", sorted(set(MISSING_FP)))
