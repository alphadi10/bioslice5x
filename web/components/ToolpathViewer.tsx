"use client";

/**
 * Three.js toolpath viewer — the browser-side counterpart of
 * `bioslice5x.visualization.preview.ToolpathViewer`.
 *
 * Renders:
 *  - extrusion moves as colored line segments (by Z height or by wall
 *    shear stress)
 *  - travel moves as a thin grey overlay
 *  - layer-clip scrubber via `clipRangeMax` prop
 *  - optional semi-transparent source mesh (loaded from an ArrayBuffer
 *    via three.js STLLoader)
 *  - build-volume wireframe
 *  - tool-orientation arrows at sampled extrusion points (for 5-axis)
 *
 * Reuses every concept from the PyVista viewer so the desktop and web
 * tools render the same toolpath with the same color semantics.
 */

import {
  useEffect,
  useMemo,
  useRef,
} from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import {
  type Colormap,
  layerColor,
  sample as sampleColormap,
} from "@/lib/colormaps";
import { type KinematicChainInfo, type ParsedMove } from "@/lib/gcode-parser";
import { machineToPart } from "@/lib/kinematics";

export type ColorMode = "z" | "shear" | "layer";

export interface BuildVolume {
  xMm: [number, number];
  yMm: [number, number];
  zMm: [number, number];
}

export interface ToolpathViewerProps {
  moves: ParsedMove[];
  layerIndices: Int32Array;
  /** Show extrusion moves with `clipRangeMin <= layer_index <= clipRangeMax`.
   * Use the same value for both bounds to inspect a single layer. */
  clipRangeMin: number;
  clipRangeMax: number;
  colorMode: ColorMode;
  /** Cell-shear threshold in Pa. When set + colorMode=shear, clamps colormap. */
  cellShearThresholdPa: number | null;
  /** Optional mesh STL bytes for the semi-transparent overlay. */
  meshSTL: ArrayBuffer | null;
  meshOpacity?: number;
  buildVolume: BuildVolume | null;
  /** Kinematic chain config from the G-code META block. The viewer
   * uses this to recover part-frame coordinates from machine-frame
   * XYZ + A + C — without it, 5-axis prints render as degenerate
   * vertical columns. */
  chain: KinematicChainInfo;
  /** Called with the active scalar range whenever the geometry rebuilds,
   * so the parent page can render a legend overlay outside the canvas.
   * Null when colorMode === "layer" (no continuous scalar). */
  onScalarRange?: (
    range: { lo: number; hi: number; unit: string; label: string } | null
  ) => void;
  className?: string;
}

function colormapFor(mode: ColorMode): Colormap {
  return mode === "shear" ? "hot" : "viridis";
}

