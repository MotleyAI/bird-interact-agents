# archeology — KB entries not encoded as model entities

The auto-FK joins in this DB go child → parent. Each per-aspect scan
table (`scanpointcloud`, `scanspatial`, `scans`, `scanmesh`,
`scanprocessing`, `scanenvironment`, `scanfeatures`, `scanregistration`,
`scanqc`, `scanconservation`) joins to its natural parents (some subset
of `projects`, `personnel`, `sites`, `equipment`). They do **not**
auto-resolve peer-to-peer references between two child tables that
share a parent (e.g. `scanpointcloud` ↔ `scanspatial` both via
`projects`, or `scanmesh` ↔ `scanenvironment` both via `equipment`/
`sites`) because neither holds an FK to the other.

Composite metrics that span multiple peer scan tables can't be inlined
as a single `Column.sql` — they need a **multistage / query-backed
model** (R-MULTISTAGE) that joins each peer table to the shared parent
separately and then composes. Per the skill, such composites are
deferred to the W4b refinement pass (or to query-time multistage by the
agent).

The single-host calculations and predicates below are encoded:

- **scanpointcloud:** SRI (#0), SCE (#1), SQS (#3), High Resolution
  Scan (#10), Comprehensive Coverage (#11), Premium Quality Scan (#12),
  value-illustrations for ScanResolMm (#20), PointDense (#21), NoiseDb
  (#22), CoverPct (#23).
- **scanmesh:** MCR (#4), TDI (#5), MFS (#6), High Fidelity Mesh (#13),
  Mesh Quality Classification (#53), value-illustration for
  GeomDeltaMm (#24).
- **scanenvironment:** ESI (#7), Optimal Scanning Conditions (#15),
  ECCS (#50).
- **scanregistration:** Registration Quality Threshold (#18),
  value-illustration for LogMethod (#28).
- **scanconservation:** Degradation Risk Zone (#14), Risk Zone
  Category (#52), CPI (#35) and its PS / AF / TS components,
  Conservation Emergency (#42), value-illustration for StructState (#26).
- **sites:** value-illustrations for PhaseFactor (#25) and GuessDate (#29).
- **scanprocessing:** value-illustration for FlowStage (#27).

The KB ids documented below are the deferred ones.

## KB 2 — Point Cloud Density Ratio (PCDR)

Reason: TotalPts and CloudDense live on `scanpointcloud`; AreaM2 lives
on `scanspatial`. Both are children of `projects` / `personnel`; no
direct FK between them. Status: deferred to W4b R-MULTISTAGE encoding
(join scanpointcloud↔scanspatial through projects+personnel).

## KB 8 — Processing Efficiency Ratio (PER)

Reason: GBSize on `scans`, TotalPts on `scanpointcloud`, FlowHrs +
ProcCPU + ProcGPU on `scanprocessing`. Three peer tables. Status:
deferred to W4b R-MULTISTAGE encoding.

## KB 9 — Archaeological Documentation Completeness (ADC)

Reason: SQS (`scanpointcloud`), MFS (`scanmesh`), SCE
(`scanpointcloud`), NoiseDb (`scanpointcloud`). MFS is on a peer
table (`scanmesh`). Status: deferred to W4b R-MULTISTAGE.

## KB 16 — Digital Conservation Priority

Reason: classification combining Degradation Risk Zone (encoded),
GuessDate, TypeSite, and Premium Quality Scan (`scanpointcloud`).
Cross-peer (scanconservation + scanpointcloud, also `Rare`/`Unique`
TypeSite values that don't appear in the data). Status: deferred —
cascades through Premium Quality Scan when joined cross-peer.

## KB 17 — Processing Bottleneck

Reason: PER < 0.5. Depends on PER (KB #8, deferred). Status: deferred
— cascades from KB #8.

## KB 19 — Full Archaeological Digital Twin

Reason: Premium Quality Scans (#12) AND High Fidelity Mesh (#13) AND
Registration Quality Threshold (#18) AND ADC > 85 (#9). Spans
scanpointcloud + scanmesh + scanregistration + ADC (deferred). Status:
deferred to W4b R-MULTISTAGE.

## KB 30 — Scan Time Efficiency (STE)

Reason: SQS, CoverPct (`scanpointcloud`) and SpanMin, ScanCount
(`scans`). Cross-peer (scanpointcloud + scans). Status: deferred to
W4b R-MULTISTAGE.

## KB 31 — Environmental Impact Factor (EIF)

Reason: SQS (`scanpointcloud`) / (ESI (`scanenvironment`) + 10) * 100.
Cross-peer. Status: deferred to W4b R-MULTISTAGE.

## KB 32 — Feature Extraction Efficiency (FEE)

Reason: TraitCount + ArtiCount (`scanfeatures`) and PCDR (KB #2,
deferred) + CloudDense (`scanpointcloud`). Cross-peer plus depends on
deferred PCDR. Status: deferred to W4b R-MULTISTAGE.

## KB 33 — Registration Accuracy Ratio (RAR)

Reason: ScanResolMm (`scanpointcloud`) and LogAccuMm + ErrValMm
(`scanregistration`). Cross-peer (both share `projects` + `personnel`
parents but no peer-FK). Status: deferred to W4b R-MULTISTAGE.

## KB 34 — Spatial Density Index (SDI)

Reason: TotalPts, PointDense, CloudDense (`scanpointcloud`) and AreaM2
(`scanspatial`). Cross-peer. Status: deferred to W4b R-MULTISTAGE.

## KB 36 — Mesh-to-Point Ratio (MPR)

Reason: FacetVerts, MCR (`scanmesh`) and TotalPts (`scanpointcloud`).
Cross-peer (scanmesh joins to equipment+sites; scanpointcloud joins to
projects+personnel — no shared parent through one FK hop). Status:
deferred to W4b R-MULTISTAGE.

## KB 37 — Processing Resource Utilization (PRU)

Reason: FlowHrs, ProcCPU, ProcGPU (`scanprocessing`) and GBSize
(`scans`) and FacetVerts (`scanmesh`). Three-way peer-join. Status:
deferred to W4b R-MULTISTAGE.

## KB 38 — Digital Preservation Quality (DPQ)

Reason: ADC (#9, deferred) + MFS (`scanmesh`) + RAR (#33, deferred) +
SCE (`scanpointcloud`) + ErrValMm (`scanregistration`) + ScanResolMm
(`scanpointcloud`). Multi-peer + cascades from deferred ADC/RAR.
Status: deferred to W4b R-MULTISTAGE.

## KB 39 — Equipment Effectiveness Ratio (EER)

Reason: SQS (`scanpointcloud`) and EquipStatus + PowerLevel + EquipTune
(`equipment`). scanpointcloud doesn't join to `equipment` directly
(it joins to `projects` + `personnel`); equipment is reached only via
scanmesh / scanenvironment / scanfeatures / scanprocessing. Cross-peer.
Status: deferred to W4b R-MULTISTAGE.

## KB 40 — Spatially Complex Site

Reason: AreaM2 (`scanspatial`) and SDI (#34, deferred). Status:
deferred — cascades from KB #34.

## KB 41 — Texture-Critical Artifact

Reason: TextureStudy (`scanfeatures`) and TDI (`scanmesh`). Cross-peer
(both reach `equipment` + `sites` but no peer-FK). Status: deferred
to W4b R-MULTISTAGE.

## KB 43 — Processing Optimized Workflow

Reason: PRU (#37, deferred) and MFS (`scanmesh`). Status: deferred —
cascades from KB #37.

## KB 44 — Registration Confidence Level

Reason: RAR (#33, deferred) and LogMethod (`scanregistration`).
Status: deferred — cascades from KB #33.

## KB 45 — Environmental Challenge Scan

Reason: EIF (#31, deferred). Status: deferred — cascades from KB #31.

## KB 46 — High Temporal Value Site

Reason: GuessDate (`sites`) and CPI (#35, encoded on
`scanconservation`). `sites` cannot reach `scanconservation` through
the auto-FK direction (scanconservation→sites only). Status:
deferred to W4b R-MULTISTAGE encoding (per-site CPI from
`scanconservation` joined back to `sites`).

## KB 47 — Resource-Intensive Model

Reason: FacetFaces (`scanmesh`) and MPR (#36, deferred). Status:
deferred — cascades from KB #36.

## KB 48 — Multi-Phase Documentation Project

Reason: ADC (#9, deferred) and DPQ (#38, deferred) aggregated across
multiple scans of one project. Status: deferred to W4b R-MULTISTAGE.

## KB 49 — Equipment Optimization Opportunity

Reason: EER (#39, deferred) and ESI (`scanenvironment`). Status:
deferred — cascades from KB #39.

## KB 51 — Workflow Efficiency Classification

Reason: 3-tier classification over PRU (#37, deferred). Status:
deferred — cascades from KB #37.
