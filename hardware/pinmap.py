#!/usr/bin/env python3
"""
STM32H743ZIT6 (LQFP-144) pin allocator.
Source of truth for alternate functions: STMicroelectronics/STM32_open_pin_data (STM32H743ZITx.xml, parsed to h743zit_af.json).
Every signal below is assigned to a pin that really has that function; no pin is used twice.
Run:  python3 pinmap.py  -> prints the map and writes pinmap.json
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "h743zit_af.json")))
AF = D["af"]            # pin name -> list of signal names
POS = D["pos"]          # pin name -> LQFP-144 position

# Pins that must never be given to a general signal
RESERVED = {"PA13": "SWDIO", "PA14": "SWCLK", "PH0": "HSE", "PH1": "HSE", "PC14": "LSE", "PC15": "LSE",
            "PC13": "tamper/RTC (kept free)", "PA11": "USB_DM", "PA12": "USB_DP", "PB3": "SWO (kept free)"}

# (label, [signal alternatives])   fixed-function peripherals first
REQ = []
def add(label, *sigs): REQ.append((label, list(sigs)))

# QSPI flash
for s in ["CLK", "BK1_NCS", "BK1_IO0", "BK1_IO1", "BK1_IO2", "BK1_IO3"]:
    add("QSPI_" + s.replace("BK1_", ""), "QUADSPI_" + s)
# Ethernet RMII
for s in ["REF_CLK", "MDIO", "MDC", "CRS_DV", "RXD0", "RXD1", "TX_EN", "TXD0", "TXD1"]:
    add("ETH_" + s, "ETH_" + s)
# USB FS device
add("USB_DM", "USB_OTG_FS_DM"); add("USB_DP", "USB_OTG_FS_DP")
# LTDC RGB565 + control
for n in (3, 4, 5, 6, 7): add(f"LCD_R{n}", f"LTDC_R{n}")
for n in (2, 3, 4, 5, 6, 7): add(f"LCD_G{n}", f"LTDC_G{n}")
for n in (3, 4, 5, 6, 7): add(f"LCD_B{n}", f"LTDC_B{n}")
for s in ("CLK", "HSYNC", "VSYNC", "DE"): add("LCD_" + s, "LTDC_" + s)
# comms
add("CAN_TX", "FDCAN1_TX"); add("CAN_RX", "FDCAN1_RX")
add("RS485_TX", "USART6_TX"); add("RS485_RX", "USART6_RX"); add("RS485_DE", "USART6_DE")
add("CON_TX", "USART3_TX"); add("CON_RX", "USART3_RX")
add("I2C_SCL", "I2C1_SCL"); add("I2C_SDA", "I2C1_SDA")          # INA228 x4 + temp
add("SPI_SCK", "SPI2_SCK"); add("SPI_MOSI", "SPI2_MOSI"); add("SPI_MISO", "SPI2_MISO")
add("LCD_BL_PWM", "TIM3_CH1", "TIM3_CH2", "TIM3_CH3", "TIM3_CH4", "TIM4_CH1", "TIM4_CH2", "TIM4_CH3", "TIM4_CH4")
# analog
# Vmpp/Vcv references come from an external I2C DAC (MCP4728): LTDC_VSYNC (PA4) and LTDC_R4 (PA5) take the MCU DAC pins
for n in ("VPV", "VBAT", "VLOAD", "NTC_PWR", "NTC_BAT", "NTC_AUX"):
    add("ADC_" + n, *[f"ADC{a}_INP{i}" for a in (1, 2, 3) for i in range(0, 20)])
# plain GPIO (any pin)
GPIO = ["USB_VBUS", "LED1", "LED2", "LED3", "LED4",
        "MPPT_EN", "MPPT_FLT", "LOAD_EN", "LOAD_PGD", "INV_EN", "INV_PGD", "INV_REMOTE", "INV_FAULT",
        "INA_ALERT", "ETH_NRST", "LCD_RST", "TOUCH_INT", "TOUCH_CS", "SPI_CS", "SPI_DC", "SPI_RST",
        "FAN_PWM", "RS485_NRE"]
for g in GPIO: add(g, "GPIO")

def solve():
    """Bipartite matching (Kuhn augmenting paths): signal -> pin. Raises with the unplaceable signals."""
    cands = []
    for label, sigs in REQ:
        if label in ("USB_DM", "USB_DP"):
            c = [p for p, s in AF.items() if any(x in s for x in sigs)]
        else:
            c = [p for p, s in AF.items() if p not in RESERVED and re.fullmatch(r"P[A-K]\d+", p) and any(x in s for x in sigs)]
        cands.append((label, sigs, sorted(c, key=lambda p: (p[1], int(p[2:])))))
    owner = {}                       # pin -> request index
    def try_place(i, seen):
        for p in cands[i][2]:
            if p in seen: continue
            seen.add(p)
            if p not in owner or try_place(owner[p], seen):
                owner[p] = i
                return True
        return False
    order = sorted(range(len(cands)), key=lambda i: (cands[i][1] == ["GPIO"], len(cands[i][2])))
    failed = [cands[i][0] for i in order if not try_place(i, set())]
    if failed: raise SystemExit("cannot place: " + ", ".join(failed))
    pin_of = {i: p for p, i in owner.items()}
    res = {}
    for i, (label, sigs, c) in enumerate(cands):
        p = pin_of[i]
        res[label] = {"pin": p, "lqfp": POS[p], "signal": next((x for x in sigs if x in AF[p]), "GPIO")}
    return res

if __name__ == "__main__":
    r = solve()
    json.dump(r, open(os.path.join(HERE, "pinmap.json"), "w"), indent=1)
    for k, v in r.items(): print(f"{k:12s} {v['pin']:5s} pin{v['lqfp']:>4s}  {v['signal']}")
    print(len(r), "signals")
