import streamlit as st
import ee
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date, datetime, timezone

# ---------------- Page Config ----------------
st.set_page_config(layout="wide", page_title="GEE Satellite Data Viewer")
st.title("🌍 GEE Satellite Data Viewer")

# ---------------- Session State ----------------
# Initialize coordinate states with default values (Central India)
for k, v in {"ul_lat": 23.5, "ul_lon": 77.0, "lr_lat": 21.5, "lr_lon": 79.0, "frame_idx": 1}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------- EE Init ----------------
def initialize_ee():
    try:
        ee.data.getSummary()
    except Exception:
        try:
            if "GCP_SERVICE_ACCOUNT_JSON" in st.secrets:
                info = dict(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=["https://www.googleapis.com/auth/earthengine"]
                )
                ee.Initialize(creds)
                st.sidebar.success("Earth Engine Initialized.")
            else:
                st.error("GCP_SERVICE_ACCOUNT_JSON not found in secrets.")
                st.stop()
        except Exception as e:
            st.error(f"Authentication Error: {e}")
            st.stop()

initialize_ee()

# ---------------- Processing Functions ----------------
def mask_clouds(image, satellite):
    if satellite == "Sentinel-2":
        qa = image.select('QA60')
        mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
    else: # Landsat
        qa = image.select('QA_PIXEL')
        mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
    return image.updateMask(mask)

def apply_vis(image, index, cfg):
    if index == "NDVI":
        return image.normalizedDifference([cfg['nir'], cfg['red']]).visualize(min=-0.1, max=0.8, palette=['brown', 'yellow', 'green'])
    elif index == "NDWI":
        return image.normalizedDifference([cfg['green'], cfg['nir']]).visualize(min=-0.1, max=0.5, palette=['white', 'blue'])
    elif index == "Level 1":
        return image.visualize(bands=[cfg['red'], cfg['green'], cfg['blue']], min=0, max=cfg['max'])
    return image.visualize(bands=[cfg['red'], cfg['green'], cfg['blue']], min=0, max=cfg['max'])

# ---------------- Sidebar (Editable Coordinates) ----------------
with st.sidebar:
    st.header("⚙️ Settings")
    satellite = st.selectbox("Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
    parameter = st.selectbox("Parameter", ["Level 1", "NDVI", "NDWI", "EVI", "NDSI"])
    
    st.subheader("📍 Editable Coordinates")
    # Using number inputs that sync with session state
    ul_lat = st.number_input("Upper Lat", value=st.session_state.ul_lat, format="%.6f", step=0.01)
    ul_lon = st.number_input("Upper Lon", value=st.session_state.ul_lon, format="%.6f", step=0.01)
    lr_lat = st.number_input("Lower Lat", value=st.session_state.lr_lat, format="%.6f", step=0.01)
    lr_lon = st.number_input("Lower Lon", value=st.session_state.lr_lon, format="%.6f", step=0.01)
    
    # Update session state with manual entries
    st.session_state.ul_lat, st.session_state.ul_lon = ul_lat, ul_lon
    st.session_state.lr_lat, st.session_state.lr_lon = lr_lat, lr_lon

    start_date = st.date_input("Start", date(2023, 1, 1))
    end_date = st.date_input("End", date(2024, 1, 1))

# ---------------- Map ----------------
st.subheader("1. Select or Verify Area")
# Center the map on the current coordinates
map_center = [(st.session_state.ul_lat + st.session_state.lr_lat)/2, (st.session_state.ul_lon + st.session_state.lr_lon)/2]
m = folium.Map(location=map_center, zoom_start=8)
Draw(draw_options={"polyline": False, "polygon": False, "circle": False, "marker": False, "rectangle": True}).add_to(m)

# Trigger map display
map_data = st_folium(m, height=350, width="100%", key="roi_map")

# Update state if user draws a NEW rectangle on map
if map_data and map_data.get("all_drawings"):
    coords = map_data["all_drawings"][-1]["geometry"]["coordinates"][0]
    lons, lats = zip(*coords)
    st.session_state.ul_lat, st.session_state.lr_lat = max(lats), min(lats)
    st.session_state.ul_lon, st.session_state.lr_lon = min(lons), max(lons)
    # Rerun to update the number input boxes in sidebar immediately
    st.rerun()

# ---------------- Display Logic ----------------
# Use the current state (either from manual input or map draw)
roi = ee.Geometry.Rectangle([st.session_state.ul_lon, st.session_state.lr_lat, 
                             st.session_state.lr_lon, st.session_state.ul_lat])

# Config Mapping
if satellite == "Sentinel-2":
    cfg = {"id": "COPERNICUS/S2_SR_HARMONIZED", "red": "B4", "green": "B3", "blue": "B2", "nir": "B8", "max": 3000}
else:
    cfg = {"id": f"LANDSAT/LC0{satellite[-1]}/C02/T1_L2", "red": "SR_B4", "green": "SR_B3", "blue": "SR_B2", "nir": "SR_B5", "max": 20000}

collection = (ee.ImageCollection(cfg["id"])
              .filterBounds(roi)
              .filterDate(str(start_date), str(end_date))
              .map(lambda img: mask_clouds(img, satellite))
              .sort("system:time_start"))

total_count = int(collection.size().getInfo())

if total_count > 0:
    st.divider()
    st.subheader("2. Manual Frame Scrubber")
    
    frame_idx = st.slider("Browse frames", 1, total_count, st.session_state.frame_idx)
    st.session_state.frame_idx = frame_idx

    img_list = collection.toList(total_count)
    selected_img = ee.Image(img_list.get(frame_idx - 1))
    
    # Metadata / Date
    try:
        timestamp = selected_img.get('system:time_start').getInfo()
        dt_object = datetime.fromtimestamp(float(timestamp) / 1000.0, tz=timezone.utc)
        acq_date = dt_object.strftime('%B %d, %Y | %H:%M UTC')
    except:
        acq_date = "Date Unknown"

    st.info(f"📅 **Acquisition Date:** {acq_date}")
    
    # Render Image
    vis_img = apply_vis(selected_img, parameter, cfg)
    thumb_url = vis_img.getThumbURL({'dimensions': 1024, 'region': roi, 'format': 'png'})
    st.image(thumb_url, use_container_width=True, caption=f"Frame {frame_idx} of {total_count}")
else:
    st.warning("No imagery found. Try adjusting coordinates or date range.")
