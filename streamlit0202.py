import streamlit as st
import ee
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date

# ---------------- Page Config ----------------
st.set_page_config(layout="wide", page_title="GEE Satellite Timelapse")
st.title("🌍 GEE Satellite Data Timelapse")

# ---------------- EE Init ----------------
def initialize_ee():
    if not ee.data._credentials:
        try:
            # Assumes GCP_SERVICE_ACCOUNT_JSON is in Streamlit Secrets
            service_account_info = dict(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=["https://www.googleapis.com/auth/earthengine"],
            )
            ee.Initialize(credentials)
        except Exception as e:
            st.error(f"Error initializing Earth Engine: {e}")
            st.stop()

initialize_ee()

# ---------------- Helper Functions ----------------
def get_sensor_config(satellite):
    """Returns band mapping and collection ID based on satellite choice."""
    if satellite == "Sentinel-2":
        return {
            "id": "COPERNICUS/S2_SR_HARMONIZED",
            "nir": "B8", "red": "B4", "green": "B3", "blue": "B2", "swir": "B11",
            "cloud_bit": 10, "cirrus_bit": 11, "qa": "QA60", "scale": 3000
        }
    else: # Landsat 8 or 9
        return {
            "id": "LANDSAT/LC08/C02/T1_L2" if satellite == "Landsat-8" else "LANDSAT/LC09/C02/T1_L2",
            "nir": "B5", "red": "B4", "green": "B3", "blue": "B2", "swir": "B6",
            "cloud_bit": 3, "shadow_bit": 4, "qa": "QA_PIXEL", "scale": 0.2 # Scaled for L2
        }

def mask_clouds(image, config, satellite):
    qa = image.select(config["qa"])
    if satellite == "Sentinel-2":
        mask = qa.bitwiseAnd(1 << config["cloud_bit"]).eq(0) \
                 .And(qa.bitwiseAnd(1 << config["cirrus_bit"]).eq(0))
    else:
        mask = qa.bitwiseAnd(1 << config["cloud_bit"]).eq(0) \
                 .And(qa.bitwiseAnd(1 << config["shadow_bit"]).eq(0))
    return image.updateMask(mask)

def apply_index(image, index_name, cfg):
    """Computes the requested spectral index."""
    if index_name == "NDVI":
        return image.normalizedDifference([cfg['nir'], cfg['red']]).rename('idx')
    elif index_name == "NDWI":
        return image.normalizedDifference([cfg['green'], cfg['nir']]).rename('idx')
    elif index_name == "NDMI":
        return image.normalizedDifference([cfg['nir'], cfg['swir']]).rename('idx')
    elif index_name == "Level 1":
        return image.select([cfg['red'], cfg['green'], cfg['blue']])
    return image.normalizedDifference([cfg['nir'], cfg['red']]).rename('idx')

# ---------------- Sidebar UI ----------------
with st.sidebar:
    st.header("⚙️ Parameters")
    satellite = st.selectbox("Select Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
    parameter = st.selectbox("Spectral Index", ["Level 1", "NDVI", "NDWI", "NDMI"])
    
    col_date1, col_date2 = st.columns(2)
    start_date = col_date1.date_input("Start", date(2023, 1, 1))
    end_date = col_date2.date_input("End", date(2023, 12, 31))
    
    fps = st.slider("Frames per second", 1, 15, 5)
    st.info("💡 Draw a rectangle on the map to define the timelapse area.")

# ---------------- Map Interface ----------------
m = folium.Map(location=[22.0, 69.0], zoom_start=6)
Draw(draw_options={
    "polyline": False, "polygon": False, "circle": False, 
    "marker": False, "circlemarker": False, "rectangle": True
}).add_to(m)

map_output = st_folium(m, height=450, width="100%")

# ---------------- Logic Execution ----------------
if map_output and map_output.get("all_drawings"):
    # Extract ROI from map
    roi_coords = map_output["all_drawings"][-1]["geometry"]["coordinates"][0]
    roi = ee.Geometry.Polygon(roi_coords)
    
    cfg = get_sensor_config(satellite)
    
    # Process Collection
    with st.spinner(f"Fetching {satellite} data..."):
        collection = (ee.ImageCollection(cfg["id"])
                      .filterBounds(roi)
                      .filterDate(str(start_date), str(end_date))
                      .map(lambda img: mask_clouds(img, cfg, satellite))
                      .sort("system:time_start")
                      .limit(50)) # Limit frames for stability

        count = collection.size().getInfo()
        
        if count > 0:
            st.success(f"Found {count} clear images. Generating timelapse...")
            
            # Prepare visualization frames
            def create_vis_frame(img):
                processed = apply_index(img, parameter, cfg)
                if parameter == "Level 1":
                    # Scaling for visual clarity
                    v_min, v_max = (0, 3000) if satellite == "Sentinel-2" else (7000, 12000)
                    return processed.visualize(min=v_min, max=v_max)
                else:
                    return processed.visualize(min=-0.2, max=0.8, palette=['brown', 'yellow', 'green'])

            video_col = collection.map(create_vis_frame)
            
            # Get Video URL
            video_url = video_col.getVideoThumbURL({
                'dimensions': 720,
                'fps': fps,
                'region': roi
            })
            
            # Display Results
            st.divider()
            st.image(video_url, caption=f"{satellite} {parameter} Timelapse", use_container_width=True)
            st.download_button("Download GIF", video_url, file_name="timelapse.gif")
        else:
            st.warning("No images found for the selected area and date range. Try a larger area or different dates.")
else:
    st.info("Please use the rectangle tool on the map to select an area.")
