# Bioprinting Requirements for the 5-Axis Slicer

This document translates the biological and material constraints of FRESH/CHIPS extrusion bioprinting into engineering requirements for an open-source 5-axis slicer targeting syringe-based bioprinters. Numerical claims are cited to a specific source; values flagged "approximate" come from secondary/review literature and should be verified against primary data before being hard-coded as defaults.

## 1. Process Overview

**FRESH** (Freeform Reversible Embedding of Suspended Hydrogels) is an embedded extrusion technique developed in the Feinberg lab at CMU. A blunt syringe needle is driven through a bath of densely packed gelatin microparticles that behaves as a Bingham/Herschel-Bulkley plastic: it yields locally around the needle, lets a soft bioink (collagen, fibrin, alginate, dECM, etc.) be deposited along the toolpath, then self-heals behind the needle and supports the freshly extruded filament until it crosslinks (per CMU press release; per "Emergence of FRESH 3D printing as a platform for advanced tissue biofabrication", PMC7889293). Removal is by warming the bath to ~37 C, which melts the gelatin and releases the printed construct (per FRESH support-bath review, PMC7889293).

**CHIPS** (Collagen High-resolution Internally Patterned Scaffolds, per Science Advances 2025, DOI 10.1126/sciadv.adu5905, summarized in the CMU April 2025 press piece) extends FRESH with single-step, multi-material co-deposition of cell-laden bioinks, ECM proteins, and growth factors to fabricate perfusable, vascularized constructs with channels down to ~100 µm diameter (per CMU press release, 2025-04-23). A centimeter-scale pancreatic-like construct produced glucose-stimulated insulin release in vitro (per CMU press release, 2025-04-23).

For the slicer, the operational picture is: multiple temperature-controlled syringes mounted on a 5-axis motion platform deposit different inks into a yield-stress bath, with toolpaths that may need to follow curved anatomical surfaces rather than flat horizontal layers.

## 1.1 Modality Landscape — Why Syringe Extrusion in a Support Bath

