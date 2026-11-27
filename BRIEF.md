# BRIEF.md — GIW26 Hackathon (Team 5 Single Source of Truth)

> Rule: Every number spoken in the 5–6 min video must match `kpis.json` and `numbers.csv`.
> Last updated: 2026-11-27

## 0. Status
- **Team:** Team 5 — Ziad Elmaadawy, Nada, Daniel Thomas (Engineering) + Nourhan Ahmed (Business Informatics)
- **Track:** Track 2 — Smart Energy & Sustainability
- **Concept Name:** New Cairo Roof Decision Engine (Per-Building Solar PV vs. Cool-Roof Triage)
- **Deadlines:** Registration Sun 29 Nov 2026 (23:59) | Video Submission Sat 5 Dec 2026 (target Fri 4 Dec) | Finals Wed 16 Dec 2026 (GUC Hall D1)
- **Video Length:** 5–6 minutes (per organiser email; confirm if 10 min PDF cap also applies)

## 1. Verified Data & Pipeline Results (`kpis.json`)
| Check / Metric | Status | Verified Value | Ledger ID |
|---|---|---|---|
| Building Footprints (Overture Maps) | PASS | 26,341 raw → 21,135 eligible roofs (≥ 40 m², excluding sheds/stadiums/mosques) | S-001 |
| Height Coverage (Overture / OSM) | LIMIT | 0.2% (42 buildings) — 3D shading transparently excluded rather than fabricated | S-002 |
| PVGIS Solar Irradiance (7 Cairo districts) | PASS | 1,795–1,875 kWh/kWp/yr (mid 1,835; 4.4% spread → sunlight alone is flat) | S-003 |
| Landsat 8/9 Summer LST Composite | PASS | 8 cloud-masked summer scenes (2025–2026); mean 45.15 °C, std 1.28 °C, 67th-pct hot cutoff 45.57 °C | S-004 |
| Thermal Spatial Resolution | INFO | 1.3 buildings / 30 m resampled px; 6.3 buildings / 100 m native Landsat TIRS cell | S-005 |
| Classification: Solar PV Only | PASS | 5,357 buildings (25.3%) | R-001 |
| Classification: Both (Priority) | PASS | 2,502 buildings (11.8%) | R-002 |
| Classification: Cool-Roof Only | PASS | 4,519 buildings (21.4%) | R-003 |
| Classification: Low Priority | PASS | 8,757 buildings (41.4%) | R-004 |
| Total PV-Capable Potential | PASS | 7,859 buildings (37.2%), 259.6 MWp, 476.33 GWh/yr gross | R-005 |

## 2. Problem & Solution (One Sentence Each)
- **Problem:** Following Egypt's August 2026 electricity tariff hike (flat 2.74 EGP/kWh cliff above 1,000 kWh/mo), New Cairo compound managers and homeowners face surging summer AC bills, yet generic solar maps fail because sunlight varies by only 4.4% across Cairo while roof size and heat stress vary dramatically.
- **Solution:** An automated, per-building geospatial decision engine covering 21,135 Fifth Settlement roofs that fuses Overture Maps footprints, 8-scene Landsat thermal composites, PVGIS solar yield, and EgyptERA 2026 tariff-cliff economics to prescribe **Solar PV**, **Cool-Roof coating**, **Both**, or **Low Priority** with live EGP payback.

## 3. Area of Interest (AOI)
- **Zone:** Fifth Settlement Pilot Zone, New Cairo (`31.42°E–31.50°E, 29.98°N–30.03°N`, ~42.6 km²)
- **Analysis CRS:** `EPSG:32636` (UTM Zone 36N, metric) | **Display CRS:** `EPSG:4326`
- **Why this AOI:** Combines gated compounds (El Narges, El Diyar, Gardenia Heights), commercial hubs (Point 90 Mall, Dusit Thani), institutional campuses (GUC Hall D1 — the finals venue — and AUC), and the Petrified Forest reserve boundary. Pipeline scales to any Greater Cairo district by changing 4 bbox coordinates.

