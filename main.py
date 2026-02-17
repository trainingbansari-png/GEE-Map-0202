import os
import json
import ee
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google.oauth2 import service_account

app = FastAPI()

# ---------------- 1. Robust EE Initialization ----------------
def initialize_ee():
    try:
        # Get absolute path to the key file
        base_dir = os.path.dirname(os.path.abspath("D:\gcp_key.json.json"))
        key_path = os.path.join(base_dir, "gcp_key.json")
        
        if not os.path.exists(key_path):
            raise FileNotFoundError(f"Key file missing at {key_path}")

        with open(key_path) as f:
            info = json.load(f)
        
        credentials = service_account.Credentials.from_service_account_info(info)
        
        # Initialize with your specific project ID
        ee.Initialize(
            credentials=credentials,
            project='my-project-0102-486108'
        )
        print("✅ Earth Engine Initialized Successfully!")
    except Exception as e:
        print(f"❌ Initialization Error: {e}")

initialize_ee()

# ---------------- 2. Request Model ----------------
class ROIRequest(BaseModel):
    ul_lat: float
    ul_lon: float
    lr_lat: float
    lr_lon: float
    satellite: str = "Sentinel-2"
    parameter: str = "NDVI"

# ---------------- 3. Core Logic (Simplified for API) ----------------
def get_bands(sat):
    if "Sentinel" in sat:
        return {'red': 'B4', 'nir': 'B8'}
    return {'red': 'B4', 'nir': 'B5'}

@app.post("/analyze")
async def analyze_area(data: ROIRequest):
    try:
        roi = ee.Geometry.Rectangle([data.ul_lon, data.lr_lat, data.lr_lon, data.ul_lat])
        
        col_id = "COPERNICUS/S2_SR_HARMONIZED" if "Sentinel" in data.satellite else "LANDSAT/LC08/C02/T1_L2"
        
        # Get latest image
        img = ee.ImageCollection(col_id).filterBounds(roi).sort("system:time_start", False).first()
        
        # Calculate Index (e.g., NDVI)
        bm = get_bands(data.satellite)
        ndvi = img.normalizedDifference([bm['nir'], bm['red']]).rename('NDVI')
        
        # Get Stats
        stats = ndvi.reduceRegion(reducer=ee.Reducer.mean(), geometry=roi, scale=30).getInfo()
        
        # Get Preview URL
        vis = {"min": 0, "max": 1, "palette": ['white', 'green']}
        map_url = ndvi.getMapId(vis)['tile_fetcher'].url_format
        
        return {
            "status": "success",
            "mean_value": stats.get('NDVI'),
            "map_tiles": map_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)