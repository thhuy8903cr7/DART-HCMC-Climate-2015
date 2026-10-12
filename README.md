# DART-HCMC-Climate-2015
Replication of the DART-Pipeline workflow to extract daily ERA5 temperature and relative humidity data for Ho Chi Minh City, Vietnam (2015).
# Daily temperature and relative humidity in Ho Chi Minh City (2015)

This small project is for **methodological review**. I used the [DART-Pipeline](https://github.com/kraemer-lab/DART-Pipeline) to prepare ERA5 weather data and a short custom Python workflow to produce daily estimates for **22 districts of Ho Chi Minh City (HCMC), Vietnam**. The same workflow is intended for 2016–2024 after checking 2015.

## Files in this repository

| File | Purpose |
| --- | --- |
| `crop_worldpop.py` | Creates a small WorldPop raster covering HCMC and a 0.05° buffer, without changing source pixel values or resolution. |
| `process_2015.py` | Resamples the DART daily ERA5 data to that raster, summarizes values for 22 districts, and exports a CSV. |
| `README.md` | Brief overview and instructions. |

This is **not a standalone implementation of DART**. `process_2015.py` starts with a daily NetCDF file already prepared by DART. The raw ERA5 data, WorldPop source raster, and district shapefile are not included here.

## Data and methods

- **Weather:** ERA5 hourly reanalysis data, processed with DART. For 2015, DART needs the end of 2014 to align hourly observations with HCMC local time (**UTC+7**).
- **Temperature:** ERA5 2-m air temperature (`t2m`), reported as daily mean in °C (converted from Kelvin).
- **Relative humidity:** Calculated by DART from hourly 2-m temperature and dew-point temperature using MetPy, then averaged by local day; reported in %.
- **Population raster:** WorldPop 2015, used as the **target spatial grid** (~1 km). `crop_worldpop.py` selects whole original pixels within the HCMC bounding rectangle plus a 0.05° buffer. The original raster is not modified.
- **Spatial processing:** `geoglue.resample("remapbil", ...)`, following DART's CDO bilinear resampling for daily means; district summaries use `geoglue.zonalstats()` / ExactExtract with `mean(coverage_weight=area_spherical_km2)`.
- **Important:** The result is a **spherical-area-weighted district mean, not a population-weighted mean**. WorldPop defines the grid, but the `mean` operation does not weight the weather values by population. This was checked against `weighted_mean` in a small test.
- **Administrative boundaries:** A fixed 22-district shapefile (`HCMC_22.shp`) is used for the entire analysis. Applying these boundaries retrospectively to 2015 is a research choice.

## Inputs expected on the local machine

The scripts currently use the paths from my WSL/Ubuntu setup (`~` means the Linux home directory):

```text
~/.local/share/dart-pipeline/sources/VNM/worldpop/
    vnm_ppp_2015_1km_Aggregated_UNadj.tif
~/.local/share/dart-pipeline/scratch/HCM/era5/
    HCM-2015-era5.daily_mean.nc
~/DART_HCMC/boundaries/HCMC_22.shp  (+ shapefile sidecars)
```

The intermediate `daily_mean.nc` contains `t2m` and `r` for 365 local days. It was created using the DART ERA5 workflow with the custom `HCM` region (`tz = "+07:00"`). DART source commit used for the analysis: `f85f92094898a1422b3c1c8db1a9c92a0d833cbe`.

## How I ran the two scripts

With DART and its Python dependencies installed, and the input files above already prepared:

```bash
cd ~/DART-Pipeline
uv run python /path/to/crop_worldpop.py
uv run python /path/to/process_2015.py
```

The output paths in `process_2015.py` are currently tied to `~/DART_HCMC/`, so these would need changing on another computer. Both scripts avoid overwriting existing outputs.

The main CSV is:

```text
~/DART_HCMC/outputs/HCMC_2015_temperature_humidity_daily.csv
```

It has **8,030 rows** (365 days × 22 districts) and these columns:

`date`, `district_id`, `district_name`, `temp_mean_c`, `rh_mean_pct`.

## Checks performed for 2015

- The WorldPop crop is **110 × 94 pixels**, retains the source pixel values / CRS / resolution, and covers all 22 district polygons.
- In a seven-day test of the `daily_min` raster, the values on the cropped grid matched the corresponding pixels of the nationwide-grid interpolation.
- For one test day, district-level temperature using the full versus cropped WorldPop gave the **same result** (maximum absolute difference = 0).
- In a separate test, DART's `mean(coverage_weight=area_spherical_km2)` exactly matched the area-weighted result; a population-weighted alternative was different.
- The 2015 export passed the script's basic checks for number of days/districts, missing values, duplicate district-day records, and plausible value ranges.

These checks support the approach, but they are not a complete external validation. On the original laptop, some Python executions also printed `Error in sys.excepthook` at exit; the generated outputs should still be reviewed rather than assuming that message is harmless.

## Feedback I would appreciate

1. Is the **area-weighted district mean** a suitable measure of weather exposure for our study, or would a population-weighted mean be preferable?
2. Is cropping the WorldPop target grid before resampling and spatial aggregation a reasonable optimization?
3. Are the UTC+7 daily alignment and relative-humidity calculation appropriate for the intended analysis?

**Source framework:** [Kraemer Lab — DART-Pipeline](https://github.com/kraemer-lab/DART-Pipeline). The cropping and CSV-export scripts are small custom additions for this H