export function ToolpathViewer({
  moves,
  layerIndices,
  clipRangeMin,
  clipRangeMax,
  colorMode,
  cellShearThresholdPa,
  meshSTL,
  meshOpacity = 0.15,
  buildVolume,
  chain,
  onScalarRange,
  className,
}: ToolpathViewerProps) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<{
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    renderer: THREE.WebGLRenderer;
    controls: OrbitControls;
    extrusion: Line2 | null;
    extrusionMaterial: LineMaterial | null;
    travels: Line2 | null;
    travelMaterial: LineMaterial | null;
    meshOverlay: THREE.Mesh | null;
    buildVolume: THREE.LineSegments | null;
    arrows: THREE.Group | null;
    disposeFns: Array<() => void>;
  } | null>(null);

  // Pre-build line-segment geometries (per render of moves/clipRange).
  const { extrusionGeometry, travelGeometry, sceneCenter, sceneRadius, scalarRange } = useMemo(
    () =>
      buildLineGeometries({
        moves,
        layerIndices,
        clipRangeMin,
        clipRangeMax,
        colorMode,
        cellShearThresholdPa,
        chain,
      }),
    [
      moves,
      layerIndices,
      clipRangeMin,
      clipRangeMax,
      colorMode,
      cellShearThresholdPa,
      chain,
    ]
  );

  // Surface the active scalar range to the parent so it can render an
  // overlay legend. Fires whenever the colour-coded geometry rebuilds.
  useEffect(() => {
    onScalarRange?.(scalarRange);
  }, [scalarRange, onScalarRange]);

  // ---- Scene setup: runs once. ----
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf8fafc);

    const camera = new THREE.PerspectiveCamera(
      60,
      mount.clientWidth / Math.max(1, mount.clientHeight),
      0.1,
      5000
    );
    camera.position.set(80, -80, 80);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    // Three.js coordinate system: Z is up to match RRF G-code.
    scene.up = new THREE.Vector3(0, 0, 1);
    camera.up.set(0, 0, 1);

    // Subtle directional + ambient lighting for the mesh overlay.
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const dir = new THREE.DirectionalLight(0xffffff, 0.5);
    dir.position.set(50, -50, 100);
    scene.add(dir);

    sceneRef.current = {
      scene,
      camera,
      renderer,
      controls,
      extrusion: null,
      extrusionMaterial: null,
      travels: null,
      travelMaterial: null,
      meshOverlay: null,
      buildVolume: null,
      arrows: null,
      disposeFns: [],
    };

    // Animation loop.
    let stopped = false;
    const animate = () => {
      if (stopped) return;
      controls.update();
      renderer.render(scene, camera);
      requestAnimationFrame(animate);
    };
    animate();

    const onResize = () => {
      if (!mount) return;
      camera.aspect = mount.clientWidth / Math.max(1, mount.clientHeight);
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
      // LineMaterial uses screen-space resolution to compute line width;
      // refresh it whenever the canvas resizes so 1.5px stays 1.5px.
      const ref = sceneRef.current;
      if (ref) {
        ref.extrusionMaterial?.resolution.set(mount.clientWidth, mount.clientHeight);
        ref.travelMaterial?.resolution.set(mount.clientWidth, mount.clientHeight);
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      stopped = true;
      window.removeEventListener("resize", onResize);
      const ref = sceneRef.current;
      if (ref) {
        ref.disposeFns.forEach((fn) => fn());
        ref.controls.dispose();
        ref.renderer.dispose();
      }
      if (renderer.domElement.parentElement) {
        renderer.domElement.parentElement.removeChild(renderer.domElement);
      }
      sceneRef.current = null;
    };
  }, []);

  // ---- Update extrusion + travel actors whenever geometry changes. ----
  useEffect(() => {
    const ref = sceneRef.current;
    if (!ref) return;
    const { scene, renderer } = ref;
    const size = new THREE.Vector2();
    renderer.getSize(size);
    const screenRes: [number, number] = [
      size.x > 0 ? size.x : 1,
      size.y > 0 ? size.y : 1,
    ];

    // Replace extrusion. Line2 + LineMaterial gives ribbons whose width
    // scales with screen pixels — `LineBasicMaterial`'s `linewidth` is
    // ignored on every modern WebGL platform (spec mandates 1px), which
    // is the single biggest "feels like an intern wireframe" bug
    // surfaced by the audit. Line2 fixes it for both extrusion and
    // travels.
    if (ref.extrusion) {
      scene.remove(ref.extrusion);
      ref.extrusion.geometry.dispose();
      ref.extrusionMaterial?.dispose();
      ref.extrusion = null;
      ref.extrusionMaterial = null;
    }
    if (extrusionGeometry.positions.length > 0) {
      const geom = new LineGeometry();
      // `LineGeometry.setPositions` expects a flat float array of
      // *per-segment-pair* points (start+end alternating). Our
      // extrusion positions are already in that shape — every 6 floats
      // is one segment.
      geom.setPositions(Array.from(extrusionGeometry.positions));
      geom.setColors(Array.from(extrusionGeometry.colors));
      const mat = new LineMaterial({
        vertexColors: true,
        linewidth: 2.4,
        worldUnits: false,
        transparent: false,
        depthTest: true,
        // `Line2` is a segmented "ribbon" — we don't want any miter / cap
        // on the line endpoints because the geometry is a sparse list of
        // independent segments, not a continuous polyline.
        alphaToCoverage: true,
      });
      mat.resolution.set(screenRes[0], screenRes[1]);
      const line = new Line2(geom, mat);
      line.computeLineDistances();
      line.scale.set(1, 1, 1);
      scene.add(line);
      ref.extrusion = line;
      ref.extrusionMaterial = mat;
    }

    // Replace travels. Thinner + semi-transparent so they read as a
    // visual sidebar, not a competing toolpath.
    if (ref.travels) {
      scene.remove(ref.travels);
      ref.travels.geometry.dispose();
      ref.travelMaterial?.dispose();
      ref.travels = null;
      ref.travelMaterial = null;
    }
    if (travelGeometry.positions.length > 0) {
      const geom = new LineGeometry();
      geom.setPositions(Array.from(travelGeometry.positions));
      const mat = new LineMaterial({
        color: 0xb0b8c4,
        linewidth: 1.0,
        transparent: true,
        opacity: 0.45,
        worldUnits: false,
        depthTest: true,
      });
      mat.resolution.set(screenRes[0], screenRes[1]);
      const line = new Line2(geom, mat);
      line.computeLineDistances();
      scene.add(line);
      ref.travels = line;
      ref.travelMaterial = mat;
    }

    // First-time framing: center camera + controls on the toolpath center.
    if (sceneCenter && sceneRadius > 0) {
      ref.controls.target.set(sceneCenter[0], sceneCenter[1], sceneCenter[2]);
      // Only reset camera position on the very first non-empty render.
      const cam = ref.camera;
      const distNow = cam.position.distanceTo(ref.controls.target);
      if (distNow < 1 || distNow > sceneRadius * 50) {
        const dist = sceneRadius * 3.2;
        cam.position.set(
          sceneCenter[0] + dist,
          sceneCenter[1] - dist,
          sceneCenter[2] + dist
        );
      }
      ref.controls.update();
    }
  }, [extrusionGeometry, travelGeometry, sceneCenter, sceneRadius]);

  // ---- Source-mesh overlay. ----
  useEffect(() => {
    const ref = sceneRef.current;
    if (!ref) return;
    const { scene } = ref;

    if (ref.meshOverlay) {
      scene.remove(ref.meshOverlay);
      ref.meshOverlay.geometry.dispose();
      (ref.meshOverlay.material as THREE.Material).dispose();
      ref.meshOverlay = null;
    }
    if (meshSTL) {
      try {
        const loader = new STLLoader();
        const geometry = loader.parse(meshSTL);
        const material = new THREE.MeshStandardMaterial({
          color: 0x90b4d8,
          transparent: true,
          opacity: meshOpacity,
          metalness: 0.1,
          roughness: 0.8,
        });
        const mesh = new THREE.Mesh(geometry, material);
        scene.add(mesh);
        ref.meshOverlay = mesh;
      } catch (exc) {
        // Mesh-load failures are non-fatal in the desktop viewer too.
        // eslint-disable-next-line no-console
        console.warn("ToolpathViewer: source mesh failed to load:", exc);
      }
    }
  }, [meshSTL, meshOpacity]);

  // ---- Build-volume wireframe. ----
  useEffect(() => {
    const ref = sceneRef.current;
    if (!ref) return;
    const { scene } = ref;

    if (ref.buildVolume) {
      scene.remove(ref.buildVolume);
      ref.buildVolume.geometry.dispose();
      (ref.buildVolume.material as THREE.Material).dispose();
      ref.buildVolume = null;
    }
    // Suppress the build-volume box for 5-axis prints. It lives in
    // machine frame and the toolpath is rendered in part frame for
    // tilt-swivel chains, so the two would float in different spaces.
    const showBuildVolume =
      chain.tiltAxis === null && chain.swivelAxis === null;
    if (buildVolume && showBuildVolume) {
      const [x0, x1] = buildVolume.xMm;
      const [y0, y1] = buildVolume.yMm;
      const [z0, z1] = buildVolume.zMm;
      const box = new THREE.BoxGeometry(x1 - x0, y1 - y0, z1 - z0);
      const edges = new THREE.EdgesGeometry(box);
      const mat = new THREE.LineBasicMaterial({
        color: 0xa1a8b5,
        transparent: true,
        opacity: 0.4,
      });
      const wf = new THREE.LineSegments(edges, mat);
      wf.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
      scene.add(wf);
      ref.buildVolume = wf;
      box.dispose();
    }
  }, [buildVolume, chain]);

  return (
    <div
      ref={mountRef}
      className={className ?? "h-full w-full"}
      data-color-mode={colorMode}
    />
  );
}

