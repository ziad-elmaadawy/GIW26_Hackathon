#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_roof_analysis.py  (GIW26 Track 2: Cairo Roof Decision Engine — v3 Overture + OSM)

Auto-detects `smoke_out/overture_buildings.geojson` (Overture Maps: OSM + Microsoft + Google Open Buildings)
and falls back to `smoke_out/osm_buildings.geojson` if Overture is absent.

Outputs:
  dashboard_data.geojson   (lightweight, optimized for 25k+ buildings in Leaflet Canvas)
  kpis.json                (verified metrics for BRIEF.md and numbers.csv)
  smoke_out/lst_composite.tif (cached 8-scene summer Landsat 8/9 LST median composite)

Run:
  python build_roof_analysis.py
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PARAMS = dict(
    utm_epsg=32636,
    min_footprint_m2=40,
    excluded_building=[
        "roof", "ruins", "construction", "greenhouse", "shed", "garage", "garages", "carport",
        "hut", "cabin", "kiosk", "service", "static_caravan", "container", "toilets", "bunker",
        "stadium", "grandstand", "mosque", "church", "chapel", "temple", "synagogue", "religious",
        "bridge", "wall", "tower", "water_tower", "silo", "storage_tank", "transformer_tower",
    ],
    usable_fraction=0.40,      # Cairo flat-roof usable share (after stairwells, tanks, AC units, setbacks)
    kwp_per_m2=0.15,           # kWp per usable m2 (tilted 25 deg rows with inter-row spacing)
    pv_min_kwp=20.0,           # Minimum compound/commercial-viable PV capacity (~333 m2 footprint)
    hot_percentile=67,         # Relative top-third heat stress threshold within AOI
    simplify_m=0.5,            # 0.5 m simplification keeps 26k+ buildings fast in browser
    coord_decimals=5,          # 5 decimals (~1.1 m) halves GeoJSON file size cleanly
    lst_scale=0.00341802, lst_offset=149.0,
    stac_range="2025-06-01/2026-08-31", summer_months=[6, 7, 8], max_cloud=15,
)
CLASS_NAMES = ["Solar PV", "Cool-roof", "Both", "Low priority"]


