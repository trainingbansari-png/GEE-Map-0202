import streamlit as st
import ee
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date, datetime

# ---------------- Page Config ----------------
st.set_page_config(layout="wide", page_title="GEE Satellite Data Viewer")
st.title("🌍 GEE Satellite Data Viewer")

# ---------------- Session State ----------------
# Initialize all keys to avoid AttributeErrors
for k in ["ul_lat", "ul_lon", "lr_lat", "lr_lon", "frame_idx", "is_playing", "index"]:
    if k not in st.session_state:
        st.session_state[k] = None

if st.session_state.frame_idx is None:
    st.session_state.frame_idx = 1
if st.session_state.is_playing is None:
    st.session_state.is_playing = False
if st.session_state.index is None:
    st.session_state.index = "Level 1"

# ---------------- EE Init ----------------
def initialize_ee():
    # Robust check for existing initialization
    try:
        ee.data.getSummary()
    except Exception:
        try:
            service_account_info = dict(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
            credentials = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=["https://www.googleapis.com/auth/earthengine"],
            )
            ee.Initialize(credentials)
            st.success("Earth Engine initialized successfully.")
        except Exception as e:
            st.error(f"Error initializing Earth Engine: {e}")
            st.stop()

initialize_ee()

# ---------------- Cloud Masking Functions ----------------
def mask_clouds(image, satellite):
    if satellite == "Sentinel-2":
        qa = image.select('QA60')
        mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
        return image.updateMask(mask)
    elif satellite in ["Landsat-8", "Landsat-9"]:
        qa = image.select('QA_PIXEL')
        mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
        return image.updateMask(mask)
    return image

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("🧭 Area of Interest")
    st.info("Draw a rectangle on the map to define your ROI.")
    
    # Coordinates Display/Edit
    ul_lat = st.number_input("Upper Left Latitude", value=st.session_state.ul_lat if st.session_state.ul_lat else 0.0, format="%.6f")
    ul_lon = st.number_input("Upper Left Longitude", value=st.session_state.ul_lon if st.session_state.ul_lon else 0.0, format="%.6f")
    lr_lat = st.number_input("Lower Right Latitude", value=st.session_state.lr_lat if st.session_state.lr_lat else 0.0, format="%.6f")
    lr_lon = st.number_input("Lower Right Longitude", value=st.session_state.lr_lon if st.session_state.lr_lon else 0.0, format="%.6f")
    
    st.session_state.ul_lat, st.session_state.ul_lon = ul_lat, ul_lon
    st.session_state.lr_lat, st.session_state.lr_lon = lr_lat, lr_lon

    st.header("📅 Date Filter")
    start_date = st.date_input("Start Date", date(2023, 1, 1))
    end_date = st.date_input("End Date", date(2023, 12, 31))

    st.header("🛰️ Satellite")
    satellite = st.selectbox("Select Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])

    st.header("🔢 Select Parameter")
    parameter = st.selectbox("Select Parameter", ["Level 1", "NDVI", "NDWI", "EVI"])
    st.session_state.index = parameter

# ---------------- Map Selection ----------------
st.subheader("1. Select your Area")
m = folium.Map(location=[22.0, 69.0], zoom_start=6)
Draw(draw_options={"polyline": False, "polygon": False, "circle": False, "marker": False, "rectangle": True}).add_to(m)
map_data = st_folium(m, height=400, width="100%", key="roi_map")

if map_data and map_data.get("all_drawings"):
    coords = map_data["all_drawings"][-1]["geometry"]["coordinates"][0]
    lons, lats = zip(*coords)
    st.session_state.ul_lat, st.session_state.lr_lat = min(lats), max(lats)
    st.session_state.ul_lon, st.session_state.lr_lon = min(lons), max(lons)

# ---------------- Processing Logic ----------------
if st.session_state.ul_lat and st.session_state.ul_lon:
    roi = ee.Geometry.Rectangle([st.session_state.ul_lon, st.session_state.ul_lat, 
                                 st.session_state.lr_lon, st.session_state.lr_lat])

    col_id = {"Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED", "Landsat-8": "LANDSAT/LC08/C02/T1_L2", "Landsat-9": "LANDSAT/LC09/C02/T1_L2"}[satellite]
    
    # Define Band Mapping based on sensor
    bands = {
        "Sentinel-2": {'red': 'B4', 'green': 'B3', 'blue': 'B2', 'nir': 'B8'},
        "Landsat-8": {'red': 'SR_B4', 'green': 'SR_B3', 'blue': 'SR_B2', 'nir': 'SR_B5'},
        "Landsat-9": {'red': 'SR_B4', 'green': 'SR_B3', 'blue': 'SR_B2', 'nir': 'SR_B5'}
    }[satellite]

    collection = (ee.ImageCollection(col_id)
                  .filterBounds(roi)
                  .filterDate(str(start_date), str(end_date))
                  .map(lambda img: mask_clouds(img, satellite))
                  .sort("system:time_start")
                  .limit(30))

    def compute_vis(image):
        if st.session_state.index == "NDVI":
            idx = image.normalizedDifference([bands['nir'], bands['red']])
            return idx.visualize(min=-0.1, max=0.8, palette=['brown', 'yellow', 'green'])
        elif st.session_state.index == "NDWI":
            idx = image.normalizedDifference([bands['green'], bands['nir']])
            return idx.visualize(min=-0.1, max=0.5, palette=['white', 'blue'])
        elif st.session_state.index == "Level 1":
            # Scale for SR data (S2 is 0-10000, Landsat is scaled differently)
            v_max = 3000 if satellite == "Sentinel-2" else 15000
            return image.visualize(bands=[bands['red'], bands['green'], bands['blue']], min=0, max=v_max)
        return image.visualize(bands=[bands['red'], bands['green'], bands['blue']], min=0, max=3000)

    total_count = collection.size().getInfo()

    if total_count > 0:
        st.divider()
        st.subheader("2. Generated Timelapse")
        
        # Create a collection of RGB visualized frames
        video_col = collection.map(compute_vis)
        
        # Request video URL from GEE
        video_url = video_col.getVideoThumbURL({
            'dimensions': 720,
            'region': roi,
            'framesPerSecond': 5,
            'format': 'mp4'
        })
        
        st.video(video_url)
        st.write(f"Showing {total_count} frames from {satellite}")
    else:
        st.warning("No images found for this area/date range.")
