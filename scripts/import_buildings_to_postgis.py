from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon


# ============================================================
# Configuration
# ============================================================

PROJECT_ROOT = Path(
    r"D:\python_projects\disaster-risk-intelligence"
)

INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "buildings"
    / "mumbai_building_footprints.geojson"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "buildings"
    / "mumbai_building_footprints.shp"
)


# ============================================================
# Geometry normalization
# ============================================================

def to_multipolygon(geom):
    """
    Convert Polygon to MultiPolygon.

    Keep MultiPolygon unchanged.

    Return None for unsupported, empty,
    or invalid geometries.
    """

    if geom is None or geom.is_empty:
        return None

    # Repair invalid geometry if possible
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
    print("GEE Building Footprints → Shapefile")
    print("=" * 70)

    print(f"Input : {INPUT_FILE}")
    print(f"Output: {OUTPUT_FILE}")
    print()

    # --------------------------------------------------------
    # Validate input
    # --------------------------------------------------------

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Input GeoJSON not found:\n{INPUT_FILE}"
        )

    # --------------------------------------------------------
    # Read GeoJSON
    # --------------------------------------------------------

    print("Reading GeoJSON...")

    gdf = gpd.read_file(INPUT_FILE)

    print(f"Features loaded: {len(gdf):,}")
    print(f"Original CRS   : {gdf.crs}")
    print()

    # --------------------------------------------------------
    # Validate source CRS
    # --------------------------------------------------------

    if gdf.crs is None:
        raise ValueError(
            "Input GeoJSON does not contain a CRS."
        )

    # GEE Open Buildings should be EPSG:4326
    print("Converting CRS to EPSG:4326...")

    gdf = gdf.to_crs("EPSG:4326")

    print(f"Output CRS: {gdf.crs}")
    print()

    # --------------------------------------------------------
    # Show original geometry types
    # --------------------------------------------------------

    print("Original geometry types:")

    print(
        gdf.geometry
        .geom_type
        .value_counts()
        .to_string()
    )

    print()

    # --------------------------------------------------------
    # Normalize geometry
    # --------------------------------------------------------

    print("Normalizing geometries to MultiPolygon...")

    gdf["geometry"] = gdf.geometry.apply(
        to_multipolygon
    )

    # --------------------------------------------------------
    # Remove unsupported / empty geometries
    # --------------------------------------------------------

    before_count = len(gdf)

    gdf = gdf[
        gdf.geometry.notna()
        & ~gdf.geometry.is_empty
    ].copy()

    removed = before_count - len(gdf)

    print(f"Removed invalid/unsupported geometries: {removed:,}")
    print()

    # --------------------------------------------------------
    # Validate normalized geometry
    # --------------------------------------------------------

    invalid_count = (
        ~gdf.geometry.is_valid
    ).sum()

    print(
        f"Invalid geometries after normalization: "
        f"{invalid_count:,}"
    )

    if invalid_count > 0:
        raise ValueError(
            "Invalid geometries remain after normalization."
        )

    # --------------------------------------------------------
    # Verify geometry types
    # --------------------------------------------------------

    print()
    print("Normalized geometry types:")

    print(
        gdf.geometry
        .geom_type
        .value_counts()
        .to_string()
    )

    # --------------------------------------------------------
    # Rename fields for Shapefile
    #
    # Shapefile field names are limited to 10 characters.
    # --------------------------------------------------------

    gdf = gdf.rename(
        columns={
            "area_in_meters": "area_m2",
            "full_plus_code": "plus_code",
            "longitude_latitude": "lon_lat",
        }
    )

    # --------------------------------------------------------
    # Keep required attributes only
    # --------------------------------------------------------

    required_columns = [
        "id",
        "area_m2",
        "confidence",
        "plus_code",
        "lon_lat",
        "geometry",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in gdf.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    gdf = gdf[required_columns].copy()

    # --------------------------------------------------------
    # Create output directory
    # --------------------------------------------------------

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Remove existing Shapefile components
    # --------------------------------------------------------

    for extension in [
        ".shp",
        ".shx",
        ".dbf",
        ".prj",
        ".cpg",
    ]:

        existing_file = OUTPUT_FILE.with_suffix(
            extension
        )

        if existing_file.exists():
            existing_file.unlink()

    # --------------------------------------------------------
    # Write Shapefile
    # --------------------------------------------------------

    print()
    print("Writing Shapefile...")

    gdf.to_file(
        OUTPUT_FILE,
        driver="ESRI Shapefile",
        encoding="UTF-8",
    )

    # --------------------------------------------------------
    # Final verification
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("CONVERSION COMPLETE")
    print("=" * 70)

    print(f"Output file : {OUTPUT_FILE}")
    print(f"Features    : {len(gdf):,}")
    print(f"CRS         : {gdf.crs}")
    print()

    print("Output geometry types:")

    print(
        gdf.geometry
        .geom_type
        .value_counts()
        .to_string()
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

        file_path = OUTPUT_FILE.with_suffix(
            extension
        )

        if file_path.exists():
            print(
                f"  {file_path.name} "
                f"({file_path.stat().st_size / (1024 * 1024):.2f} MB)"
            )

    print()
    print("Ready for PostGIS Import/Export Manager.")


if __name__ == "__main__":
    main()