#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_lst.py — Empirical Validation Pack for GIW26 Track 2

Does two judge-proofing checks in ~20 seconds:
  1. Split-Half Landsat Thermal Stability (defeats Judge Attack #1: "1.28 C spread is sensor noise"):
     Re-reads the 8 summer Landsat scenes from kpis.json, splits them into Half A (scenes 1-4)
     vs. Half B (scenes 5-8) AND 2025 vs. 2026, computes building LST for all 21,135 roofs,
     and prints the Spearman rank correlation (rho) + median absolute difference (degC).
  2. Random Satellite Audit Sheet (defeats Judge Attack #2: "Where is ground truth?"):
     Exports `validation_sample_50.csv` with 50 random building IDs, areas, classes, and
     direct Google Maps satellite links so Nada/Daniel can verify footprint accuracy in 5 mins.

Run inside VS Code terminal (Projects/giw26-cairo-roof-engine):
  python validate_lst.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LST_SCALE = 0.00341802
LST_OFFSET = 149.0


def spearman_rho(x: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 10:
        return float("nan")
    rx = pd.Series(x[mask]).rank(method="average").to_numpy()
    ry = pd.Series(y[mask]).rank(method="average").to_numpy()
    return float(np.corrcoef(rx, ry)[0, 1])


def read_scene_window(item, bounds):
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds

    with rasterio.open(item.assets["lwir11"].href) as src:
        b = transform_bounds("EPSG:4326", src.crs, *bounds, densify_pts=21)
        w = from_bounds(*b, transform=src.transform)
        win = Window(math.floor(w.col_off), math.floor(w.row_off), math.ceil(w.width) + 1, math.ceil(w.height) + 1)
        dn = src.read(1, window=win).astype("float64")
        tr, crs = src.window_transform(win), src.crs
    c = np.where(dn > 0, dn * LST_SCALE + LST_OFFSET - 273.15, np.nan)
    try:
        with rasterio.open(item.assets["qa_pixel"].href) as q:
            qa = q.read(1, window=win)
        if qa.shape == c.shape:
            c[(qa & 0b11110) != 0] = np.nan
    except Exception:
        pass
    return c.astype("float32"), tr, crs


def sample_points(xs, ys, arr, tr):
    from rasterio.transform import rowcol

    rows, cols = rowcol(tr, xs, ys)
    rows, cols = np.asarray(rows), np.asarray(cols)
    ok = (rows >= 0) & (rows < arr.shape[0]) & (cols >= 0) & (cols < arr.shape[1])
    out = np.full(len(xs), np.nan, dtype="float64")
    out[ok] = arr[rows[ok], cols[ok]]
    return out


def main():
    import geopandas as gpd
    import planetary_computer as pc
    from pystac_client import Client

    gj_path = Path("dashboard_data.geojson")
    kpis_path = Path("kpis.json")
    if not gj_path.exists() or not kpis_path.exists():
        print("ERROR: Run this inside your project folder next to dashboard_data.geojson and kpis.json.")
        sys.exit(1)

    print("1/3 Loading buildings from dashboard_data.geojson...")
    g = gpd.read_file(gj_path)
    kpis = json.loads(kpis_path.read_text(encoding="utf-8"))
    scene_ids = [s.split(" ")[0] for s in kpis.get("lst_scenes", [])]
    bounds = tuple(g.total_bounds)
    pad = 0.01
    bb = (bounds[0] - pad, bounds[1] - pad, bounds[2] + pad, bounds[3] + pad)

    # Export 50-building random visual audit sheet (always works even offline)
    rng = np.random.default_rng(42)
    sample_idx = np.sort(rng.choice(len(g), size=min(50, len(g)), replace=False))
    pts_wgs = g.geometry.representative_point()
    cls_names = ["Solar PV", "Cool-roof", "Both", "Low priority"]
    with Path("validation_sample_50.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["sample_no", "building_id", "area_m2", "lst_c", "class", "lat", "lon", "google_maps_sat_link", "roof_matches_sat_YES_NO", "notes"])
        for n, idx in enumerate(sample_idx, 1):
            row = g.iloc[idx]
            lat, lon = round(float(pts_wgs.iloc[idx].y), 6), round(float(pts_wgs.iloc[idx].x), 6)
            link = f"https://www.google.com/maps/@?api=1&map_action=map&center={lat},{lon}&zoom=20&basemap=satellite"
            wr.writerow([n, int(row["i"]), int(row["a"]), row["t"], cls_names[int(row["c"])], lat, lon, link, "", ""])
    print("    Saved validation_sample_50.csv (50 random roofs with 1-click satellite links).")

    print(f"2/3 Fetching the {len(scene_ids)} Landsat scenes for split-half stability check...")
    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=pc.sign_inplace)
    items = list(cat.search(collections=["landsat-c2-l2"], ids=scene_ids).items())
    by_id = {it.id: it for it in items}
    ordered = [by_id[sid] for sid in scene_ids if sid in by_id]
    if len(ordered) < 4:
        print(f"ERROR: Only retrieved {len(ordered)} scenes from STAC.")
        sys.exit(1)

    stack, years, ref_tr, ref_crs = [], [], None, None
    for it in ordered:
        arr, tr, crs = read_scene_window(it, bb)
        if ref_tr is None:
            ref_tr, ref_crs = tr, crs
        if stack and arr.shape != stack[0].shape:
            continue
        stack.append(arr)
        years.append(it.datetime.year)
        print(f"    ok {it.id} ({it.datetime.date()})")

    pts_proj = g.to_crs(ref_crs).geometry.representative_point()
    xs, ys = pts_proj.x.values, pts_proj.y.values

    print("3/3 Computing split-half Spearman rank correlations across all buildings...")
    mid = len(stack) // 2
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        half_a = np.nanmedian(np.stack(stack[:mid]), axis=0)
        half_b = np.nanmedian(np.stack(stack[mid:]), axis=0)
        even_m = np.nanmedian(np.stack(stack[0::2]), axis=0)
        odd_m = np.nanmedian(np.stack(stack[1::2]), axis=0)

    ta = sample_points(xs, ys, half_a, ref_tr)
    tb = sample_points(xs, ys, half_b, ref_tr)
    te = sample_points(xs, ys, even_m, ref_tr)
    to = sample_points(xs, ys, odd_m, ref_tr)

    rho_split = spearman_rho(ta, tb)
    rho_alt = spearman_rho(te, to)
    mad_split = float(np.nanmedian(np.abs((ta - np.nanmean(ta)) - (tb - np.nanmean(tb)))))

    # Check top-third (67th pct) hotspot overlap between Half A and Half B
    valid = np.isfinite(ta) & np.isfinite(tb)
    hot_a = ta[valid] >= np.nanpercentile(ta[valid], 67)
    hot_b = tb[valid] >= np.nanpercentile(tb[valid], 67)
    overlap_pct = float((hot_a & hot_b).sum() / max(hot_a.sum(), 1) * 100.0)

    # Inter-year stability (2025 vs 2026) if both years exist
    s25 = [a for a, y in zip(stack, years) if y == 2025]
    s26 = [a for a, y in zip(stack, years) if y == 2026]
    rho_yr = float("nan")
    if s25 and s26:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            t25 = sample_points(xs, ys, np.nanmedian(np.stack(s25), axis=0), ref_tr)
            t26 = sample_points(xs, ys, np.nanmedian(np.stack(s26), axis=0), ref_tr)
        rho_yr = spearman_rho(t25, t26)

    out = dict(
        n_buildings=int(valid.sum()),
        n_scenes=len(stack),
        spearman_scenes_1_4_vs_5_8=round(rho_split, 4),
        spearman_even_vs_odd_scenes=round(rho_alt, 4),
        spearman_2025_vs_2026=None if math.isnan(rho_yr) else round(rho_yr, 4),
        hotspot_top33_agreement_pct=round(overlap_pct, 1),
        demeaned_median_abs_diff_c=round(mad_split, 2),
    )
    Path("validation_results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"Buildings validated            : {out['n_buildings']:,}")
    print(f"Split-half Spearman rho (1-4 vs 5-8): {out['spearman_scenes_1_4_vs_5_8']:.3f}")
    print(f"Alternating Spearman rho (even/odd) : {out['spearman_even_vs_odd_scenes']:.3f}")
    if out["spearman_2025_vs_2026"] is not None:
        print(f"Inter-year Spearman rho (2025 vs 26): {out['spearman_2025_vs_2026']:.3f}")
    print(f"Top-third hotspot agreement         : {out['hotspot_top33_agreement_pct']:.1f}%")
    print(f"De-meaned median abs diff           : {out['demeaned_median_abs_diff_c']:.2f} C")
    print("Saved validation_results.json & validation_sample_50.csv")
    print("=" * 70)


if __name__ == "__main__":
    main()