BioSlice5X targets one specific cell of a wider bioprinting modality matrix. The choice is deliberate: support-bath extrusion is the only modality with (a) an active open-source hardware ecosystem (Open5X, Voron-derived bioprinters, Replistruder syringe extruders) and (b) a clinically advanced program (FluidForm Bio's T1D CHIPS implant, six-month in vivo efficacy in diabetic SCID Beige mice per FluidForm Bio communications at ADA 85 / IPITA World Congress, July 2025). Other modalities are commercially dominated and out of scope for v1.

| Modality | Native resolution | Cell viability | Open-source hardware? | Slicer fit |
|---|---|---|---|---|
| Inkjet | ~50 µm | Moderate | Limited | Not a target — low-viscosity inks only, poor structural fidelity |
| **Extrusion + support bath (FRESH)** | **~20 µm filament, ~100 µm channels (CHIPS 2025)** | **High (shear-bounded)** | **Yes (Open5X, Voron-bio)** | **Primary target** |
| Laser-assisted (LIFT) | <10 µm | >95% | No | Out of scope — closed commercial systems |
| SLA/DLP photopolymerization | 20–250 µm | >90% | Partial (consumer SLA repurposed) | v0.3+ as sibling `Extruder` Protocol impl; needs `PhotodoseError` analog of `CellViabilityError` |
| Volumetric (CAL / tomographic) | <30 µm | >90% | No | Out of scope — proprietary control software (BIO INX, Readily3D); architectural fork (3D tomographic projection, not 2D layer slicing) |

The article-derived comparison reinforces the slicer's existing scoping decision in `LIMITATIONS.md`: ship the FRESH/CHIPS extrusion path to publication-grade fidelity first; add DLP as a sibling modality only after that path is calibrated against wet-lab data.

## 2. Support Bath Specification

| Property | Value | Source |
|---|---|---|
| Particle material | Gelatin (type A or B) microparticles | PMC7889293 |
| Particle diameter, original FRESH | ~60 µm mean | search result, PMC review |
| Particle diameter, FRESH v2 / CHIPS | sub-25 µm (approximate, reported as "improved versions use smaller particles") | search-derived, verify against primary FRESH v2 paper |
| Rheology | Yield-stress, self-healing (Bingham/Herschel-Bulkley) | PMC7889293 |
| Removal mechanism | Thermal melting at ~37 C | per CMU press release and PMC7889293 |
| Sterility | Bath is autoclaved or aseptically prepared; specific protocol not in abstracts (verify with wet-lab) | open question |

The slicer needs the bath's yield stress and an effective viscosity (or H-B parameters) as inputs to compute the drag force on the needle along the path and to set safe traverse speeds.

## 3. Bioink Material Envelope

Numbers below are typical operating ranges aggregated from the search-cited reviews; treat them as defaults, not specifications. The "Establishing a Bioink Assessment Protocol" paper (ACS Biomater Sci Eng 2025, PMC12001187) and "Insights on shear rheology of inks for extrusion-based 3D bioprinting" (Bioprinting 2021) are the most directly usable primary sources for the slicer's material library.

| Bioink | Typical conc. | Apparent viscosity (Pa·s) at printing shear rates | Rheological fit | Working temp | Notes |
|---|---|---|---|---|---|
| Collagen I (acidified) | 3–10 mg/mL | ~0.1–10 (approximate, shear-thinning) | Power-law n<1; consistency ~80 Pa·s reported with p=0.1 (per search-derived PMC12001187 summary) | 4 C in syringe, gels above ~20 C | Workhorse ink for FRESH/CHIPS (per CMU 2025 press) |
| Fibrin (fibrinogen + thrombin) | 10–50 mg/mL fibrinogen | low, ~0.01–1 | near-Newtonian until thrombin contact | room temp | Crosslinks on contact with thrombin in bath |
| Alginate | 1–5 % w/v | ~1–100 | Power-law shear-thinning, often Herschel-Bulkley with small yield stress (search-derived) | room temp | Ca²⁺ crosslink |
| GelMA | 5–15 % w/v | ~1–100 (strongly temp-dependent) | Herschel-Bulkley; n typically <0.5; "n<0.2 for high printability" (per search of GelMA rheology literature, MDPI/ACS) | 20–37 C, photocrosslinked | Often blended with collagen microparticles for ambient printing (per Galliger 2022, PMC9757590) |
| Decellularized ECM (dECM) | 6–20 mg/mL | ~0.1–10, tissue-source dependent | Power-law shear-thinning | 4 C load, gels at 37 C | Used in CHIPS as one of the co-deposited materials (per CMU 2025 press) |

The slicer's bioink record should carry at minimum: density, consistency index K, flow index n, yield stress τ₀, working/storage temperature, crosslinking modality (thermal, ionic, photo, enzymatic), and per-cell-type maximum allowable wall shear stress.

### 3.1 Bioink Material Categories

Bioinks divide into three categories that drive design tradeoffs visible to the user. The slicer should carry this as a `category` field on each `Bioink` record so the recipe editor and viewer can filter and color-code by category.

| Category | Examples | Strength | Weakness | Slicer implication |
|---|---|---|---|---|
| Natural polymers | Collagen I, gelatin, fibrin, hyaluronic acid, silk | Native ECM mimicry; high bioactivity; cells "recognize" the matrix | Mechanical weakness; lot-to-lot variation | Dominant FRESH inks; calibration provenance is load-bearing — every value needs `calibrated_against` populated |
| Synthetic polymers | PEG, PCL, PLA, PEGDA | Tunable mechanics and degradation; reproducible | Lower inherent bioactivity; usually needs RGD functionalization | Often paired with photopolymerization (PEGDA + LAP at 405 nm) — sibling modality |
| Ceramics / composites | Hydroxyapatite, calcium phosphate, nano-HA / polyamide | Osteogenic; compressive strength | Brittle; not extrusion-friendly without polymer carrier | Bone-tissue niche; out of scope for v1 |

## 4. Cell Viability Constraints

Shear-induced damage in extrusion bioprinting is governed by the wall shear stress in the needle and, separately, by extensional stresses at the die entry (the conical contraction from syringe barrel to needle bore). Both must be bounded.

Threshold landscape, from the review literature surfaced in search:

- A widely cited safety threshold is **wall shear stress ≤ ~5 kPa** for "high cell viability" in extrusion bioprinting; some cell types fail at much lower stress, with **≤ ~1.3 kPa** reported as the conservative bound from rheometer-based viability work (per Rheologica Acta 2025, "Cell viability in extrusion bioprinting", link.springer.com s00397-025-01504-z — search-derived summary).
- A more conservative everyday working number cited in multiple reviews is **wall shear stress under ~1–2 kPa for hiPSC-derived cardiomyocytes and other mechanosensitive primary cells** (approximate, search-derived from MDPI 16/12/436 and PMC9756521 reviews).
- Cell death follows a threshold-then-power-law relationship with shear stress and exposure time, not a hard cliff (per PMC9036289 review).
- Hardy cell lines (HEK293, fibroblasts, MSCs) tolerate the 5 kPa range; stem-cell-derived cardiomyocytes, neurons, β-cells, and hepatocytes do not — bioink-and-cell pairing must be customized (per MDPI Biomimetics 16/12/436 review).

The slicer should therefore treat the wall-shear-stress limit as **a per-cell-type property of the bioink**, not a global constant. The Feinberg group's primary FRESH/CHIPS papers don't publish a single numeric threshold in the abstracts — those defaults need to be tuned against wet-lab viability assays for the specific cell line.

Extensional stress at the needle entry is typically not modeled directly in current open-source slicers, but a conservative envelope is: keep barrel-to-needle area contraction ratio ≤ ~100:1 and avoid abrupt step contractions (per IOPscience 1758-5090/ab7553, "Engineering considerations on extrusion-based bioprinting").

## 5. Resolution & Flow Regime

- FRESH 2019 reported feature resolution **down to ~20 µm at the nozzle** for filaments deposited in the gelatin bath (per Science 2019, DOI 10.1126/science.aav9051, via CMU 2019 coverage; not directly verifiable from the paywalled abstract).
- CHIPS 2025 reports perfusable internal channels **down to ~100 µm diameter** (per CMU press release, 2025-04-23, and Science Advances 2025 DOI 10.1126/sciadv.adu5905).
- Needle gauges in routine FRESH/CHIPS work: **22G (~410 µm ID) down to 30G (~150 µm ID)**, blunt-tipped, typically 0.5–1.5 inch length (per IOPscience 1758-5090/aa8dd8 bioprintability review — search-derived).
- Drive: pneumatic (kPa-range pressures, typically 10–300 kPa for hydrogels in this viscosity band) or positive-displacement (syringe pump, µL/s flow rates). The slicer should support both control modes since CMU's reference platforms and FluidForm Bio's commercial hardware use displacement-based control for repeatability (open question for verification against the CHIPS methods section).

Flow regime is laminar, Reynolds number ≪ 1, so analytical Herschel-Bulkley pressure-drop formulas apply and the slicer can compute pressure, mean velocity, and wall shear in closed form from (K, n, τ₀, needle ID, length, flow rate).

## 6. Multi-Material Coordination Requirements

"Simultaneous" in CHIPS means **multi-syringe co-deposition with coordinated G-code**, not single-needle switching (per CMU press release, 2025-04-23: "combined with multi-material 3D bioprinting of ECM proteins, growth factors, and cell-laden bioinks"). The pancreatic-like construct combined at least three material streams: structural collagen ECM, growth factors, and cell-laden ink.

Operationally this implies the slicer must:

- Treat each syringe as an independent extruder with its own temperature, gauge, bioink, cell payload, and shear-stress budget.
- Support tool-change moves with explicit purge/wipe sequences in the bath.
- Avoid cross-contamination by lifting clear of the deposited region during tool changes — non-trivial in a yield-stress bath because retraction leaves a kerf channel.
- Time-coordinate deposition for materials that crosslink on mixing (e.g. fibrinogen + thrombin).

Practical print typically uses 2–4 materials; the slicer's data model should not hard-cap at 2.

### 6.1 Reference Geometry — CHIPS Pancreatic Construct

The CHIPS pancreatic-like construct is the most fully specified reference recipe in the open literature and a good first-class sample for the slicer:

- **Core**: fibrin (fibrinogen 25 mg/mL nominal) loaded with MIN6 β-cells, ~2,000 islet-equivalents (IEQ) per construct in the FluidForm Bio formulation reported at ADA 85 / IPITA World Congress 2025 (search-derived from FluidForm Bio communications).
- **Shell**: type I collagen, deposited as the structural matrix around the fibrin core, with perfusable channels at ~100 µm diameter (per Shiwarski et al. 2025, DOI 10.1126/sciadv.adu5905).
- **Scale**: centimeter-scale overall construct (per Science Advances 2025 abstract and CMU press 2025-04-23).
- **In vivo behavior**: normal blood glucose maintained for 6 months in diabetic SCID Beige mice; reversion to diabetic state on explant; revascularization by host vessels by day 14 with no fibrotic capsule (per FluidForm Bio ADA 85 / IPITA 2025 communications; primary publication pending — verify against final paper).
- **Cell payload**: MIN6 β-cells in the published in vitro work (per Science Advances 2025); the FluidForm Bio T1D clinical program substitutes human donor islets, with CRISPR-edited hypoimmunogenic iPSC-derived islets as the eventual off-the-shelf path.

For the slicer this is a two-syringe recipe: syringe 0 deposits the fibrin/MIN6 core on a `Region(kind="submesh", name="core")`; syringe 1 deposits the collagen shell on `Region(kind="submesh", name="shell")`. The bath is gelatin microparticles at FRESH v2 sub-25 µm spec. The recipe ships in `samples/chips_pancreatic_recipe.yaml`.

## 7. Sterility & Process Window

The CMU press piece and Science Advances abstract do not specify cleanroom class, exact bath sterilization, or ambient temperature in numerical detail. Reasonable defaults from the broader literature:

- Bath prepared and autoclaved or sterile-filtered; print performed in a biosafety cabinet (open question — verify with wet-lab).
- Bioinks stored at 4 C; collagen kept on ice during loading to delay thermal gelation.
- Ambient print temperature: 20–25 C for most inks, with bath temperature held below the gelatin melt point (often 10–22 C).
- Total print duration: cells tolerate ~1–4 hours in a syringe at low temperature with modest viability loss; longer prints risk settling and viability decline (approximate, search-derived from PMC9756521 review).

The slicer should expose a total-print-duration estimator and warn if it exceeds a user-configurable budget.

## 8. Engineering Requirements for the Slicer

Synthesizing the above into concrete asks:

1. **Per-syringe configuration is mandatory.** Each tool carries: needle gauge (inner diameter, length), bioink record (K, n, τ₀, density, working temperature), cell type with maximum wall shear stress, crosslinking modality, and drive mode (pneumatic kPa or displacement µL/s).
2. **The slicer MUST compute wall shear stress per segment** using the Herschel-Bulkley pressure-drop solution for laminar flow in a cylindrical needle, given the planned flow rate and needle geometry. It MUST refuse to emit G-code where computed wall shear stress exceeds `bioink.cell.max_wall_shear_stress`, raising `CellViabilityError` with the offending segment ID, computed stress, threshold, and the dominant contributing factor (flow rate, gauge, viscosity).
3. **Extensional-stress check at die entry.** Reject configurations where the barrel-to-needle contraction ratio exceeds a user-set bound (default 100:1), or warn loudly.
4. **Bath-drag check.** Compute the lateral force on the needle from the yield-stress bath as a function of traverse speed and depth; clamp feedrate so the needle does not deflect beyond a configurable tolerance, and so the kerf behind the needle is allowed to self-heal before the next adjacent pass.
5. **Multi-material coordination as a first-class concept.** Tool changes are explicit moves with purge volumes, retract-clear paths that minimize bath kerf, and optional dwell for crosslinking.
6. **Non-planar / 5-axis paths are the point, not an afterthought.** FRESH already supports continuous curved-Z deposition for thin curved geometries — tracheas, heart valve leaflets, intervertebral discs, corneas — and the open-source Bioprinting community has published explicit non-planar slicing for FRESH (per Bioprinting 2022, "Non-planar embedded 3D printing for complex hydrogel manufacturing", S2405886622000525, and Rheolution 2022 commentary). The slicer's geometric core MUST treat planar slicing as a degenerate case of conformal slicing on a 5-axis kinematic, not as the primary mode.
7. **Bath model is a global resource.** The slicer needs the bath's yield stress, particle size, and effective viscosity. Minimum feature size and minimum inter-pass spacing are derived from particle diameter (rule of thumb: features ≥ 2–3× particle diameter; verify against FRESH resolution paper PMC review).
8. **Print-duration budget.** Surface estimated total time and viability-loss curve per cell type; warn on overrun.
9. **Deterministic, reviewable output.** G-code (or equivalent) must be plain-text, diff-friendly, and carry comment annotations naming the bioink, computed wall shear, and any user overrides per segment — bioprinting is regulated-adjacent and traceability matters.
10. **Open-source bioink and cell library.** Ship with seeded defaults for collagen I, fibrin, alginate, GelMA, dECM, and a small catalog of cell-type shear limits; make it trivially user-editable since values vary by lab.

## 8.1 Regulatory Context — FDA NAM Directive (April 2025)

The FDA's April 2025 directive phasing out mandatory animal testing for certain drug applications in favor of human-based New Approach Methodologies (NAMs) — explicitly including bioprinted tissues — is the single most consequential regulatory shift for the bioprinting field's commercial trajectory (per FDA April 2025 announcement, summarized in industry press 2025-Q2; verify against the final FDA guidance document). For BioSlice5X this implies one concrete deliverable beyond the v0.1.0 surface:

- **`SliceResult.regulatory_report()`** — a Markdown summary suitable as an appendix in a NAM submission, listing per-bioink calibration provenance, per-cell-payload viability margin (computed vs threshold), max observed wall shear per syringe, bath calibration provenance, and the SHA of the source mesh + recipe + profile. This is a v0.1.1 deliverable filed in `LIMITATIONS.md`.

Implantable bioprinted constructs remain a Class III combination-product path (FDA PMA, EMA equivalent, NMPA, TGA — no harmonized standard exists as of 2025-Q2 per FDA / IMDRF public materials). The slicer's role is to make the calibration story auditable; it is not, and should not be, a regulatory submission tool.

## 9. Open Questions / Things to Verify with Wet-Lab Experts

- Exact FRESH v2 / CHIPS gelatin microparticle size distribution and yield stress (the 60 µm number is from the original 2015 paper; CHIPS uses a finer bath but the abstract doesn't quote a value).
- Whether CHIPS drives syringes pneumatically or via displacement, and the actual pressure/flow ranges used in the Science Advances 2025 paper.
- Numeric wall-shear-stress limits the Feinberg group uses internally for the cell types in CHIPS (β-cells, endothelial cells, fibroblasts) — abstracts don't quote these.
- Bath sterilization protocol and BSC class for cell-laden prints.
- Maximum acceptable print duration for the specific cell payloads in CHIPS.
- Whether non-planar paths in FRESH are routinely produced via a slicer or hand-authored — and which open-source toolchain (if any) the Feinberg lab uses today, to avoid reinventing what FluidForm Bio may already be shipping.
- Crosslinking-on-mixing edge cases (fibrin, alginate) — what dwell times and purge volumes does the Feinberg lab use between tool changes?

## Sources

- [CMU College of Engineering: FRESH bioprinting brings vascularized tissue one step closer (2025-04-23)](https://engineering.cmu.edu/news-events/news/2025/04/23-bioprinting-tissue.html)
- [Science 2019, FRESH (Lee et al.), DOI 10.1126/science.aav9051](https://www.science.org/doi/10.1126/science.aav9051)
- [Science Advances 2025, CHIPS (Shiwarski et al.), DOI 10.1126/sciadv.adu5905](https://www.science.org/doi/10.1126/sciadv.adu5905)
- [Emergence of FRESH 3D printing as a platform for advanced tissue biofabrication (PMC7889293)](https://pmc.ncbi.nlm.nih.gov/articles/PMC7889293/)
- [Cell viability in extrusion bioprinting (Rheologica Acta 2025)](https://link.springer.com/article/10.1007/s00397-025-01504-z)
- [An Overview of 3D Bioprinting Impact on Cell Viability (MDPI Biomimetics 2025)](https://www.mdpi.com/2079-4983/16/12/436)
- [Engineering considerations on extrusion-based bioprinting (Biofabrication, IOPscience)](https://iopscience.iop.org/article/10.1088/1758-5090/ab7553)
- [Proposal to assess printability of bioinks for extrusion-based bioprinting (Biofabrication)](https://iopscience.iop.org/article/10.1088/1758-5090/aa8dd8)
- [Establishing a Bioink Assessment Protocol: GelMA and Collagen (ACS Biomater Sci Eng 2025, PMC12001187)](https://pmc.ncbi.nlm.nih.gov/articles/PMC12001187/)
- [Extracellular Matrix Microparticles Improve GelMA Bioink Resolution at Ambient Temperature (Galliger 2022, PMC9757590)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9757590/)
- [Non-planar embedded 3D printing for complex hydrogel manufacturing (Bioprinting 2022)](https://www.sciencedirect.com/science/article/abs/pii/S2405886622000525)
- [A review on cell damage, viability, and functionality during 3D bioprinting (PMC9756521)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9756521/)
- FluidForm Bio T1D preclinical data — ADA 85th Scientific Sessions (Chicago, July 2025) and IPITA World Congress (Pisa, July 2025), search-derived summary; primary peer-reviewed publication pending.
- FDA April 2025 directive on New Approach Methodologies (NAMs) — phase-out of mandatory animal testing for certain drug applications, search-derived from FDA April 2025 announcement and industry coverage. Verify against final guidance.
- Stanford Marsden / Skylar-Scott labs, *Science* 2025 — 200× faster algorithmic vascular tree generation at organ scale (search-derived summary; verify against primary paper).
- Wyss Institute SWIFT / co-SWIFT — Sacrificial Writing Into Functional Tissue (search-derived; Skylar-Scott et al., *Science Advances* 2019 for SWIFT primary).
- 3DBio Therapeutics / PrintBio AuriNovo™ Phase 1/2a clinical trial — patient-matched auricular cartilage implant, March 2022 first-in-human (search-derived from 3DBio Therapeutics 2022 press; verify against ClinicalTrials.gov entry).
