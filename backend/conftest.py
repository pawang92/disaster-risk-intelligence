import os
import pyproj

PROJ_DATA = (
    r"D:\python_projects\geoai-copilot\venv"
    r"\Lib\site-packages\rasterio\proj_data"
)

os.environ["PROJ_DATA"] = PROJ_DATA
os.environ["PROJ_LIB"] = PROJ_DATA
pyproj.datadir.set_data_dir(PROJ_DATA)