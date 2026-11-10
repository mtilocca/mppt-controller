# Handover: MPPT controller PCB (state at end of 2026-11-09 session)

Repo: `~/mppt-controller` (git, branch `main`, no remote). Work dir for everything below: `hardware/`.
KiCad scripts run with `flatpak run --command=python3 org.kicad.KiCad <script>` (KiCad 10 flatpak). Run `kicad-cli` the same way.

## 1. Where we are

| Area | State |
|---|---|
| Requirements / architecture | Done (`docs/01`, `02`, `03`). Open design items in `02-architecture.md` section 2.7 are still open. |
| Schematic (SKiDL -> KiCad) | Done, ERC 0 errors, 350 parts / 290 nets |
| Placement | Done on a **195 x 128 mm** 4-layer board (was 175 x 120; `place_pcb_175.py` is the old version) |
| Routing | ~95 % done, see section 2 |
| Pours / stitching | Done by `post_route.py` (GND on F/B + In1 plane, high-current copper areas) |
| 3D models | Placeholders for L1, L2, F2, J11; real EasyEDA STEP for J8 (RJ45). See section 3 |
| Fab outputs (BOM/LCSC, CPL, gerbers, drill) | **Not started** |

Last committed DRC state (before today's terminal-block flip): 3 clearance, 4 starved thermal, 141 unconnected
(80 GND SMD pads without room for a via, about 60 single signal/power links).

## 2. Update 2026-11-10 (supersedes the numbers above)
Terminal flip is done and its nets re-routed; `post_route.py` was fixed (it crashed/accumulated stale GND vias because SWIG proxies go stale after `Remove()`; it now saves and reloads). `fix_gnd.py` adds via+stub for GND pads (slow, ~8 min). **DRC: 0 violations, 133 unconnected** (72 GND pads with no room for a via, 61 signal/power links: I2C_SCL x7, BAT_BUS x3, 3V3 x2, INV_UVLO x2, INA_ALERT x2, ETH_NRST x2, LCD_*, etc.). `route_power.py` could not close BAT_BUS 4, INV_OUT 2, LOAD_OUT 2, VIN_PWR 2: fine-pitch INA228/LM5069 pins. Next: hand-route those in KiCad.

## 2b. Older notes (before 2026-11-10)

1. **Terminal blocks J1-J4 (MKDS 5.08) were mounted backwards** (wire entry facing the board interior). Fix applied:
   - `place_pcb.py`: `place_edge` adds 180 deg for MKDS footprints (so a rebuild is right too).
   - On the current board: `flip_term.py` rotated J1-J4 180 deg about their courtyard centre and `strip_near.py J1,J2,J3,J4 3 _before_flip.kicad_pcb` removed the tracks that touched the old pad positions. Backup of the board before the flip: `hardware/_before_flip.kicad_pcb`.
   - After the flip the nets on J1-J4 (PV_RAW, BAT_RAW, BAT_NEG, LOAD_OUT, INV_OUT) must be re-routed. `route_power.py ... PV_RAW BAT_RAW BAT_NEG LOAD_OUT INV_OUT` was **still running in the background when the session stopped**; it overwrites `mppt_controller.kicad_pcb` on completion. Its log is `_rp3.log`. Check `ps aux | grep route_power`; if it is not finished/saved, re-run it (a few minutes). Known: `INV_OUT: no path from piece near 96.9,68.8`.
   - J5, J9, J10 (PT-1,5 3.5 mm) were judged correct; verify in the 3D viewer.
   - J8 (RJ45), J11 (USB-C), J13 (FPC) orientation not re-checked after the user's remark that "some connectors are mounted the other way around".
2. After the router finishes: `post_route.py mppt_controller.kicad_pcb --no-import` (refills the zones; the zone fills are stale after the flip), then DRC.
3. Commit (`git add -A hardware docs 3d`).

## 3. Known issues / to do, in order

### 3.1 Finish routing (user asked for it to be done by hand)
- Re-run DRC (`kicad-cli pcb drc --format json --severity-error`) and list the unconnected items per net.
- Remaining open nets (before the flip): GND x80, I2C_SCL x7, BAT_BUS x3, 3V3 x2, INV_UVLO x2, INV_OUT x2, LOAD_OUT x2, INA_ALERT x2, ETH_NRST x2, plus single links: SWCLK, NRST, BOOT0, OSC_OUT, LCD_R3/R4/R6/R7, LCD_G3/G5/G7, LCD_B4/B5/B6/B7, LCD_HSYNC, LCD_CLK, LED1, TOUCH_CS, SPI_SCK/DC, MPPT_NEN, LOAD_NEN/PGD, INV_PGD/FAULT/REMOTE, CHG_SNS_N, LO1_G_IC, VIN_PWR.
- The automatic routers are out of steam: Freerouting left ~177 items on the 195 x 128 board; `route_power.py --rest` fails on most. Real options:
  - route the remaining links manually in KiCad (about 60 non-GND, mostly single connections), and/or
  - move the parts around U17 (STM32) / U2 (LM5177) to open space, then re-run the pipeline, and/or
  - give the 80 GND pads a via-in-pad / short stub to the In1 plane (`fix_gnd.py` only found room for 4 of 23; most need a neighbouring part moved).
- High-current nets must keep the wide copper (HC zones from `post_route.py`): BAT_BUS, LOAD_OUT, INV_OUT, VIN_PWR, PV_*, SW1/SW2, VOUT, BAT_*.

### 3.2 DRC clean-up
- 3 clearance (SPI_SCK stub tracks next to the GND pour; GND via next to the HC_BAT_BUS area), 4 starved thermal (GND PTH pads on J6/J7/J12), silkscreen, edge clearance. Delete or widen the 0.1 mm SPI_SCK stubs.

### 3.3 3D models
- **RJ45 J8 sits about 3 mm too far back** (user screenshot, 2026-11-09): the body should move toward the board edge so its front face is flush with / just past the shield-tab holes. Model offset is in `make_3d.py` (J8 block, `m_Offset = (4.44, 2.4, 0)`). Try `y = 5.4` (or `-0.6` if the KiCad offset sign is the other way) and check with
  `kicad-cli pcb render --side top --perspective --rotate "-55,0,-90" --zoom 4`. The STEP is `3d/J8_HR911105A.step` (LCSC C12074, from EasyEDA). Its colour is plain white; that is how the vendor model is.
- L1 (toroid), L2 (SRP1245A), F2 (blade fuse holder), J11 (USB-C) are generated boxes (`3d/*.wrl`). Replace by real STEP models if wanted; `~/Downloads/ProtoFlow Parts/C165948__*/` has a USB-C `TYPE-C-31-M-12` STEP that matches J11 (needs alignment).
- `make_3d.py` must be re-run after anything that regenerates the board (`rebuild.sh`).

### 3.4 Open design items (see `02-architecture.md` 2.7)
Compensation values (LM5177 and MPPT loop need bench validation), battery TVS clamp 93.6 V vs LM5177 85 V abs max, charge-voltage margin, real inductor part for L1, 15 A switch limits, hot-swap (LM5069) tuning, display pinout/backlight vs the actual panel datasheet (40-pin AT043TN24-style is unverified), CA-IS3062W English datasheet check, RJ45 LEDs unwired.

### 3.5 Fab prep (not started)
JLCPCB 4-layer stackup and design rules, silkscreen/fiducials, BOM with LCSC numbers (use the `kicad-happy:bom` / `jlcpcb` skills), CPL with rotation corrections, gerbers + drill, update `docs/` and the memory note, final `kicad-cli` DRC + ERC.

## 4. Pipeline cheat sheet (all in `hardware/`)

```
BOARD_W=195 BOARD_H=128 bash rebuild.sh        # schematic -> netlist -> PCB -> placement -> setup (destroys routing!)
route_power.py PCB [NET ...] [--rest]          # own A* router: HC nets + rails (full run ~30 min); NET names = only those
export_dsn.py PCB _route2.dsn --phase2         # DSN for Freerouting, power tracks locked, GND detached
../_tools/freerouting/full/freerouting-2.5.0-linux-x64/bin/freerouting --gui.enabled=false -de _route2.dsn -do _route2.ses -mp 3
        # ~35 min; use timeout > 55 min or no SES is written; kill by PID, never `pkill -f`
import_ses.py PCB _route2.ses                   # NOTE: drops the existing power tracks ...
merge_tracks.py NEW OLD                        # ... so copy the missing ones back from the pre-import board
post_route.py PCB --no-import                  # GND pours, stitching vias, HC copper areas, zone refill
make_3d.py PCB                                 # 3D models
fix_gnd.py PCB drc.json                        # via + stub for unconnected GND pads (conservative)
flatpak run --command=kicad-cli org.kicad.KiCad pcb drc --format json --severity-error -o drc.json PCB
render.sh / kicad-cli pcb render              # PNG / 3D render (write output into hardware/, not /tmp: the flatpak cannot see the scratchpad)
```

Gotchas: SWIG proxies go stale after `board.Remove()` (collect plain data first, remove by uuid); compare nets by name, not with `==`;
SKiDL `Net(name)` makes a new net each call (use `N(name)`); zone fills are stale after any copper change, always refill;
`rebuild.sh` wipes all routing, so commit before it.

## 5. Files worth knowing
`hardware/mppt_controller.py` (generator), `place_pcb.py` (placement; edge parts in `EDGE_PARTS`, regions in `REGION`), `setup_board.py` (net classes, planes, isolation keep-outs for CAN/RS485),
`netdump.py` (net inspector), `_ds/` (datasheets), `_tools/freerouting/` (Freerouting 2.5.0 with bundled JRE), `3d/` (3D models), `_dl/` (EasyEDA downloads).
Intermediate boards/logs: `_before_flip.kicad_pcb`, `_after_power.kicad_pcb`, `_before_ses.kicad_pcb`, `_rp3.log`, `_route4.log`, `_drc*.json/txt`.
