from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape, Polygon, MultiPolygon
from shapely.ops import unary_union


# ============================================================
# Configuration
# ============================================================

PROJECT_ROOT = Path(
    r"D:\python_projects\disaster-risk-intelligence"
)

INPUT_RASTER = (
    PROJECT_ROOT
    / "data"
    / "flood_extent"
    / "mumbai_s1_flood_extent.tif"
)

OUTPUT_SHAPEFILE = (
    PROJECT_ROOT
    / "data"
    / "flood_extent"
    / "mumbai_s1_flood_extent.shp"
)


# ============================================================
# Geometry normalization
# ============================================================

def to_multipolygon(geom):
    """
    Normalize geometry to MultiPolygon.
    """

    if geom is None or geom.is_empty:
        return None

    # Repair invalid geometry
    if not geom.is_valid:
        geom = geom.buffer(0)

        if geom is None or geom.is_empty:
            return None

    if isinstance(geom, Polygon):
        return MultiPolygon([geom])

    if isinstance(geom, MultiPolygon):
        return geom

    return None


# ============================================================
# Main
# ============================================================

def main():

    print("=" * 70)
    print("Sentinel-1 Flood Raster -> Shapefile")
    print("=" * 70)

    print(f"Input : {INPUT_RASTER}")
    print(f"Output: {OUTPUT_SHAPEFILE}")
    print()

    if not INPUT_RASTER.exists():
        raise FileNotFoundError(
            f"Flood raster not found:\n{INPUT_RASTER}"
        )

    # --------------------------------------------------------
    # Read raster
    # --------------------------------------------------------

    with rasterio.open(INPUT_RASTER) as src:

        print("Raster CRS:", src.crs)
        print(
            "Raster size:",
            src.width,
            "x",
            src.height,
        )
        print("Resolution:", src.res)
        print("NoData:", src.nodata)

        raster = src.read(1)

        # ----------------------------------------------------
        # Inspect raster values
        # ----------------------------------------------------

        values, counts = np.unique(
            raster,
            return_counts=True,
        )

        print()
        print("Raster values:")

        for value, count in zip(values, counts):
            print(
                f"  {int(value)} = {int(count):,} pixels"
            )

        # ----------------------------------------------------
        # Flood mask
        #
        # 0 = non-flood
        # 1 = flood
        # ----------------------------------------------------

        flood_mask = raster == 1

        flood_pixel_count = int(
            flood_mask.sum()
        )

        print()
        print(
            "Flood pixels:",
            f"{flood_pixel_count:,}",
        )

        if flood_pixel_count == 0:
            raise ValueError(
                "No flood pixels with value = 1 were found."
            )

        # ----------------------------------------------------
        # Convert flooded pixels to polygons
        # ----------------------------------------------------

        print()
        print("Converting flooded pixels to polygons...")

        polygons = []

        for geometry, value in shapes(
            raster,
            mask=flood_mask,
            transform=src.transform,
        ):

            if value == 1:

                geom = shape(geometry)

                if not geom.is_empty:
                    polygons.append(geom)

        print(
            "Initial polygons:",
            f"{len(polygons):,}",
        )

        # ----------------------------------------------------
        # Dissolve flood polygons
        # ----------------------------------------------------

        print("Dissolving flood polygons...")

        flood_geometry = unary_union(
            polygons
        )

        print(
            "Dissolved geometry:",
            flood_geometry.geom_type,
        )

        # ----------------------------------------------------
        # Normalize to MultiPolygon
        # ----------------------------------------------------

        flood_geometry = to_multipolygon(
            flood_geometry
        )

        if flood_geometry is None:
            raise ValueError(
                "Unable to create valid MultiPolygon "
                "from flood raster."
            )

        # ----------------------------------------------------
        # Create GeoDataFrame
        # ----------------------------------------------------

        flood_gdf = gpd.GeoDataFrame(
            {
                "source": ["Sentinel-1"],
                "flood_val": [1],
                "flood_pixels": [
                    flood_pixel_count
                ],
            },
            geometry=[flood_geometry],
            crs=src.crs,
        )

    # --------------------------------------------------------
    # Ensure EPSG:4326
    # --------------------------------------------------------

    print()
    print("Source CRS:", flood_gdf.crs)

    flood_gdf = flood_gdf.to_crs(
        "EPSG:4326"
    )

    print(
        "Output CRS:",
        flood_gdf.crs,
    )

    # --------------------------------------------------------
    # Validate geometry
    # --------------------------------------------------------

    invalid_count = (
        ~flood_gdf.geometry.is_valid
    ).sum()

    print(
        "Invalid geometries:",
        invalid_count,
    )

    if invalid_count > 0:

        print(
            "Repairing invalid geometries..."
        )

        flood_gdf.geometry = (
            flood_gdf.geometry.buffer(0)
        )

    # --------------------------------------------------------
    # Calculate flood area in metric CRS
    # --------------------------------------------------------

    metric_gdf = flood_gdf.to_crs(
        "EPSG:6933"
    )

    flood_area_m2 = float(
        metric_gdf.geometry.area.iloc[0]
    )

    flood_area_km2 = (
        flood_area_m2 / 1_000_000
    )

    print()
    print("Flood area:")
    print(
        f"  m²  : {flood_area_m2:,.2f}"
    )
    print(
        f"  km² : {flood_area_km2:.6f}"
    )

    # --------------------------------------------------------
    # Output directory
    # --------------------------------------------------------

    OUTPUT_SHAPEFILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Remove previous Shapefile
    # --------------------------------------------------------

    for extension in [
        ".shp",
        ".shx",
        ".dbf",
        ".prj",
        ".cpg",
    ]:

        file_path = (
            OUTPUT_SHAPEFILE.with_suffix(
                extension
            )
        )

        if file_path.exists():
            file_path.unlink()

    # --------------------------------------------------------
    # Write Shapefile
    # --------------------------------------------------------

    print()
    print("Writing Shapefile...")

    flood_gdf.to_file(
        OUTPUT_SHAPEFILE,
        driver="ESRI Shapefile",
        encoding="UTF-8",
    )

    # --------------------------------------------------------
    # Final output
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("FLOOD SHAPEFILE CREATED")
    print("=" * 70)

    print(
        "Shapefile:",
        OUTPUT_SHAPEFILE,
    )

    print(
        "Features:",
        len(flood_gdf),
    )

    print(
        "CRS:",
        flood_gdf.crs,
    )

    print(
        "Geometry:",
        flood_gdf.geometry.iloc[0].geom_type,
    )

    print(
        f"Flood area: {flood_area_km2:.6f} km²"
    )

    print()
    print("Output files:")

    for extension in [
        ".shp",
        ".shx",
        ".dbf",
        ".prj",
        ".cpg",
    ]:

        file_path = (
            OUTPUT_SHAPEFILE.with_suffix(
                extension
            )
        )

        if file_path.exists():

            size_mb = (
                file_path.stat().st_size
                / (1024 * 1024)
            )

            print(
                f"  {file_path.name} "
                f"({size_mb:.2f} MB)"
            )


if __name__ == "__main__":
    main()