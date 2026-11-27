# New Cairo Roof Decision Engine — GIW26 Hackathon (Track 2)

An automated, per-building geospatial decision engine for the **Fifth Settlement, New Cairo (42.6 km² pilot zone)** that classifies **21,135 rooftops** into **Solar PV**, **Cool-Roof coating**, **Both (Priority)**, or **Low Priority** using open satellite telemetry and EgyptERA August 2026 electricity tariff cliffs.

**Live Interactive Map:** `https://ziad-elmaadawy.github.io/giw26-cairo-roof-engine/` *(enable GitHub Pages in Settings → Pages → main / root)*

---

## Why Not Rank Roofs by Sunlight?
EU JRC PVGIS modeling across 7 Greater Cairo districts shows only a **4.4% spread** in annual solar yield (`1,795–1,875 kWh/kWp/yr`). Because sunlight is nearly flat across Cairo, effective roof triage depends on three real discriminators:
1. **Usable Roof Area:** Overture Maps building footprints (merging OpenStreetMap, Microsoft, and Google Open Buildings) projected to UTM Zone 36N (`EPSG:32636`).
2. **Neighborhood Thermal Stress:** Zonal mean Land Surface Temperature (LST) from an 8-scene, QA cloud-masked summer median composite of Landsat 8/9 Collection 2 Level 2 (`lwir11`, 2025–2026).
3. **EgyptERA 2026 Tariff Cliffs:** Interactive EGP payback calculator modeling Egypt's residential flat-rate cliffs (`>650 kWh` at `2.41 EGP/kWh`; `>1,000 kWh` at `2.74 EGP/kWh`) and LV commercial/shared meters (`2.74 EGP/kWh`).

---

## Pilot Zone Results (`kpis.json`)
| Metric | Verified Value |
| :--- | :--- |
| **Buildings Analyzed** | 21,135 eligible roofs (≥ 40 m² from 26,341 raw Overture footprints) |
| **Solar PV Only** | 5,357 buildings (25.3%) |
| **Both (Solar + Cool-Roof)** | 2,502 buildings (11.8%) |
| **Cool-Roof Only** | 4,519 buildings (21.4%) |
| **Low Priority** | 8,757 buildings (41.4%) |
| **Gross Solar Potential** | 259.6 MWp · 476.33 GWh/yr (7,859 PV-capable roofs) |
| **Summer Median LST** | Mean 45.15 °C · Std 1.28 °C · 67th-pct hot cutoff 45.57 °C |

---

## Repository Structure
* `index.html` — Single-file interactive Leaflet Canvas dashboard (no API keys required).
* `dashboard_data.geojson` — Lightweight classified building polygons + landmarks for the web map.
* `build_roof_analysis.py` — Reproducible Python pipeline (Overture/OSM footprints + Planetary Computer Landsat LST composite + zonal stats + sensitivity analysis).
* `kpis.json` — Verified summary statistics and sensitivity matrix.
* `BRIEF.md` — Team 5 single-source-of-truth project brief and 6-minute video split.
* `numbers.csv` — Fact ledger separating verified geospatial outputs from BI financial inputs.

---

## Run Locally
```powershell
# View the interactive dashboard locally
python -m http.server 8000
# Open http://localhost:8000
```

To re-run the geospatial analysis pipeline from scratch:
```powershell
pip install osmnx geopandas pandas numpy requests rasterio pystac-client planetary-computer overturemaps
python build_roof_analysis.py
```

---

## Team 5 (GUC — GIW26)
* **Engineering:** Ziad Elmaadawy, Nada, Daniel Thomas
* **Business Informatics (BI):** Nourhan Ahmed
