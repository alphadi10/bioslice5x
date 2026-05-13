; ============================================================
; BioSlice5X — rotary sign-verification commissioning sequence
; ============================================================
;
; Purpose:
;   Confirm that the physical rotation direction of each rotary
;   axis matches the right-hand-rule convention BioSlice5X assumes
;   when it emits G-code. Run this BEFORE any cell-laden print on a
;   freshly built or freshly re-flashed Open5X (or Voron / Jubilee /
;   any tilt-swivel) machine.
;
;   The sequence is bath-safe by construction: no bioink leaves the
;   nozzle, Z stays well clear of the build plate the entire time,
;   and every rotary command is small (±15°) so a wrong-sign axis
;   cannot crash into a hard stop. The only thing that moves
;   physically is the bed; the syringe is parked.
;
; Procedure:
;   1. Mark the +X edge of the rotary plate with a piece of tape.
;   2. Make sure the tilt yoke is at a known horizontal orientation
;      (consult your machine's home position; on Open5X Prusa the
;      yoke is roughly horizontal when A = 0).
;   3. Load this file into RepRapFirmware's web UI (or push via
;      `M28`/`M29` over USB) and click Print.
;   4. Watch the bed and write down the observed direction for each
;      labelled move below.
;
; Expected observation (right-hand rule):
;   - Tilt move "tilt_positive":
;       * Open5X Prusa (tilt = A about X): bed-top tilts from +Z toward +Y
;         (i.e. the front of the bed dips down, the back rises).
;       * Open5X Voron / Jubilee (tilt = B about Y): bed-top tilts from +Z
;         toward +X (i.e. the left edge dips, the right edge rises).
;   - Swivel move "swivel_positive":
;       * The taped +X edge of the plate rotates toward +Y (counter-
;         clockwise as viewed from above).
;
; If your machine moves the OPPOSITE direction for either axis:
;   - The hardware reverses one rotary sign. Open5X built with stock
;     stepper drivers and the upstream M569 settings often DOES match
;     right-hand rule; built with reversed drivers (or with `S1`
;     swapped to `S0` in the operator's config.g) it does not.
;   - Fix in the BioSlice5X profile YAML by setting `invert: true`
;     on the affected axis. No kinematics code change required.
;     See docs/OPEN5X_NOTES.md §2 for the rationale.
;
; Sign-check rotation amounts are kept small (±15° tilt, ±30° swivel)
; so the bed motion is visible-but-recoverable even on a printer with
; aggressive endstops. The Z stays at 30 mm above home throughout.
;
; ============================================================

G21       ; mm units
G90       ; absolute positioning
M83       ; relative extrusion (no E is actually emitted below;
          ;   keeping the mode consistent with print files)
M564 S0   ; allow movement past axis limits (set by config.g; included
          ;   here defensively in case operator's config disables it)

; ---- Park: raise Z, centre XY, return rotaries to zero. ----
G1 Z30 F750            ; raise nozzle clear of bed
G1 X0 Y0 F6000         ; centre XY over the rotary plate
M400                   ; finish moves before issuing rotary command
G92 A0 B0 C0 U0 V0     ; declare the current rotary pose as zero on
                       ;   every letter the four shipped profiles use
                       ;   (A: Prusa tilt; B: Voron/Jubilee tilt;
                       ;    C: swivel on A+C and B+C profiles;
                       ;    U/V: current upstream firmware variant).
                       ; The unused letters are a no-op on a given
                       ;   firmware; emitting them here lets the same
                       ;   commissioning file work across builds.

; ============================================================
; ; tilt_positive — tilt joint to +15°
; ============================================================
; A axis machines (Open5X Prusa) — A15
; B axis machines (Voron / Jubilee) — B15
; U axis machines (current upstream Prusa) — U15
; Emit all three letters on the same line; non-existent axes are
; ignored by RRF.
G1 A15 B15 U15 F1200   ; small tilt — observe direction
M400
G4 P2000               ; pause 2s for human observation

; ============================================================
; ; tilt_negative — tilt joint to -15°
; ============================================================
G1 A-15 B-15 U-15 F1200
M400
G4 P2000

; ============================================================
; ; swivel_positive — swivel joint to +30°
; ============================================================
G1 A0 B0 U0 F1200      ; first, return tilt to zero
G1 C30 V30 F2400       ; then sweep swivel; observe taped edge
M400
G4 P2000

; ============================================================
; ; swivel_negative — swivel joint to -30°
; ============================================================
G1 C-30 V-30 F2400
M400
G4 P2000

; ---- Return to home, motors off. ----
G1 A0 B0 U0 C0 V0 F2400
M400
M84                    ; disable steppers — bed will free-spin
                       ;   slightly under gravity; that's expected.

; ============================================================
; ; If everything moved as expected:
; ;   You're good. The default `invert: false` flags in your active
; ;   profile YAML match your hardware. Proceed to a first dry-run
; ;   print via `uv run bioslice5x slice ... && bioslice5x dry-run`.
; ; If a sign was reversed:
; ;   Open src/bioslice5x/profile/library/<your_profile>.yaml and set
; ;   `invert: true` on the affected axis. Re-run this commissioning
; ;   file to confirm. No kinematics code change is needed.
; ============================================================
