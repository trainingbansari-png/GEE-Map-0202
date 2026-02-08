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

# ---------------- EE Init ----------------
def initialize_ee():
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
            st.sidebar.success("Earth Engine Initialized")
        except Exception as e:
            st.error(f"Error initializing Earth Engine: {e}")
            st.stop()

initialize_ee()

# ---------------- Session State ----------------
for k in ["ul_lat", "ul_lon", "lr_lat", "lr_lon"]:
    if k not in st.session_state:
        st.session_state[k] = None

# ---------------- Cloud Masking ----------------
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
    st.header("⚙️ Control Panel")
    view_mode = st.radio("Display Mode", ["Auto-Timelapse", "Manual Scrubber"])
    
    st.divider()
    satellite = st.selectbox("Select Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
    parameter = st.selectbox("Select Parameter", ["Level 1", "NDVI", "NDWI", "EVI", "NDSI", "SAVI"])

    start_date = st.date_input("Start Date", date(2023, 1, 1))
    end_date = st.date_input("End Date", date(2023, 12, 31))

# ---------------- Map Selection ----------------
st.subheader("1. Select your Area")
m = folium.Map(location=[22.0, 69.0], zoom_start=6)
Draw(draw_options={"polyline": False, "polygon": False, "circle": False, "marker": False, "rectangle": True}).add_to(m)
map_data = st_folium(m, height=350, width="100%", key="roi_map")

if map_data and map_data.get("all_drawings"):
    coords = map_data["all_drawings"][-1]["geometry"]["coordinates"][0]
    lons, lats = zip(*coords)
    st.session_state.ul_lat, st.session_state.lr_lat = min(lats), max(lats)
    st.session_state.ul_lon, st.session_state.lr_lon = min(lons), max(lons)

# ---------------- Processing Logic ----------------
if st.session_state.ul_lat and st.session_state.ul_lon:
    roi = ee.Geometry.Rectangle([st.session_state.ul_lon, st.session_state.ul_lat, 
                                 st.session_state.lr_lon, st.session_state.lr_lat])

    # Sensor Band Config
    config = {
        "Sentinel-2": {"id": "COPERNICUS/S2_SR_HARMONIZED", "red": "B4", "green": "B3", "blue": "B2", "nir": "B8", "swir": "B11", "max": 3000},
        "Landsat-8": {"id": "LANDSAT/LC08/C02/T1_L2", "red": "SR_B4", "green": "SR_B3", "blue": "SR_B2", "nir": "SR_B5", "swir": "SR_B6", "max": 20000},
        "Landsat-9": {"id": "LANDSAT/LC09/C02/T1_L2", "red": "SR_B4", "green": "SR_B3", "blue": "SR_B2", "nir": "SR_B5", "swir": "SR_B6", "max": 20000}
    }[satellite]

    collection = (ee.ImageCollection(config["id"])
                  .filterBounds(roi)
                  .filterDate(str(start_date), str(end_date))
                  .map(lambda img: mask_clouds(img, satellite))
                  .sort("system:time_start")
                  .limit(50))

    def apply_vis(image):
        if parameter == "NDVI":
            return image.normalizedDifference([config['nir'], config['red']]).visualize(min=-0.1, max=0.8, palette=['brown', 'yellow', 'green'])
        elif parameter == "NDWI":
            return image.normalizedDifference([config['green'], config['nir']]).visualize(min=-0.1, max=0.5, palette=['white', 'blue'])
        elif parameter == "NDSI":
            return image.normalizedDifference([config['green'], config['swir']]).visualize(min=0.0, max=0.8, palette=['black', 'blue', 'white'])
        elif parameter == "SAVI":
            savi = image.expression("((N - R) / (N + R + 0.5)) * (1.5)", {'N': image.select(config['nir']), 'R': image.select(config['red'])})
            return savi.visualize(min=-0.1, max=0.8, palette=['brown', 'yellow', 'green'])
        elif parameter == "Level 1":
            return image.visualize(bands=[config['red'], config['green'], config['blue']], min=0, max=config['max'])
        return image.visualize(bands=[config['red'], config['green'], config['blue']], min=0, max=config['max'])

    total_count = int(collection.size().getInfo())

    if total_count > 0:
        st.divider()
        
        if view_mode == "Auto-Timelapse":
            st.subheader("2. Auto-Timelapse (GIF)")
            video_col = collection.map(apply_vis)
            video_url = video_col.getVideoThumbURL({'dimensions': 720, 'region': roi, 'framesPerSecond': 5, 'format': 'gif'})
            st.image(video_url, use_container_width=True)
        
        else:
            st.subheader("2. Manual Frame Scrubber")
            frame_idx = st.slider("Move slider to change date", 1, total_count, 1)
            
            # Fetch specific image and its date
            img_list = collection.toList(total_count)
            selected_img = ee.Image(img_list.get(frame_idx - 1))
            
            # --- This part changes the date dynamically ---
            acq_date = selected_img.date().format('MMMM dd, YYYY | HH:mm').getInfo()
            st.info(f"📅 **Acquisition Date:** {acq_date}")
            
            # Display Image
            vis_img = apply_vis(selected_img)
            thumb_url = vis_img.getThumbURL({'dimensions': 1024, 'region': roi, 'format': 'png'})
            st.image(thumb_url, use_container_width=True, caption=f"Frame {frame_idx} - {parameter}")

    else:
        st.warning("No imagery found for this selection.")
