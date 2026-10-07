from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.windows import Window


@dataclass(frozen=True, slots=True)
class PopulationExposureResult:
    """Population exposure derived from a flood mask and population raster."""

    population_at_risk: float
    flooded_area_sq_km: float
    affected_population_percentage: float
    source: str
    population_dataset: str
    flood_mask_dataset: str
    population_resolution_x: float
    population_resolution_y: float


class PopulationExposureAdapter:
    """
    Estimate population exposed to a flood extent.

    The population raster contains estimated people per population cell.
    The flood raster is a binary/continuous flood mask where 1 means
    flooded. Because the two rasters normally have different resolutions,
    the flood mask is reprojected onto the population grid using
    area averaging.

    Exposure is calculated as:

        sum(population_cell * flooded_fraction)

    This avoids duplicating population counts when a ~10 m flood raster
    is aligned to a ~100 m population raster.
    """

    def __init__(
        self,
        population_path: str | Path,
        flood_mask_path: str | Path,
    ) -> None:
        self.population_path = Path(population_path)
        self.flood_mask_path = Path(flood_mask_path)

        if not self.population_path.exists():
            raise FileNotFoundError(
                f"Population raster not found: {self.population_path}"
            )

        if not self.flood_mask_path.exists():
            raise FileNotFoundError(
                f"Flood mask raster not found: {self.flood_mask_path}"
            )

    def calculate(self) -> PopulationExposureResult:
        """
        Calculate population exposed to the flood extent.

        The population raster is cropped to the flood raster bounds before
        reprojection so a large country-wide WorldPop raster does not need
        to be loaded entirely into memory.
        """
        with rasterio.open(self.population_path) as population_src:
            if population_src.crs is None:
                raise ValueError(
                    "Population raster does not contain a CRS."
                )

            with rasterio.open(self.flood_mask_path) as flood_src:
                if flood_src.crs is None:
                    raise ValueError(
                        "Flood mask raster does not contain a CRS."
                    )

                population_window = self._population_window(
                    population_src,
                    flood_src,
                )

                if population_window.width <= 0 or population_window.height <= 0:
                    raise ValueError(
                        "Flood mask does not overlap the population raster."
                    )

                population_data = population_src.read(
                    1,
                    window=population_window,
                    masked=True,
                )

                destination_transform = population_src.window_transform(
                    population_window
                )

                population_values = np.ma.filled(
                    population_data,
                    0.0,
                ).astype(np.float64, copy=False)

                valid_population = ~np.ma.getmaskarray(population_data)

                flood_fraction = np.zeros(
                    population_values.shape,
                    dtype=np.float32,
                )

                reproject(
                    source=rasterio.band(flood_src, 1),
                    destination=flood_fraction,
                    src_transform=flood_src.transform,
                    src_crs=flood_src.crs,
                    src_nodata=flood_src.nodata,
                    dst_transform=destination_transform,
                    dst_crs=population_src.crs,
                    dst_nodata=0.0,
                    resampling=Resampling.average,
                )

                flood_fraction = np.nan_to_num(
                    flood_fraction,
                    nan=0.0,
                    posinf=0.0,
                    neginf=0.0,
                )
                flood_fraction = np.clip(
                    flood_fraction,
                    0.0,
                    1.0,
                )

                total_population = float(
                    np.sum(
                        population_values[valid_population],
                        dtype=np.float64,
                    )
                )

                population_at_risk = float(
                    np.sum(
                        (
                            population_values
                            * flood_fraction
                        )[valid_population],
                        dtype=np.float64,
                    )
                )

                flooded_area_sq_km = self._calculate_flooded_area_sq_km(
                    flood_src
                )

                percentage = (
                    population_at_risk / total_population * 100.0
                    if total_population > 0
                    else 0.0
                )

                return PopulationExposureResult(
                    population_at_risk=round(
                        max(0.0, population_at_risk),
                        2,
                    ),
                    flooded_area_sq_km=round(
                        max(0.0, flooded_area_sq_km),
                        4,
                    ),
                    affected_population_percentage=round(
                        max(0.0, min(100.0, percentage)),
                        2,
                    ),
                    source="WorldPop + Sentinel-1",
                    population_dataset=self.population_path.name,
                    flood_mask_dataset=self.flood_mask_path.name,
                    population_resolution_x=float(
                        population_src.res[0]
                    ),
                    population_resolution_y=float(
                        population_src.res[1]
                    ),
                )

    @staticmethod
    def _population_window(
        population_src: rasterio.io.DatasetReader,
        flood_src: rasterio.io.DatasetReader,
    ) -> Window:
        """Return a population-grid window covering the flood bounds."""

        transformer = Transformer.from_crs(
            flood_src.crs,
            population_src.crs,
            always_xy=True,
        )

        left, bottom, right, top = flood_src.bounds

        xs, ys = zip(
            *(
                transformer.transform(x, y)
                for x, y in (
                    (left, bottom),
                    (left, top),
                    (right, bottom),
                    (right, top),
                )
            )
        )

        bounds = (
            min(xs),
            min(ys),
            max(xs),
            max(ys),
        )

        window = population_src.window(*bounds)

        # Clamp the requested window to the actual population raster.
        full_window = Window(
            col_off=0,
            row_off=0,
            width=population_src.width,
            height=population_src.height,
        )
        window = window.intersection(full_window)

        return window.round_offsets().round_lengths()

    @staticmethod
    def _calculate_flooded_area_sq_km(
        flood_src: rasterio.io.DatasetReader,
    ) -> float:
        """
        Calculate flood area in square kilometres.

        This mirrors the flood extent adapter's projected-area approach.
        """
        from rasterio.crs import CRS
        from rasterio.warp import calculate_default_transform

        projected_crs = CRS.from_string("EPSG:6933")

        transform, width, height = calculate_default_transform(
            flood_src.crs,
            projected_crs,
            flood_src.width,
            flood_src.height,
            *flood_src.bounds,
        )

        destination = np.zeros(
            (height, width),
            dtype=np.float32,
        )

        reproject(
            source=rasterio.band(flood_src, 1),
            destination=destination,
            src_transform=flood_src.transform,
            src_crs=flood_src.crs,
            dst_transform=transform,
            dst_crs=projected_crs,
            resampling=Resampling.nearest,
        )

        flooded_pixels = int(
            np.count_nonzero(destination > 0)
        )

        pixel_area_sq_m = abs(
            transform.a * transform.e
        )

        return (
            flooded_pixels
            * pixel_area_sq_m
            / 1_000_000
        )
