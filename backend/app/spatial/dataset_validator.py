from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import geopandas as gpd


SUPPORTED_RASTER_EXTENSIONS = {".tif", ".tiff"}
SUPPORTED_VECTOR_EXTENSIONS = {".geojson", ".gpkg", ".shp"}


@dataclass
class RasterValidation:
    path: str
    crs: str | None
    width: int
    height: int
    bands: int
    resolution_x: float
    resolution_y: float
    bounds: tuple[float, float, float, float]
    nodata: Any
    dtype: str
    valid_pixels: int
    nan_pixels: int
    total_pixels: int
    min_value: float | None
    max_value: float | None

    @property
    def valid_percentage(self) -> float:
        if self.total_pixels == 0:
            return 0.0
        return round(
            self.valid_pixels / self.total_pixels * 100,
            2,
        )


def validate_raster(path: Path) -> RasterValidation:
    with rasterio.open(path) as src:
        data = src.read(1, masked=True)

        # Get the underlying NumPy values and raster mask.
        raw_values = np.ma.getdata(data)
        masked = np.ma.getmaskarray(data)

        # A pixel is valid only when:
        # 1. It is not masked as NoData
        # 2. Its value is finite (not NaN or +/- infinity)
        finite = np.isfinite(raw_values)

        valid_mask = (~masked) & finite

        valid_values = raw_values[valid_mask]

        total_pixels = src.width * src.height

        valid_pixels = int(valid_mask.sum())

        # Pixels that are not masked but contain NaN/infinity.
        nan_pixels = int(
            ((~masked) & ~finite).sum()
        )

        min_value = (
            float(valid_values.min())
            if valid_values.size
            else None
        )

        max_value = (
            float(valid_values.max())
            if valid_values.size
            else None
        )

        return RasterValidation(
            path=str(path),
            crs=str(src.crs) if src.crs else None,
            width=src.width,
            height=src.height,
            bands=src.count,
            resolution_x=round(src.res[0], 8),
            resolution_y=round(src.res[1], 8),
            bounds=(
                round(src.bounds.left, 6),
                round(src.bounds.bottom, 6),
                round(src.bounds.right, 6),
                round(src.bounds.top, 6),
            ),
            nodata=src.nodata,
            dtype=str(src.dtypes[0]),
            valid_pixels=valid_pixels,
            nan_pixels=nan_pixels,
            total_pixels=total_pixels,
            min_value=min_value,
            max_value=max_value,
        )


def validate_vector(path: Path) -> dict[str, Any]:
    gdf = gpd.read_file(path)

    bounds = gdf.total_bounds

    return {
        "path": str(path),
        "features": len(gdf),
        "geometry_types": sorted(
            gdf.geometry.geom_type.dropna().unique().tolist()
        ),
        "crs": str(gdf.crs) if gdf.crs else None,
        "bounds": (
            round(float(bounds[0]), 6),
            round(float(bounds[1]), 6),
            round(float(bounds[2]), 6),
            round(float(bounds[3]), 6),
        ),
        "columns": list(gdf.columns),
    }


def print_raster(result: RasterValidation) -> None:
    print()
    print("=" * 70)
    print("RASTER")
    print("=" * 70)

    print(f"File             : {result.path}")
    print(f"CRS              : {result.crs}")
    print(
        f"Dimensions       : "
        f"{result.width} x {result.height}"
    )
    print(f"Bands            : {result.bands}")
    print(
        f"Resolution       : "
        f"{result.resolution_x} x {result.resolution_y}"
    )
    print(f"Bounds           : {result.bounds}")
    print(f"NoData           : {result.nodata}")
    print(f"Data type        : {result.dtype}")
    print(f"Valid pixels     : {result.valid_pixels:,}")
    print(f"NaN pixels       : {result.nan_pixels:,}")
    print(f"Total pixels     : {result.total_pixels:,}")
    print(
        f"Valid percentage : "
        f"{result.valid_percentage}%"
    )
    print(f"Minimum value    : {result.min_value}")
    print(f"Maximum value    : {result.max_value}")


def print_vector(result: dict[str, Any]) -> None:
    print()
    print("=" * 70)
    print("VECTOR")
    print("=" * 70)

    print(f"File          : {result['path']}")
    print(f"Features      : {result['features']}")
    print(f"Geometry      : {result['geometry_types']}")
    print(f"CRS           : {result['crs']}")
    print(f"Bounds        : {result['bounds']}")
    print(f"Columns       : {result['columns']}")


def discover_files(data_root: Path) -> list[Path]:
    files: list[Path] = []

    for path in data_root.rglob("*"):
        if not path.is_file():
            continue

        suffix = path.suffix.lower()

        if (
            suffix in SUPPORTED_RASTER_EXTENSIONS
            or suffix in SUPPORTED_VECTOR_EXTENSIONS
        ):
            files.append(path)

    return sorted(files)


def validate_dataset_directory(data_root: Path) -> None:
    print()
    print("=" * 70)
    print("DISASTER RISK INTELLIGENCE")
    print("FLOOD DATASET VALIDATION")
    print("=" * 70)

    print(f"Data root: {data_root}")

    if not data_root.exists():
        raise FileNotFoundError(
            f"Data directory does not exist: {data_root}"
        )

    files = discover_files(data_root)

    if not files:
        print("\nNo supported raster/vector files found.")
        return

    print(f"\nDiscovered {len(files)} supported files.")

    for path in files:
        try:
            suffix = path.suffix.lower()

            if suffix in SUPPORTED_RASTER_EXTENSIONS:
                result = validate_raster(path)
                print_raster(result)

            elif suffix in SUPPORTED_VECTOR_EXTENSIONS:
                result = validate_vector(path)
                print_vector(result)

        except Exception as exc:
            print()
            print("=" * 70)
            print("VALIDATION ERROR")
            print("=" * 70)
            print(f"File  : {path}")
            print(f"Error : {type(exc).__name__}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Disaster Risk Intelligence "
            "flood datasets."
        )
    )

    parser.add_argument(
        "--data-root",
        required=True,
        help="Path to the project's data directory.",
    )

    args = parser.parse_args()

    validate_dataset_directory(
        Path(args.data_root).resolve()
    )


if __name__ == "__main__":
    main()