## 4. Method (Reproducible)
1. **Footprint Ingestion & Filtering (`build_roof_analysis.py`):** Pull Overture Maps buildings (merging OSM + Microsoft + Google Open Buildings), project to EPSG:32636, exclude non-roof/domed/open-air structures (`stadium`, `mosque`, `shed`, `garage`, etc.) and polygons < 40 m².
2. **Thermal Composite:** Query Microsoft Planetary Computer STAC for 8 clear (<15% cloud) summer Landsat 8/9 Collection 2 Level 2 `lwir11` scenes from path/row 176/039, apply `qa_pixel` cloud/shadow bitmask (`0b11110`), compute pixel-wise median LST (°C), and extract zonal mean LST per building.
3. **Screening Classification:** Usable PV capacity = `area * 0.40 * 0.15 kWp/m²`. Buildings with `≥ 20 kWp` (~333 m² footprint) are PV-capable; buildings in the top third of zonal LST (`≥ 45.57 °C`) are thermal hotspots.
4. **Interactive Prototype (`index.html`):** Keyless Leaflet Canvas dashboard rendering all 21,135 buildings with live layer switching (Decision / Heat LST / PV kWp), Dark/Satellite/Light basemaps, 1-click landmark jumps, live threshold sliders, and an EgyptERA Aug 2026 EGP Payback calculator (Single Villa vs. Shared/B2B meter).

## 5. Honest Limitations (State on Camera for Spatial Rigor Points)
- **Native 100 m thermal resolution:** Landsat TIRS is 100 m native (resampled to 30 m; ~6.3 buildings share one native cell) captured mid-morning (~10:30 AM local). LST is therefore a *relative neighborhood hotspot screen*, not a single-roof thermometer.
- **No 3D shading:** Only 0.2% of footprints carry height tags; 3D shadow raycasting was excluded rather than fabricated.
- **Gross vs. net PV:** 476.33 GWh/yr is gross technical roof potential; actual installation sizes are capped by each meter's annual load under EgyptERA net-metering rules.

## 6. Business & Operations (Owner: Nourhan — BI)
- **Target Buyers:** (1) New Cairo compound developers & facility management companies (common-area OPEX reduction + ESG positioning); (2) Egyptian Solar EPCs & reflective-coating contractors buying ranked, building-level prospect lists.
- **BI Verification Needed in `numbers.csv`:** Confirm 5 local Egyptian figures (B-001 to B-005): EgyptERA Aug 2026 residential & LV commercial tariffs, installed Solar PV CAPEX (EGP/kWp), reflective cool-roof coating cost (EGP/m²), cool-roof AC saving citation/DOI, and SaaS/lead-list pricing model.

## 7. 6-Minute Video Split & Team Roles
| Segment | Time | Owner | Visuals (Max 15s slides total!) |
|---|---|---|---|
| 1. Problem & Real Cairo Hook | 0:45 | Nada / Daniel | 15–20 sec real phone footage of New Cairo rooftops / AC units + GUC |
| 2. Solution & Why Not Sunlight? | 0:45 | Ziad | Live map overview showing 4.4% PVGIS flat spread vs. 21,135 classified roofs |
| 3. Technical Pipeline & Spatial Rigor | 1:45 | Ziad | Quick VS Code / `build_roof_analysis.py` run + Heat (LST) mode + Satellite overlay + honest limits |
| 4. Live Interactive Prototype Demo | 1:15 | Nada / Daniel | Click **Jump: GUC Hall D1**, **El Narges Villas**, drag live sliders & watch classes update |
| 5. Business Model & EGP Payback | 1:00 | Nourhan (BI) | Live right-panel EgyptERA 2026 tariff cliff demo (sliding past 1,000 kWh) + B2B buyer pitch |
| 6. Impact & Scalability Close | 0:30 | All / Ziad | Zoom out to Greater Cairo: 259.6 MWp / 476 GWh/yr pilot, 4-coordinate scale-up |
