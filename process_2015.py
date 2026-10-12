
#!/usr/bin/env python3
"""HCMC 2015 ERA5 daily temperature and RH, DART-based workflow."""

from pathlib import Path
import hashlib
import json
import subprocess
import sys

import numpy as np
import pandas as pd
import geopandas as gpd
import xarray as xr

from geoglue.resample import resample
from geoglue.util import read_geotiff
from geoglue.zonalstats import zonalstats

HOME = Path.home()
ROOT = HOME / "DART_HCMC"
SCRATCH = HOME / ".local/share/dart-pipeline/scratch/HCM/era5"

DAILY = SCRATCH / "HCM-2015-era5.daily_mean.nc"
POP = ROOT / "derived/worldpop/worldpop_2015_HCMC_buffer005.tif"
SHP = ROOT / "boundaries/HCMC_22.shp"

OUT = ROOT / "outputs/HCMC_2015_temperature_humidity_daily.csv"
QC = ROOT / "outputs/HCMC_2015_QC.json"
RESAMPLED = ROOT / "derived/HCMC_2015_daily_mean_resampled.nc"

OPERATION = "mean(coverage_weight=area_spherical_km2)"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    print("=== DART HCMC 2015 ===", flush=True)

    for path in (DAILY, POP, SHP):
        if not path.is_file():
            raise FileNotFoundError(path)

    if OUT.exists() or QC.exists():
        raise FileExistsError(
            "Output 2015 already exists. Preserve and review it "
            "before running again."
        )

    # 1. Validate original DART daily means
    with xr.open_dataset(DAILY) as ds:
        if not {"t2m", "r"}.issubset(ds.data_vars):
            raise ValueError(f"Missing variables: {list(ds.data_vars)}")
        if ds.sizes.get("valid_time") != 365:
            raise ValueError("Expected 365 daily timesteps")

        dates = pd.DatetimeIndex(ds.valid_time.values)
        expected = pd.date_range("2015-01-01", "2015-12-31")
        if not dates.normalize().equals(expected):
            raise ValueError(
                f"Daily dates do not match 2015: "
                f"{dates.min()} to {dates.max()}"
            )
        if (dates != dates.normalize()).any():
            raise ValueError("Unexpected non-midnight daily timestamps")

        daily_tmin = float(ds.t2m.min(skipna=True))
        daily_tmax = float(ds.t2m.max(skipna=True))
        rh_min = float(ds.r.min(skipna=True))
        rh_max = float(ds.r.max(skipna=True))

    print("Daily input: PASS, 365 dates", flush=True)
    print("T2m range (K):", daily_tmin, daily_tmax, flush=True)
    print("RH range (%):", rh_min, rh_max, flush=True)

    if not (170 < daily_tmin < daily_tmax < 340):
        raise ValueError("Temperature requires review")
    if not (0 <= rh_min <= rh_max <= 100):
        raise ValueError("Relative humidity requires review")

    # 2. Read population crop and administrative polygons
    population = read_geotiff(POP).fillna(0)

    regions = gpd.read_file(SHP)
    if regions.crs is None:
        raise ValueError("Shapefile CRS missing")
    regions = regions.to_crs("EPSG:4326").reset_index(drop=True)

    if len(regions) != 22:
        raise ValueError("Expected exactly 22 administrative units")
    if not {"dist_id", "dist_name"}.issubset(regions.columns):
        raise ValueError("Missing dist_id or dist_name")

    # Clean strings in memory only; original shapefile untouched
    regions["dist_id"] = regions["dist_id"].astype(str).str.strip()
    regions["dist_name"] = regions["dist_name"].astype(str).str.strip()

    if (
        regions["dist_id"].duplicated().any()
        or regions["dist_id"].eq("").any()
        or regions["dist_name"].eq("").any()
        or regions.geometry.is_empty.any()
        or not regions.geometry.is_valid.all()
    ):
        raise ValueError("Invalid administrative geometry or identifiers")

    import rasterio
    with rasterio.open(POP) as p:
        west, south, east, north = regions.total_bounds
        b = p.bounds
        if not (
            b.left <= west and b.bottom <= south
            and b.right >= east and b.top >= north
        ):
            raise ValueError("Population crop does not cover all regions")
        print("Population grid:", p.height, "x", p.width, flush=True)

    # 3. Resample DART daily_mean to cropped WorldPop grid
    RESAMPLED.parent.mkdir(parents=True, exist_ok=True)

    if RESAMPLED.exists():
        print("Using existing resampled candidate; validating", flush=True)
    else:
        print("Running geoglue resample(remapbil)", flush=True)
        resample("remapbil", DAILY, population, RESAMPLED)

    with xr.open_dataset(RESAMPLED) as ds:
        expected_dims = {"valid_time": 365, "latitude": 110, "longitude": 94}
        if any(ds.sizes.get(k) != v for k, v in expected_dims.items()):
            raise ValueError(f"Unexpected resampled dimensions: {dict(ds.sizes)}")
        if not {"t2m", "r"}.issubset(ds.data_vars):
            raise ValueError("Resampled file missing temperature or RH")

        if not pd.DatetimeIndex(ds.valid_time.values).equals(dates):
            raise ValueError("Resampling changed time coordinates")

        print("Resampling: PASS", flush=True)

        # 4. Apply DART's geoglue exactextract operation
        print("Aggregating temperature", flush=True)
        temperature = zonalstats(
            ds["t2m"],
            regions,
            OPERATION,
            weights=population,
        ).values

        print("Aggregating relative humidity", flush=True)
        humidity = zonalstats(
            ds["r"],
            regions,
            OPERATION,
            weights=population,
        ).values

    expected_shape = (365, 22)
    if temperature.shape != expected_shape or humidity.shape != expected_shape:
        raise ValueError(
            f"Unexpected zonal result shapes: "
            f"{temperature.shape}, {humidity.shape}"
        )

    temperature_c = temperature - 273.15
    humidity_pct = humidity

    # 5. Build output: order = one day, then 22 regions
    result = pd.DataFrame({
        "date": np.repeat(dates.strftime("%Y-%m-%d"), 22),
        "district_id": np.tile(regions["dist_id"].to_numpy(), 365),
        "district_name": np.tile(regions["dist_name"].to_numpy(), 365),
        "temp_mean_c": temperature_c.reshape(-1),
        "rh_mean_pct": humidity_pct.reshape(-1),
    })

    # 6. Mandatory quality checks
    if len(result) != 8030:
        raise ValueError("Incorrect number of output rows")
    if result["district_id"].nunique() != 22:
        raise ValueError("Incorrect number of districts")
    if result.duplicated(["date", "district_id"]).any():
        raise ValueError("Duplicate district-date key")

    numeric = result[["temp_mean_c", "rh_mean_pct"]]
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("Missing or nonfinite temperature/humidity values")
    if not result["rh_mean_pct"].between(0, 100).all():
        raise ValueError("Humidity outside 0-100%")
    if not result["temp_mean_c"].between(-20, 60).all():
        raise ValueError("Implausible temperature: review required")

    # 7. Provenance and outputs
    report = {
        "year": 2015,
        "status": "PASS_NUMERICAL_AND_STRUCTURAL_QC",
        "rows": len(result),
        "dates": result["date"].nunique(),
        "districts": result["district_id"].nunique(),
        "temperature_min_c": float(result.temp_mean_c.min()),
        "temperature_max_c": float(result.temp_mean_c.max()),
        "rh_min_pct": float(result.rh_mean_pct.min()),
        "rh_max_pct": float(result.rh_mean_pct.max()),
        "daily_source": str(DAILY),
        "daily_source_sha256": sha256(DAILY),
        "worldpop_crop": str(POP),
        "worldpop_crop_sha256": sha256(POP),
        "shapefile": str(SHP),
        "resampling": "geoglue.resample: remapbil",
        "zonal_operation": OPERATION,
        "note": (
            "DART-derived custom cropped-WorldPop workflow. "
            "Daily timezone semantics and method validation "
            "require separate review."
        ),
        "python": sys.version,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT, index=False, encoding="utf-8-sig",
                  float_format="%.6f")
    QC.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("=== 2015 PROCESSING PASS ===", flush=True)
    print("CSV:", OUT, flush=True)
    print("QC:", QC, flush=True)
    print(result.head(5).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
