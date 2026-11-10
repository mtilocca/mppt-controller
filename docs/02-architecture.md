# 2. Architecture (draft)

```
PV 0-48V --[fuse][TVS][reverse-pol FET]--> Vpv sense -+
                                                      |  LM5177 4-switch buck-boost
                                                      +--(Q1..Q4, L, Rcs)--> VBAT bus --[fuse]-- BAT 12-48V
                                                                               |
                                      load switch (back-to-back FET, current limit) --> LOAD 12-48V
                                      inverter switch (pre-charge + FET) --> INVERTER DC + control port
STM32H743 <-- ADCs (V/I/T), DAC (Vmpp ref, Vbat trim), GPIO (enables/faults), QSPI flash, LTDC/SPI display,
              ETH RMII (LAN8720A), FDCAN (isolated), USART RS485 (isolated), USB FS, UART header, SWD, 4 LEDs
Aux supply: VBAT bus (10-60 V) -> 9 V buck (TPS54360; LM5177 BIAS, fan) -> 5 V (AP63205) and 3V3 (AP63203)
```

## 2.1 Power stage: LM5177 (checked against datasheet SNVSBU4F)

- VIN 3.5-60 V (abs max 85 V), VOUT 3.3-60 V, bidirectional, fixed frequency in buck/boost/buck-boost, up to 600 kHz. HTSSOP-38 (DCP), pins read from Table 4-1. "Solar charge controller" is a listed application.
- FB reference 1.0 V (+-1 %). Output voltage = battery CV limit set by the FB divider (hardware cap about 58.8 V). SS/ATRK takes the lowest voltage applied, so a MCU DAC can lower the CV target per chemistry without the hardware cap being removable.
- Battery-side CC: the second current-sense amplifier (ISNSP/ISNSN) as a *current limiter* on the battery output side (limit set by the sense resistor, 45 mV class threshold; set for ~10 A). CFG resistor latches SCP/hiccup, spread spectrum, PSM, current-limit options at power-up (Table 7-1). SYNC low at enable selects negative limit direction, so it must be pulled high/clocked for a charging (positive) limit.
- **MPPT loop (my design, not from TI):** the LM5177 has no input-voltage regulation. COMP only swings about 0.24-1.25 V (clamp voltages in the datasheet), so a small op-amp compares the divided PV voltage with a DAC reference (Vmpp setpoint) and pulls COMP down through a diode when Vpv sags below the setpoint. The MCU runs the MPPT algorithm by moving the DAC reference (voltage-based P&O, plus open-circuit-voltage fraction at start). This is analog and fast, and the MCU cannot make the converter unsafe.
- Power stage parts to pick (100 V class): 4x N-FET (e.g. 100 V, <= 6 mOhm, PowerPAK/LFPAK), shielded inductor ~10-15 uH, Isat >= 25 A (likely a through-hole/chassis part), sense resistors 2-5 mOhm, bulk caps rated 80 V+ on both sides. Switching frequency 100-150 kHz to keep losses and size manageable at 10 A.

## 2.2 Protection

PV: fuse, 58 V-class TVS, reverse-polarity P-FET/ideal diode. Battery: fuse, TVS, reverse-polarity protection, hardware OVP via FB cap. Load and inverter switches: back-to-back N-FETs with gate driver and current-sense limit; MCU can cut them, hardware trips on overcurrent independent of MCU. Pre-charge resistor + relay/FET for inverter input capacitors.

## 2.3 MCU: STM32H743ZIT6 (LQFP-144)

Chosen over LQFP-100 because QSPI + LTDC (RGB) + RMII + FDCAN + 3 USART + 12-bit DAC need more pins than the 100-pin package offers. Pin map to be built from the KiCad symbol alternate functions and checked against the DS12110 datasheet tables; assertions in the generator will stop the build if a signal is on a pin without that alternate function. Crystal 25 MHz (shared with LAN8720A via its own crystal or the MCU MCO), 32.768 kHz RTC crystal, SMPS or LDO core supply (LDO mode, simpler).

