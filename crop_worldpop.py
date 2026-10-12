#!/usr/bin/env python3
"""Crop the 2015 Vietnam WorldPop raster to a buffered HCMC window.

This is the same pixel-preserving window-crop method used for the 2015
DART-HCMC analysis. It does not resample, mask, or modify the source raster.
Run from the DART-Pipeline environment (which provides rasterio).
"""

from pathlib import Path
import math

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds, transform

HOME = Path.home()
SOURCE = (
    HOME
    / ".local/share/dart-pipeline/sources/VNM/worldpop"
    / "vnm_ppp_2015_1km_Aggregated_UNadj.tif"
)
OUTPUT = (
    HOME
    / "DART_HCMC/derived/worldpop"
    / "worldpop_2015_HCMC_buffer005.tif"
)

# HCM bbox from the project's regions.toml: [west, south, east, north].
HCMC_BBOX = (106.356674195, 10.354226112, 107.027275086, 11.160309792)
BUFFER_DEGREES = 0.05  # Experimental spatial buffer; not a DART default.


def crop(source: Path = SOURCE, output: Path = OUTPUT) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"WorldPop source not found: {source}")
    if output.exists():
        raise FileExistsError(f"Output exists; refusing to overwrite: {output}")

    west, south, east, north = HCMC_BBOX
    buffer = BUFFER_DEGREES
    output.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(source) as src:
        if src.crs is None or src.crs.to_epsg() != 4326:
            raise ValueError(f"Expected EPSG:4326, got {src.crs}")

        raw = from_bounds(
            west - buffer,
            south - buffer,
            east + buffer,
            north + buffer,
            transform=src.transform,
        )

        # Expand the window to whole source pixels; never resample values.
        col0 = max(0, math.floor(raw.col_off))
        row0 = max(0, math.floor(raw.row_off))
        col1 = min(src.width, math.ceil(raw.col_off + raw.width))
        row1 = min(src.height, math.ceil(raw.row_off + raw.height))
        window = Window(col0, row0, col1 - col0, row1 - row0)
        if window.width <= 0 or window.height <= 0:
            raise ValueError("Crop window is outside the source raster")

        profile = src.profile.copy()
        profile.update(
            width=int(window.width),
            height=int(window.height),
            transform=transform(window, src.transform),
        )
        pixels = src.read(window=window)
        with rasterio.open(output, "w", **profile) as dst:
            dst.write(pixels)

        # Verify exact pixel identity immediately after writing the new file.
        with rasterio.open(output) as dst:
            if not np.array_equal(pixels, dst.read(), equal_nan=True):
                raise RuntimeError("Output pixel values differ from source window")
            b = dst.bounds
            covers_bbox = (
                b.left <= west and b.bottom <= south
                and b.right >= east and b.top >= north
            )
            if not covers_bbox or dst.crs != src.crs or dst.res != src.res:
                raise RuntimeError("Output bbox, CRS, or resolution is unexpected")
            print("=== WORLDPOP CROP: PASS ===")
            print("Output:", output)
            print("Grid:", dst.height, "x", dst.width)
            print("CRS:", dst.crs)
            print("Bounds:", dst.bounds)
            print("Pixel size:", dst.res)
            print("Size (MiB):", round(output.stat().st_size / 1024**2, 3))


if __name__ == "__main__":
    crop()
