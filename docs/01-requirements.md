# 1. Requirements (draft, 2026-11-07)

MPPT solar charge controller with an STM32H7 supervisor, built for JLCPCB fabrication. Reuses the workflow of `~/sprinkler-valve-controller` (SKiDL generator, label-only schematic, placement script, autoroute, JLC fab package).

| ID | Requirement |
|----|-------------|
| F1 | PV input 0-48 V DC, up to ~10 A |
| F2 | Battery 12-48 V nominal packs (12/24/36/48 V). A "48 V" LiFePO4 or Li-ion pack charges to 54-58.8 V, so the power stage is rated 60 V continuous |
| F3 | MPPT charging (CC/CV, voltage-based MPPT), PV may be below or above the battery voltage: 4-switch buck-boost |
| F4 | Load output 12-48 V = switched battery bus: current limit, overcurrent trip, low-voltage disconnect, current sense |
| F5 | Inverter feed: fused, switched DC output from the battery bus with pre-charge, plus a control port (remote ON/OFF out, fault/status in). The 220 V AC inverter itself is external |
| F6 | MCU: STM32H743 (LQFP-144 ZIT6), 2 MB flash, 1 MB RAM |
| F7 | External 16 MB (128 Mbit) QSPI flash for logs, settings, GUI assets, firmware staging |
| F8 | RS485 (isolated), CAN (FDCAN, isolated), Ethernet via RJ45 (RMII, 10/100) |
| F9 | Display: 40-pin FPC for RGB/LTDC TFT with backlight PWM and touch I2C, plus SPI header for small OLED/TFT |
| F10 | USB-C (USB device: DFU programming, CDC console) and a UART header (3V3 TTL: console and ROM-bootloader fallback), SWD header |
| F11 | 4 status LEDs driven by the MCU |
| F12 | Measure PV V/I, battery V/I, load V/I, inverter-feed I, temperatures (NTC) |

## Assumptions (please confirm)

1. "RJ45" = Ethernet 10/100 (LAN8720A + magnetics-integrated jack). If you meant a second RS485/CAN daisy-chain connector, say so.
2. RS485 and CAN are galvanically isolated from the power stage and MCU (field wiring on long cables).
3. Battery chemistry/setpoints are set in firmware (profiles); the hardware OVP/OCP limits are fixed by resistor values.
4. Board size ~140 x 100 mm, 4 layers, 2 oz outer copper, SMT on top, large parts and terminals through-hole or hand-soldered.
5. Zephyr RTOS firmware, as on the valve controller.