## 2.4 Peripherals

| Block | Part (proposed) | Notes |
|-------|-----------------|-------|
| QSPI flash | W25Q128JV (16 MB) | symbol in KiCad lib (Memory_Flash) |
| Ethernet | LAN8720A + RJ45 with integrated magnetics | symbol in KiCad lib; RMII |
| RS485 | isolated transceiver (e.g. CA-IS3092W as on the valve board, datasheet already checked) | 120 R termination jumper |
| CAN | isolated CAN-FD transceiver (e.g. ISO1042 class or CA-IS3050) | footprint/symbol need to be created |
| USB-C | USB FS device, USBLC6-2, 5.1 k CC resistors | as valve board |
| UART header | 3V3 TTL, 1x4 header (TX, RX, GND, 3V3) + BOOT0 button | ROM bootloader fallback |
| Display | 40-pin 0.5 mm FPC (RGB565/LTDC, backlight, touch I2C) + 1x8 SPI header | STM32H743 LTDC |
| LEDs | 4x 0603 on MCU GPIO | e.g. CHARGE, LOAD, COMM, FAULT |
| Sensing | INA228-class monitors on PV, BAT, load (80 V common mode, I2C) or INA240-class + ADC | INA228 is common-mode 85 V, in KiCad lib |

## 2.5 Open decisions / risks

1. **MPPT COMP-pull-down loop** is my own topology; needs bench verification (stability against the LM5177 compensation) and ideally SPICE. The datasheet-only values (COMP clamp, FB 1 V) are the basis.
2. 48 V nominal batteries need 60 V-rated everything; PV open-circuit voltage up to 48 V plus cold-weather margin is OK for the 60 V LM5177 limit, but a PV array that can exceed 55 V is not supported.
3. 10 A at 48 V = 480 W: thermal design (2 oz, heatsinking of FETs/inductor) decides whether this fits on the board. Inductor likely off-board.
4. Isolated CAN part not chosen yet; Ethernet jack part must be available at JLC (hand-solder if not).
5. Pin map of the STM32 not yet built; DS12110 not yet fetched.

## 2.6 Status 2026-11-07: schematic generated (KiCad ERC 0 violations, 335 parts, 285 nets)

Built by `hardware/mppt_controller.py` (SKiDL) + `net2sch.py`; STM32 pins by `hardware/pinmap.py` (see 03-pinmap.md).

| Block | Implementation |
|-------|----------------|
| PV input | 15 A blade fuse, SMCJ51A TVS (clamp 82 V < LM5177 85 V), LM74700 ideal diode + 100 V N-FET (the LM5177 is bidirectional, so the battery must not back-feed the PV terminal), 2 mOhm PV shunt |
| Power stage | LM5177 at about 151 kHz (RT 200 k), L 10 uH / 32 A (placeholder footprint), RCS 2 mOhm, 4 x 100 V TDSON-8 N-FETs, MODE low = PSM (no reverse inductor current), CFG 36.5 k, SLOPE 200 k, FB 71.5 k / 1.24 k = 58.66 V hardware charge cap, charge-current limiter on a 4 mOhm shunt |
| MPPT loop | TLV9061 PI error amp, PV divider 301 k / 10 k (60 V = 1.93 V), reference from MCP4728 channel A, Schottky to COMP. MCP4728 channel B drives SS/ATRK (CV target) |
| Battery | 30 A blade fuse, SMCJ58A, 2 parallel low-side N-FETs for reverse polarity (gate pulled up to battery +, 12 V zener), 2 mOhm battery shunt, 2 x 150 uF + ceramics on the bus |
| Load / inverter feed | LM5069-1 hot-swap controllers (latch-off), 3 mOhm sense (about 17 A limit, 35 A breaker), UVLO 9.7 V / OVLO 63 V, MCU NFET pulls UVLO low (gate pulled up: OFF at reset). Inverter port: PC817 optocouplers, REMOTE (contact out) and STATUS (5-24 V in) |
| Sensing | 5 x INA228 (PV 0x40, CHG 0x41, BAT 0x42, LOAD 0x43, INV 0x44) on I2C1 with a shared ALERT line, plus redundant ADC dividers and 3 NTC inputs |
| Aux power | TPS54360 9.0 V -> AP63205 5 V, AP63203 3.3 V, filtered 3V3A for ADC/VREF |
| MCU and memory | STM32H743ZIT6, 25 MHz HSE, 32.768 kHz LSE, SWD 1.27 mm, RESET/BOOT0 buttons, W25Q128JVS on QUADSPI BK1 |
| Comms | LAN8720A RMII (REF_CLK-out mode, nINT unavailable) + HR911105A jack, CA-IS3062VW isolated CAN (classic CAN 1 Mbit/s, no FD), CA-IS3092W isolated RS485, USB-C FS device, UART header (USART3), 40-pin FPC (RGB565), SPI header, 4 LEDs, 9 V fan output |