def extract_primary_name(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    if isinstance(val, dict):
        return str(val.get("primary") or "").strip()
    s = str(val).strip()
    if not s or s.lower() == "none":
        return ""
    if s.startswith("{"):
        try:
            d = json.loads(s)
            if isinstance(d, dict):
                return str(d.get("primary") or "").strip()
        except Exception:
            pass
    return s


# ------------------------------------------------------------------ buildings
def load_buildings(path: Path):
    import geopandas as gpd
    import pandas as pd

    print(f"Loading buildings from: {path}")
    g = gpd.read_file(path)
    n0 = len(g)
    g = g[g.geom_type.isin(["Polygon", "MultiPolygon"])].copy()

    # Detect Overture Maps vs raw OSM schema
    is_overture = ("subtype" in g.columns) or ("names" in g.columns) or ("class" in g.columns)
    source_label = "Overture Maps (OSM + Microsoft + Google)" if is_overture else "OpenStreetMap"

    if is_overture:
        cls_s = g["class"].fillna("").astype(str).str.strip() if "class" in g.columns else pd.Series([""] * len(g), index=g.index)
        sub_s = g["subtype"].fillna("").astype(str).str.strip() if "subtype" in g.columns else pd.Series([""] * len(g), index=g.index)
        btag = cls_s.where(cls_s != "", sub_s)
        btag = btag.where(btag != "", "building")
        excl_mask = cls_s.str.lower().isin(PARAMS["excluded_building"]) | sub_s.str.lower().isin(PARAMS["excluded_building"])
        if "is_underground" in g.columns:
            excl_mask = excl_mask | (g["is_underground"] == True)  # noqa: E712
        g["btag"] = btag
        g = g[~excl_mask].copy()
    else:
        tag = g["building"].fillna("yes").astype(str) if "building" in g.columns else pd.Series(["yes"] * len(g), index=g.index)
        g["btag"] = tag
        g = g[~tag.str.lower().isin(PARAMS["excluded_building"])].copy()

    n1 = len(g)
    g["area"] = g.to_crs(PARAMS["utm_epsg"]).area
    g = g[g["area"] >= PARAMS["min_footprint_m2"]].copy()

    # Names
    if "names" in g.columns:
        g["bname"] = g["names"].apply(extract_primary_name)
    elif "name" in g.columns:
        g["bname"] = g["name"].apply(extract_primary_name)
    else:
        g["bname"] = ""

    # Heights (if available in Overture / OSM)
    h_vals = pd.Series(np.nan, index=g.index, dtype="float64")
    if "height" in g.columns:
        h_vals = pd.to_numeric(g["height"], errors="coerce")
    if "num_floors" in g.columns:
        fl = pd.to_numeric(g["num_floors"], errors="coerce") * 3.2
        h_vals = h_vals.fillna(fl)
    elif "building:levels" in g.columns:
        fl = pd.to_numeric(g["building:levels"], errors="coerce") * 3.2
        h_vals = h_vals.fillna(fl)
    g["height_m"] = h_vals
    height_cov = float(h_vals.notna().mean()) if len(g) else 0.0

    g = g.reset_index(drop=True)
    print(f"source: {source_label}")
    print(f"buildings: {n0} loaded -> {n1} after tag filter -> {len(g)} after >= {PARAMS['min_footprint_m2']} m2")
    print(f"height coverage: {height_cov:.1%} ({int(h_vals.notna().sum())} buildings)")
    return g, dict(source=source_label, loaded=n0, after_tag_filter=n1, kept=len(g), height_coverage_pct=round(height_cov * 100, 1))


# ------------------------------------------------------------------ LST composite
def read_scene(item, bounds):
    import planetary_computer  # noqa: F401
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds

    with rasterio.open(item.assets["lwir11"].href) as src:
        b = transform_bounds("EPSG:4326", src.crs, *bounds, densify_pts=21)
        w = from_bounds(*b, transform=src.transform)
        win = Window(math.floor(w.col_off), math.floor(w.row_off), math.ceil(w.width) + 1, math.ceil(w.height) + 1)
        dn = src.read(1, window=win).astype("float64")
        tr, crs = src.window_transform(win), src.crs
    c = np.where(dn > 0, dn * PARAMS["lst_scale"] + PARAMS["lst_offset"] - 273.15, np.nan)
    try:
        with rasterio.open(item.assets["qa_pixel"].href) as q:
            qa = q.read(1, window=win)
        if qa.shape == c.shape:
            c[(qa & 0b11110) != 0] = np.nan
    except Exception as e:  # noqa: BLE001
        print(f"  QA mask unavailable for {item.id}: {e}")
    return c.astype("float32"), tr, crs


def fetch_composite(bounds, n_scenes, out_tif: Path):
    import planetary_computer as pc
    import rasterio
    from pystac_client import Client

    pad = 0.01
    bb = (bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad)
    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)
    items = [i for i in cat.search(collections=["landsat-c2-l2"], bbox=bb, datetime=PARAMS["stac_range"],
                                   query={"eo:cloud_cover": {"lt": PARAMS["max_cloud"]}}).items()
             if i.datetime and i.datetime.month in PARAMS["summer_months"]
             and i.properties.get("platform") in ("landsat-8", "landsat-9")]
    if not items:
        raise RuntimeError("no clear summer Landsat scenes found")
    items.sort(key=lambda i: i.properties.get("eo:cloud_cover", 100))
    pr = (items[0].properties.get("landsat:wrs_path"), items[0].properties.get("landsat:wrs_row"))
    items = [i for i in items if (i.properties.get("landsat:wrs_path"), i.properties.get("landsat:wrs_row")) == pr]
    items = items[:n_scenes]
    print(f"LST: using {len(items)} scenes from path/row {pr}")
    stack, ref_tr, ref_crs, used = [], None, None, []
    for it in items:
        arr, tr, crs = read_scene(it, bb)
        if ref_tr is None:
            ref_tr, ref_crs = tr, crs
        if stack and arr.shape != stack[0].shape:
            continue
        if abs(tr.c - ref_tr.c) > 1 or abs(tr.f - ref_tr.f) > 1:
            continue
        stack.append(arr)
        used.append(f"{it.id} ({it.datetime.date()}, cloud {it.properties.get('eo:cloud_cover')})")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        comp = np.nanmedian(np.stack(stack), axis=0).astype("float32")
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_tif, "w", driver="GTiff", height=comp.shape[0], width=comp.shape[1], count=1,
                       dtype="float32", crs=ref_crs, transform=ref_tr, nodata=np.nan, compress="deflate") as dst:
        dst.write(comp, 1)
        dst.update_tags(scenes=" | ".join(used), method="nanmedian, QA-masked, Landsat C2 L2 lwir11, degC")
    print(f"saved {out_tif}")
    return comp, ref_tr, ref_crs, used


