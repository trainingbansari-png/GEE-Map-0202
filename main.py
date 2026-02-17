from fastapi import FastAPI, Query
import ee
from google.oauth2 import service_account
import json

app = FastAPI()

# ---------------- EE Initialization ----------------
def initialize_ee():
    try:
        # Load your service account key
        with open("gcp_key.json") as f:
            info = json.load(f)
        credentials = service_account.Credentials.from_service_account_info(info)
        ee.Initialize(credentials)
        print("Earth Engine Initialized Successfully")
    except Exception as e:
        print(f"EE Init Error: {e}")

initialize_ee()

# ---------------- Helper Logic (From your Original Code) ----------------
def get_band_map(satellite):
    if "Sentinel" in satellite:
        return {'red': 'B4', 'green': 'B3', 'blue': 'B2', 'nir': 'B8', 'swir1': 'B11'}
    return {'red': 'B4', 'green': 'B3', 'blue': 'B2', 'nir': 'B5', 'swir1': 'B6'}

def mask_clouds(image, satellite):
    if "Sentinel" in satellite:
        qa = image.select('QA60')
        mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
    else: 
        qa = image.select('QA_PIXEL')
        mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
    return image.updateMask(mask)

def apply_parameter(image, parameter, satellite):
    bm = get_band_map(satellite)
    if parameter == "Level1": return image
    
    pairs = {
        "NDVI": [bm['nir'], bm['red']], 
        "NDWI": [bm['green'], bm['nir']],
        "MNDWI": [bm['green'], bm['swir1']], 
        "NDSI": [bm['green'], bm['swir1']]
    }
    
    if parameter in pairs:
        return image.normalizedDifference(pairs[parameter]).rename(parameter)
    
    if parameter == "EVI":
        return image.expression(
            '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {'NIR': image.select(bm['nir']), 'RED': image.select(bm['red']), 'BLUE': image.select(bm['blue'])}
        ).rename(parameter)
    return image

# ---------------- API Endpoint ----------------
@app.get("/generate_timelapse")
def generate_timelapse(
    u_lat: float, u_lon: float, l_lat: float, l_lon: float, 
    satellite: str = "Sentinel-2", 
    parameter: str = "NDVI",
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31"
):
    roi = ee.Geometry.Rectangle([u_lon, l_lat, l_lon, u_lat])
    col_id = {
        "Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED", 
        "Landsat-8": "LANDSAT/LC08/C02/T1_L2", 
        "Landsat-9": "LANDSAT/LC09/C02/T1_L2"
    }[satellite]

    collection = (ee.ImageCollection(col_id)
                  .filterBounds(roi)
                  .filterDate(start_date, end_date)
                  .map(lambda img: mask_clouds(img, satellite))
                  .sort("system:time_start")
                  .limit(20))

    # Visualization Setup
    vis = {"min": -1, "max": 1, "palette": ['#ffffff', '#ce7e45', '#fcd163', '#66a000', '#056201']}
    
    video_col = collection.map(lambda i: apply_parameter(i, parameter, satellite).visualize(**vis).clip(roi))
    
    video_url = video_col.getVideoThumbURL({
        'dimensions': 600, 
        'region': roi, 
        'framesPerSecond': 5, 
        'crs': 'EPSG:3857'
    })

    return {"video_url": video_url}