## 2.7 Open items found while building (must be resolved before ordering)

1. **MPPT loop and LM5177 compensation are unverified.** RCOMP/CCOMP, IMONOUT RC and RSLOPE are scaled from TI's 1.8 uH example; they need SPICE and bench tuning for 10 uH and the large output capacitance. The IMONOUT limiter network topology is my reading of the datasheet text.
2. **Battery surge clamp.** SMCJ58A clamps at 93.6 V at full surge current, above the LM5177 85 V absolute maximum on VOUT/ISNS. The battery is a stiff source, but load-dump style events need a better clamp or a series element.
3. **Charge-voltage margin.** The hardware cap is 58.66 V nominal (about 58.1-59.2 V with tolerances) against a 58.4 V LiFePO4 16S charge voltage; the firmware CV target comes from the DAC and must stay below the cap.
4. **Inductor** footprint is a placeholder toroid; a real 10 uH, 32 A saturation part still has to be chosen (and fitted by hand or off-board).
5. **Current budget.** Load and inverter switches are 15 A each; the 2 low-side reverse-polarity FETs carry the sum of charge, load and inverter current, so check the thermal budget (an inverter on a 12 V battery is limited to about 180 W per 15 A).
6. **Hot-swap tuning:** RPWR 150 k and CTIMER 470 nF are starting values; the FET SOA at inverter inrush must be checked.
7. **Display pinout:** the 40-pin FPC order is a starting assignment, panels differ; match it to the chosen panel (and its LED driver) before layout.
8. **Board power:** the board is powered from the battery bus, or from USB VBUS (PTC + Schottky into VAUX) when no battery is present; a second diode blocks back-feed into the 9 V buck.
9. RJ45 jack LEDs are not wired (their polarity needs the jack datasheet), CA-IS3062VW pin table comes from the Chinese datasheet v1.04 (re-check against the English one), MCP4728 power-up output values must be confirmed (MPPT_NEN keeps the converter off until firmware sets the DAC).
10. Status 2026-11-10: PCB 195 x 128 mm placed and about 95 % routed (see 04-handover.md). Not yet done: finish routing, DRC clean-up, BOM with LCSC numbers, JLC rotations, fab files, EMC/thermal review.

## 2.8 Next steps

1. You confirm assumptions 1-5 in 01-requirements.md and the MPPT loop approach.
2. I fetch STM32H743 DS12110 and the other datasheets, build the pin map with asserts.
3. SKiDL generator (`hardware/mppt_controller.py`) in sheets: power stage, protection/switches, aux supplies, MCU, memory, comms, display, USB/UART/LEDs, sensing; local symbols for LM5177 and any parts not in KiCad.
4. ERC clean, then placement (4 layers), power pre-route, your autoroute, DRC, fab files.
