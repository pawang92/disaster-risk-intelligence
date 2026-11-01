from geopandas import gpd

data = gpd.read_file(r"D:\python_projects\disaster-risk-intelligence\data\buildings\mumbai_building_footprints.geojson")

print(data.columns) #data.columns