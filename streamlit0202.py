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
for k in ["ul_lat", "ul_lon", "lr_lat", "lr_lon", "index"]:
    if k not in st.session_state:
        st.session_state[k] = None

if st.session_state.index is None:
    st.session_state.index = "Level 1"

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
    st.header("⚙️ Settings")
    view_mode = st.radio("Display Mode", ["Auto-Timelapse", "Manual Scrubber"])
    
    st.divider()
    satellite = st.selectbox("Select Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
    parameter = st.selectbox("Select Parameter", ["Level 1", "NDVI", "NDWI", "EVI"])
    st.session_state.index = parameter

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

    config = {
        "Sentinel-2": {"id": "COPERNICUS/S2_SR_HARMONIZED", "red": "B4", "green": "B3", "blue": "B2", "nir": "B8", "max": 3000},
        "Landsat-8": {"id": "LANDSAT/LC08/C02/T1_L2", "red": "SR_B4", "green": "SR_B3", "blue": "SR_B2", "nir": "SR_B5", "max": 20000},
        "Landsat-9": {"id": "LANDSAT/LC09/C02/T1_L2", "red": "SR_B4", "green": "SR_B3", "blue": "SR_B2", "nir": "SR_B5", "max": 20000}
    }[satellite]

    collection = (ee.ImageCollection(config["id"])
                  .filterBounds(roi)
                  .filterDate(str(start_date), str(end_date))
                  .map(lambda img: mask_clouds(img, satellite))
                  .sort("system:time_start")
                  .limit(50))

    def apply_vis(image):
        if st.session_state.index == "NDVI":
            idx = image.normalizedDifference([config['nir'], config['red']])
            return idx.visualize(min=-0.1, max=0.8, palette=['brown', 'yellow', 'green'])
        elif st.session_state.index == "NDWI":
            idx = image.normalizedDifference([config['green'], config['nir']])
            return idx.visualize(min=-0.1, max=0.5, palette=['white', 'blue'])
        elif st.session_state.index == "EVI":
            evi = image.expression("2.5 * ((N-R)/(N+6*R-7.5*B+1))", 
                                   {'N':image.select(config['nir']), 'R':image.select(config['red']), 'B':image.select(config['blue'])})
            return evi.visualize(min=-0.1, max=0.8, palette=['white', 'green'])
        else:
            return image.visualize(bands=[config['red'], config['green'], config['blue']], min=0, max=config['max'])

    total_count = int(collection.size().getInfo())

    if total_count > 0:
        st.divider()
        st.subheader(f"2. {view_mode}")

        if view_mode == "Auto-Timelapse":
            video_col = collection.map(apply_vis)
            video_url = video_col.getVideoThumbURL({'dimensions': 720, 'region': roi, 'framesPerSecond': 5, 'format': 'gif'})
            st.image(video_url, use_container_width=True)
        
        else:
            # Manual Scrubber Logic
            frame_idx = st.slider("Scrub through images", 1, total_count, 1)
            # Get the specific image based on slider index
            img_list = collection.toList(total_count)
            selected_img = ee.Image(img_list.get(frame_idx - 1))
            
            # Get Date for display
            date_info = selected_img.date().format('YYYY-MM-DD HH:mm').getInfo()
            st.write(f"**Frame {frame_idx} of {total_count}** | Acquisition Date: `{date_info}`")
            
            # Generate static URL for the selected frame
            vis_img = apply_vis(selected_img)
            thumb_url = vis_img.getThumbURL({'dimensions': 1024, 'region': roi, 'format': 'png'})
            st.image(thumb_url, use_container_width=True)

    else:
        st.warning("No images found. Adjust your ROI or date range.")
