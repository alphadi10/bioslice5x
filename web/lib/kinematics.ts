/**
 * Web-side inverse kinematic transform.
 *
 * Mirrors `bioslice5x.kinematics.canonical.machine_to_part_xyz` exactly:
 * forward is `R_tilt @ R_swivel @ part = machine`, so the inverse is
 * `part = R_swivel⁻¹ @ R_tilt⁻¹ @ machine`. The viewer applies this on
 * every move's machine-frame endpoint to recover the part-frame
 * coordinate the print actually lives in — without it, conformal
 * `wrap_axis=z` prints render as a degenerate vertical column at
 * machine (r, 0, z) because the toolhead doesn't translate, only the
 * bed rotates underneath.
 */

import type { KinematicChainInfo } from "@/lib/gcode-parser";

type Mat3 = readonly [
  readonly [number, number, number],
  readonly [number, number, number],
  readonly [number, number, number],
];

function rotationMatrix(axis: "x" | "y" | "z" | null, rad: number): Mat3 {
  if (axis === null) {
    return [
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
    ];
  }
  const c = Math.cos(rad);
  const s = Math.sin(rad);
  if (axis === "x") {
    return [
      [1, 0, 0],
      [0, c, -s],
      [0, s, c],
    ];
  }
  if (axis === "y") {
    return [
      [c, 0, s],
      [0, 1, 0],
      [-s, 0, c],
    ];
  }
  // axis === "z"
  return [
    [c, -s, 0],
    [s, c, 0],
    [0, 0, 1],
  ];
}

function mulMatVec(m: Mat3, v: readonly [number, number, number]): [number, number, number] {
  return [
    m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
    m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
    m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
  ];
}

/**
 * Recover the part-frame XYZ from a machine-frame point + the joint
 * angles that produced it. For 3-axis chains (no rotary joints) this
 * is the identity, so flat prints pass through unchanged.
 *
 * Inputs:
 *   machine: machine-frame point in mm, from the G1's X/Y/Z tokens
 *   aDeg, cDeg: rotary tokens as emitted (already include the
 *     profile's invert flag). null when the chain doesn't use that axis.
 *   chain: kinematic chain config from the G-code META block.
 */
export function machineToPart(
  machine: readonly [number, number, number],
  aDeg: number | null,
  cDeg: number | null,
  chain: KinematicChainInfo
): [number, number, number] {
  // No rotary chain → identity transform.
  if (chain.tiltAxis === null && chain.swivelAxis === null) {
    return [machine[0], machine[1], machine[2]];
  }

  // Re-derive canonical joint angles (the slicer's internal radians)
  // from the emitted G-code letters. The postprocessor applied
  // `deg = canonical_deg * (invert ? -1 : 1)`, so we invert that.
  const deg2rad = (d: number) => (d * Math.PI) / 180;
  const tiltRad =
    aDeg !== null && chain.tiltAxis !== null
      ? deg2rad(chain.tiltInvert ? -aDeg : aDeg)
      : 0;
  const swivelRad =
    cDeg !== null && chain.swivelAxis !== null
      ? deg2rad(chain.swivelInvert ? -cDeg : cDeg)
      : 0;

  // part = R_swivel⁻¹ @ R_tilt⁻¹ @ machine.  Invert by negating angle.
  const rTiltInv = rotationMatrix(chain.tiltAxis, -tiltRad);
  const rSwivelInv = rotationMatrix(chain.swivelAxis, -swivelRad);
  const afterTilt = mulMatVec(rTiltInv, machine);
  return mulMatVec(rSwivelInv, afterTilt);
}