// -------------------------------------------------------------------
// Geometry-building helpers (pure, no Three.js scene state).
// -------------------------------------------------------------------

interface LineGeometryArrays {
  positions: Float32Array;
  colors: Float32Array;
}

interface GeometryBundle {
  extrusionGeometry: LineGeometryArrays;
  travelGeometry: LineGeometryArrays;
  sceneCenter: [number, number, number] | null;
  sceneRadius: number;
  /** The active color-mode's resolved scalar range; null when there's
   * no extrusion to colour. Surfaced to the legend overlay. */
  scalarRange: { lo: number; hi: number; unit: string; label: string } | null;
}

interface BuildArgs {
  moves: ParsedMove[];
  layerIndices: Int32Array;
  clipRangeMin: number;
  clipRangeMax: number;
  colorMode: ColorMode;
  cellShearThresholdPa: number | null;
  chain: KinematicChainInfo;
}

function buildLineGeometries({
  moves,
  layerIndices,
  clipRangeMin,
  clipRangeMax,
  colorMode,
  cellShearThresholdPa,
  chain,
}: BuildArgs): GeometryBundle {
  if (moves.length === 0) {
    return {
      extrusionGeometry: { positions: new Float32Array(), colors: new Float32Array() },
      travelGeometry: { positions: new Float32Array(), colors: new Float32Array() },
      sceneCenter: null,
      sceneRadius: 0,
      scalarRange: null,
    };
  }

  // First pass: turn every move's machine-frame endpoint into the
  // part-frame coordinate the print actually lives in. For 3-axis
  // chains the transform is the identity, so flat prints pass through
  // unchanged; for 5-axis conformal prints this is what unfolds the
  // toolpath from a degenerate column at (r, 0, z) back into the
  // actual cylinder geometry.
  const partPts: Array<[number, number, number]> = new Array(moves.length);
  for (let i = 0; i < moves.length; i += 1) {
    partPts[i] = machineToPart(
      moves[i].endXyz,
      moves[i].aDeg,
      moves[i].bDeg,
      moves[i].cDeg,
      chain
    );
  }

  // Pre-compute the scalar range for the active color mode.
  const cmap = colormapFor(colorMode);
  let scalarLo = Infinity;
  let scalarHi = -Infinity;
  if (colorMode === "z") {
    for (let i = 0; i < moves.length; i += 1) {
      if (moves[i].isTravel) continue;
      const z = partPts[i][2];
      if (z < scalarLo) scalarLo = z;
      if (z > scalarHi) scalarHi = z;
    }
  } else if (cellShearThresholdPa !== null) {
    scalarLo = 0;
    scalarHi = cellShearThresholdPa;
  } else {
    for (const m of moves) {
      if (m.isTravel) continue;
      const s = m.wallShearPa ?? 0;
      if (s < scalarLo) scalarLo = s;
      if (s > scalarHi) scalarHi = s;
    }
  }
  if (!Number.isFinite(scalarLo) || !Number.isFinite(scalarHi)) {
    scalarLo = 0;
    scalarHi = 1;
  }
  if (scalarHi - scalarLo < 1e-9) scalarHi = scalarLo + 1;

  const extPositions: number[] = [];
  const extColors: number[] = [];
  const travelPositions: number[] = [];

  // Toolhead position in PART frame, used as the start of each new
  // segment. The first conceptual position is the part-frame origin
  // (G92 effectively zeros all axes at start).
  let cur: [number, number, number] = [0, 0, 0];
  let extIdx = 0;
  let minX = Infinity,
    minY = Infinity,
    minZ = Infinity,
    maxX = -Infinity,
    maxY = -Infinity,
    maxZ = -Infinity;

  for (let i = 0; i < moves.length; i += 1) {
    const move = moves[i];
    const next = partPts[i];

    if (move.isTravel) {
      travelPositions.push(cur[0], cur[1], cur[2], next[0], next[1], next[2]);
    } else {
      const layer = layerIndices[extIdx] ?? 0;
      if (layer >= clipRangeMin && layer <= clipRangeMax) {
        let r: number;
        let g: number;
        let b: number;
        if (colorMode === "layer") {
          [r, g, b] = layerColor(layer);
        } else {
          const scalar =
            colorMode === "z" ? next[2] : move.wallShearPa ?? 0;
          const t = (scalar - scalarLo) / (scalarHi - scalarLo);
          [r, g, b] = sampleColormap(cmap, t);
        }
        extPositions.push(cur[0], cur[1], cur[2], next[0], next[1], next[2]);
        extColors.push(r, g, b, r, g, b);
      }
      extIdx += 1;
    }

    if (next[0] < minX) minX = next[0];
    if (next[0] > maxX) maxX = next[0];
    if (next[1] < minY) minY = next[1];
    if (next[1] > maxY) maxY = next[1];
    if (next[2] < minZ) minZ = next[2];
    if (next[2] > maxZ) maxZ = next[2];

    cur = next;
  }

  // Fall back to the toolpath extent when min/max never advanced (e.g.
  // empty move list, defensive against degenerate inputs).
  if (!Number.isFinite(minX)) {
    minX = -1;
    maxX = 1;
    minY = -1;
    maxY = 1;
    minZ = 0;
    maxZ = 1;
  }
  const sceneCenter: [number, number, number] = [
    (minX + maxX) / 2,
    (minY + maxY) / 2,
    (minZ + maxZ) / 2,
  ];
  const sceneRadius = Math.max(1, Math.max(maxX - minX, maxY - minY, maxZ - minZ) / 2 + 2);

  const scalarRange =
    colorMode === "layer"
      ? null
      : colorMode === "z"
        ? { lo: scalarLo, hi: scalarHi, unit: "mm", label: "Z height" }
        : { lo: scalarLo, hi: scalarHi, unit: "Pa", label: "Wall shear" };

  return {
    extrusionGeometry: {
      positions: new Float32Array(extPositions),
      colors: new Float32Array(extColors),
    },
    travelGeometry: {
      positions: new Float32Array(travelPositions),
      colors: new Float32Array(0),
    },
    sceneCenter,
    sceneRadius,
    scalarRange,
  };
}