def load_composite(tif: Path):
    import rasterio

    with rasterio.open(tif) as s:
        arr = s.read(1).astype("float32")
        if s.nodata is not None and not np.isnan(s.nodata):
            arr[arr == s.nodata] = np.nan
        used = [u for u in s.tags().get("scenes", "").split(" | ") if u]
        return arr, s.transform, s.crs, used


def sample_lst_zonal(g, arr, tr, crs):
    """Fast zonal mean LST: uses bounding-box pixel slice for small buildings (< 1,000 m2)
    and exact geometry_mask for larger roofs, keeping 26k+ buildings under ~8 seconds."""
    from rasterio.features import geometry_mask
    from rasterio.transform import rowcol
    from rasterio.windows import from_bounds

    g_proj = g.to_crs(crs)
    h, w = arr.shape
    t = np.full(len(g), np.nan, dtype="float64")
    pix30 = np.full(len(g), -1, dtype="int64")
    pix100 = np.full(len(g), -1, dtype="int64")

    pts = g_proj.geometry.representative_point()
    pt_rows, pt_cols = rowcol(tr, pts.x.values, pts.y.values)
    pt_rows, pt_cols = np.asarray(pt_rows), np.asarray(pt_cols)

    px_size = abs(tr.a)
    cell_factor = max(1.0, 100.0 / px_size)
    areas = g["area"].values

    for idx, geom in enumerate(g_proj.geometry):
        r0, c0 = int(pt_rows[idx]), int(pt_cols[idx])
        if 0 <= r0 < h and 0 <= c0 < w:
            pix30[idx] = r0 * 100000 + c0
            pix100[idx] = int(r0 // cell_factor) * 100000 + int(c0 // cell_factor)

        # For buildings smaller than ~1 Landsat 30m pixel (900 m2), center pixel or 2x2 touched bbox is exact
        if areas[idx] < 900.0:
            if 0 <= r0 < h and 0 <= c0 < w and np.isfinite(arr[r0, c0]):
                t[idx] = float(arr[r0, c0])
                continue

        minx, miny, maxx, maxy = geom.bounds
        win = from_bounds(minx, miny, maxx, maxy, transform=tr)
        col_off = max(0, math.floor(win.col_off))
        row_off = max(0, math.floor(win.row_off))
        col_end = min(w, math.ceil(win.col_off + win.width) + 1)
        row_end = min(h, math.ceil(win.row_off + win.height) + 1)
        ww, hh = col_end - col_off, row_end - row_off

        if ww > 0 and hh > 0:
            sub = arr[row_off:row_end, col_off:col_end]
            sub_tr = tr * tr.translation(col_off, row_off)
            mask = geometry_mask([geom], out_shape=(hh, ww), transform=sub_tr, invert=True, all_touched=True)
            vals = sub[mask]
            vals = vals[np.isfinite(vals)]
            if vals.size > 0:
                t[idx] = float(np.mean(vals))
                continue

        if 0 <= r0 < h and 0 <= c0 < w and np.isfinite(arr[r0, c0]):
            t[idx] = float(arr[r0, c0])

    return t, pix30, pix100


# ------------------------------------------------------------------ classification
def classify(area, lst, usable_fraction, kwp_per_m2, pv_min_kwp, hot_pct):
    kwp = area * usable_fraction * kwp_per_m2
    valid = np.isfinite(lst)
    thr = round(float(np.nanpercentile(lst[valid], hot_pct)), 2) if valid.any() else float("nan")
    hot = valid & (np.round(lst, 2) >= thr)
    pv = kwp >= pv_min_kwp
    cls = np.full(len(area), 3, dtype=int)
    cls[pv & ~hot] = 0
    cls[~pv & hot] = 1
    cls[pv & hot] = 2
    return cls, kwp, thr


# ------------------------------------------------------------------ export
def round_coords(x, nd=5):
    return [round_coords(i, nd) for i in x] if isinstance(x, (list, tuple)) else round(x, nd)


def find_landmarks(g_wgs):
    """Find recognizable New Cairo landmarks by name OR known coordinates (works for both OSM and Overture)."""
    pts = g_wgs.geometry.representative_point()
    lats = pts.y.values
    lons = pts.x.values
    names = g_wgs["bname"].values
    tags = g_wgs["btag"].values
    areas = g_wgs["area"].values

    def nearest_idx(target_lat, target_lon, min_area=150):
        d2 = (lats - target_lat) ** 2 + (lons - target_lon) ** 2
        d2 = np.where(areas >= min_area, d2, 999.0)
        return int(np.argmin(d2))

    # Fixed reliable landmarks with name match first, coordinate fallback second
    specs = [
        ("GUC Hall D1", lambda i: names[i] == "D1", (29.9867, 31.4413, 800)),
        ("Point 90 Mall", lambda i: "point 90" in names[i].lower(), (30.0202, 31.4948, 2000)),
        ("Dusit Thani", lambda i: "dusit thani" in names[i].lower(), (30.0256, 31.4550, 2000)),
        ("Air Force Hosp.", lambda i: "air force hospital" in names[i].lower(), (30.0175, 31.4344, 2000)),
        ("El Narges Villas", lambda i: False, (30.0085, 31.4660, 180)),
        ("AUC Campus", lambda i: "الجامعة الأمريكية" in names[i] or "american university" in names[i].lower(), (30.0198, 31.4995, 2000)),
    ]
    found = []
    for label, pred, (tlat, tlon, mina) in specs:
        match = None
        for i in range(len(g_wgs)):
            if pred(i):
                match = i
                break
        if match is None:
            match = nearest_idx(tlat, tlon, mina)
        found.append(dict(label=label, id=int(match), lat=round(float(lats[match]), 5), lon=round(float(lons[match]), 5)))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--buildings", default="", help="path to GeoJSON (auto-prefers Overture if present)")
    ap.add_argument("--lst-tif", default="smoke_out/lst_composite.tif")
    ap.add_argument("--refetch", action="store_true")
    ap.add_argument("--n-scenes", type=int, default=8)
    ap.add_argument("--smoke-json", default="smoke_out/smoke_results.json")
    ap.add_argument("--pvgis-min", type=float, default=1795.0)
    ap.add_argument("--pvgis-max", type=float, default=1875.0)
    ap.add_argument("--out", default="dashboard_data.geojson")
    a = ap.parse_args()

    import geopandas as gpd

    if a.buildings:
        bpath = Path(a.buildings)
    elif Path("smoke_out/overture_buildings.geojson").exists():
        bpath = Path("smoke_out/overture_buildings.geojson")
    else:
        bpath = Path("smoke_out/osm_buildings.geojson")

    g, bstats = load_buildings(bpath)
    bounds = tuple(g.total_bounds)
    tif = Path(a.lst_tif)
    if tif.exists() and not a.refetch:
        arr, tr, crs, scenes = load_composite(tif)
        print(f"LST: reusing {tif}")
    else:
        arr, tr, crs, scenes = fetch_composite(bounds, a.n_scenes, tif)

    pvmin, pvmax = a.pvgis_min, a.pvgis_max
    sj = Path(a.smoke_json)
    if sj.exists():
        try:
            for r in json.loads(sj.read_text(encoding="utf-8"))["results"]:
                m = re.search(r"min\s+([\d.]+),\s*max\s+([\d.]+)", r["detail"]) if r["check"] == "PVGIS" else None
                if m:
                    pvmin, pvmax = float(m.group(1)), float(m.group(2))
        except Exception:
            pass
    pv_yield = round((pvmin + pvmax) / 2, 0)

    print("LST: computing zonal mean per building polygon...")
    lst, pix30, pix100 = sample_lst_zonal(g, arr, tr, crs)
    area = g["area"].values
    P = PARAMS
    cls, kwp, thr = classify(area, lst, P["usable_fraction"], P["kwp_per_m2"], P["pv_min_kwp"], P["hot_percentile"])

    valid = np.isfinite(lst)
    ups30 = len(set(pix30[valid].tolist()))
    ups100 = len(set(pix100[valid].tolist()))
    sens = dict(
        pv_capable={f"usable={uf}|min_kwp={mk}": int(((area * uf * P["kwp_per_m2"]) >= mk).sum())
                    for uf in (0.3, 0.4, 0.5) for mk in (10, 15, 20)},
        hot={f"p{p}": int((valid & (np.round(lst, 2) >= round(float(np.nanpercentile(lst[valid], p)), 2))).sum())
             for p in (50, 67, 80)},
    )
    counts = {CLASS_NAMES[i]: int((cls == i).sum()) for i in range(4)}
    pvcap = (cls == 0) | (cls == 2)
    kpis = dict(
        built_at=datetime.now().isoformat(timespec="seconds"),
        buildings=bstats,
        params={k: v for k, v in P.items() if k != "excluded_building"},
        class_counts=counts,
        total_footprint_m2=round(float(area.sum()), 0),
        median_footprint_m2=round(float(np.median(area)), 0),
        pv_capable_buildings=int(pvcap.sum()),
        pv_capable_kwp=round(float(kwp[pvcap].sum()), 0),
        pv_gross_gwh_per_year=round(float(kwp[pvcap].sum()) * pv_yield / 1e6, 2),
        pvgis_yield_kwh_per_kwp=dict(min=pvmin, max=pvmax, mid=pv_yield),
        lst=dict(
            method="zonal_mean_all_touched",
            valid_buildings=int(valid.sum()),
            mean=round(float(np.nanmean(lst)), 2),
            std=round(float(np.nanstd(lst)), 2),
            min=round(float(np.nanmin(lst)), 2),
            max=round(float(np.nanmax(lst)), 2),
            hot_threshold_c=thr,
            unique_30m_pixels=ups30,
            buildings_per_30m_pixel=round(int(valid.sum()) / max(ups30, 1), 1),
            unique_100m_native_cells=ups100,
            buildings_per_100m_native_cell=round(int(valid.sum()) / max(ups100, 1), 1),
        ),
        sensitivity=sens,
        lst_scenes=scenes,
    )
    Path("kpis.json").write_text(json.dumps(kpis, indent=2), encoding="utf-8")

    p2, p98 = (float(np.nanpercentile(lst[valid], 2)), float(np.nanpercentile(lst[valid], 98))) if valid.any() else (0, 1)
    gg = g.to_crs(P["utm_epsg"]).copy()
    gg["geometry"] = gg.geometry.simplify(P["simplify_m"], preserve_topology=True)
    gg = gg.to_crs(4326)
    landmarks = find_landmarks(gg)

    # Fast GeoJSON export using shapely __geo_interface__ (10x faster than per-row GeoSeries.to_json)
    nd = P["coord_decimals"]
    btags = g["btag"].values
    bnames = g["bname"].values
    heights = g["height_m"].values
    feats = []
    for i, geom in enumerate(gg.geometry):
        if geom is None or geom.is_empty:
            continue
        gi = geom.__geo_interface__
        gj = dict(type=gi["type"], coordinates=round_coords(gi["coordinates"], nd))
        props = dict(
            i=i,
            a=int(round(area[i])),
            t=None if not valid[i] else round(float(lst[i]), 2),
            k=round(float(kwp[i]), 1),
            c=int(cls[i]),
            b=str(btags[i]),
        )
        if bnames[i]:
            props["n"] = str(bnames[i])
        if np.isfinite(heights[i]):
            props["h"] = round(float(heights[i]), 1)
        feats.append(dict(type="Feature", geometry=gj, properties=props))

    meta = dict(
        source=bstats["source"],
        height_coverage_pct=bstats["height_coverage_pct"],
        class_names=CLASS_NAMES,
        usable_fraction=P["usable_fraction"],
        kwp_per_m2=P["kwp_per_m2"],
        pv_min_kwp=P["pv_min_kwp"],
        hot_percentile=P["hot_percentile"],
        hot_threshold_c=thr,
        lst_p2=round(p2, 2),
        lst_p98=round(p98, 2),
        lst_std=kpis["lst"]["std"],
        buildings_per_100m_cell=kpis["lst"]["buildings_per_100m_native_cell"],
        pvgis_yield_mid=pv_yield,
        pvgis_range=[pvmin, pvmax],
        counts=counts,
        lst_scenes=scenes,
        n_buildings=len(feats),
        bounds=[float(x) for x in bounds],
        landmarks=landmarks,
        built_at=kpis["built_at"],
    )
    Path(a.out).write_text(json.dumps(dict(type="FeatureCollection", meta=meta, features=feats),
                                      separators=(",", ":")), encoding="utf-8")
    size = Path(a.out).stat().st_size / 1e6
    print("\n" + "=" * 70)
    print(f"source : {bstats['source']} (height coverage: {bstats['height_coverage_pct']}%)")
    print(f"classes: {counts}")
    print(f"PV-capable: {kpis['pv_capable_buildings']:,} buildings, {kpis['pv_capable_kwp']:,.0f} kWp, "
          f"{kpis['pv_gross_gwh_per_year']} GWh/yr gross")
    print(f"LST (zonal mean): mean {kpis['lst']['mean']} C, std {kpis['lst']['std']} C, hot threshold {thr} C")
    print(f"Thermal resolution: {kpis['lst']['buildings_per_30m_pixel']} bldgs / 30m resampled px | "
          f"{kpis['lst']['buildings_per_100m_native_cell']} bldgs / 100m native TIRS cell")
    print(f"Landmarks indexed: {[lm['label'] for lm in landmarks]}")
    print(f"wrote {a.out} ({size:.2f} MB, {len(feats):,} features), kpis.json")


if __name__ == "__main__":
    main()
