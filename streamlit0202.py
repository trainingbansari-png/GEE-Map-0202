import streamlit as st
import ee
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date, datetime, timezone

# ---------------- Page Config ----------------
st.set_page_config(layout="wide", page_title="GEE Precision Animator")
st.title("🌍 Resilient Satellite Data Viewer")

# ---------------- Session State ----------------
for k, v in {"ul_lat": 23.5, "ul_lon": 77.0, "lr_lat": 21.5, "lr_lon": 79.0, "frame_idx": 1}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------- EE Init ----------------
def initialize_ee():
    try:
        ee.Initialize()
    except Exception:
        try:
            if "GCP_SERVICE_ACCOUNT_JSON" in st.secrets:
                info = dict(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
                creds = service_account.Credentials.from_service_account_info(
                    info, scopes=["https://www.googleapis.com/auth/earthengine"]
                )
                ee.Initialize(creds)
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
    else:
        qa = image.select('QA_PIXEL')
        mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
    return image.updateMask(mask)

def apply_vis(image, index, cfg):
    if index == "NDVI":
        res = image.normalizedDifference([cfg['nir'], cfg['red']]).visualize(min=-0.1, max=0.8, palette=['brown', 'yellow', 'green'])
    elif index == "NDWI":
        res = image.normalizedDifference([cfg['green'], cfg['nir']]).visualize(min=-0.1, max=0.5, palette=['white', 'blue'])
    else:
        res = image.visualize(bands=[cfg['red'], cfg['green'], cfg['blue']], min=0, max=cfg['max'])
    return res.set('system:time_start', image.get('system:time_start'))

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("⚙️ Settings")
    satellite = st.selectbox("Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
    parameter = st.selectbox("Parameter", ["Level 1", "NDVI", "NDWI"])
    
    st.subheader("📍 Coordinates")
    ul_lat = st.number_input("Upper Lat", value=st.session_state.ul_lat, format="%.6f")
    ul_lon = st.number_input("Upper Lon", value=st.session_state.ul_lon, format="%.6f")
    lr_lat = st.number_input("Lower Lat", value=st.session_state.lr_lat, format="%.6f")
    lr_lon = st.number_input("Lower Lon", value=st.session_state.lr_lon, format="%.6f")
    
    st.session_state.ul_lat, st.session_state.ul_lon = ul_lat, ul_lon
    st.session_state.lr_lat, st.session_state.lr_lon = lr_lat, lr_lon

    start_date = st.date_input("Start", date(2023, 1, 1))
    end_date = st.date_input("End", date(2023, 12, 31))

# ---------------- Map ----------------
st.subheader("1. Area Selection")
map_center = [(st.session_state.ul_lat + st.session_state.lr_lat)/2, (st.session_state.ul_lon + st.session_state.lr_lon)/2]
m = folium.Map(location=map_center, zoom_start=10)
Draw(draw_options={"polyline": False, "polygon": False, "circle": False, "rectangle": True}).add_to(m)
map_data = st_folium(m, height=350, width="100%", key="roi_map")

if map_data and map_data.get("all_drawings"):
    coords = map_data["all_drawings"][-1]["geometry"]["coordinates"][0]
    lons, lats = zip(*coords)
    st.session_state.ul_lat, st.session_state.lr_lat = max(lats), min(lats)
    st.session_state.ul_lon, st.session_state.lr_lon = min(lons), max(lons)
    st.rerun()

# ---------------- GEE Processing ----------------
roi = ee.Geometry.Rectangle([st.session_state.ul_lon, st.session_state.lr_lat, 
                             st.session_state.lr_lon, st.session_state.ul_lat])

if satellite == "Sentinel-2":
    cfg = {"id": "COPERNICUS/S2_SR_HARMONIZED", "red": "B4", "green": "B3", "blue": "B2", "nir": "B8", "max": 3500}
else:
    cfg = {"id": f"LANDSAT/LC0{satellite[-1]}/C02/T1_L2", "red": "SR_B4", "green": "SR_B3", "blue": "SR_B2", "nir": "SR_B5", "max": 20000}

# Fetch collection and handle possible empty results
collection = (ee.ImageCollection(cfg["id"])
              .filterBounds(roi)
              .filterDate(str(start_date), str(end_date))
              .map(lambda img: mask_clouds(img, satellite))
              .sort("system:time_start"))

# Limit frames to prevent server timeout
count_info = collection.size().getInfo()

if count_info > 0:
    st.divider()
    st.subheader(f"2. Previewing {min(count_info, 50)} Frames")
    
    # We only preview the first 50 to keep things fast
    limited_col = collection.limit(50)
    display_count = min(count_info, 50)
    
    frame_idx = st.slider("Select Frame", 1, display_count, st.session_state.frame_idx)
    st.session_state.frame_idx = min(frame_idx, display_count)

    # Use a Try-Except block for metadata to prevent crashes
    try:
        img_list = limited_col.toList(display_count)
        selected_img = ee.Image(img_list.get(st.session_state.frame_idx - 1))
        timestamp = selected_img.get('system:time_start').getInfo()
        dt_object = datetime.fromtimestamp(float(timestamp) / 1000.0, tz=timezone.utc)
        acq_datetime = dt_object.strftime('%B %d, %Y | %H:%M:%S UTC')
        st.success(f"📅 **Precise Overpass:** {acq_datetime}")
        
        # Rendering
        vis_img = apply_vis(selected_img, parameter, cfg)
        thumb_url = vis_img.getThumbURL({'dimensions': 800, 'region': roi, 'format': 'png', 'crs': 'EPSG:3857'})
        st.image(thumb_url, use_container_width=True)
        
    except Exception as e:
        st.error(f"Error loading frame: {e}. Try selecting a smaller area or different date.")

    # ---------------- Video Generation ----------------
    st.divider()
    st.subheader("3. 🎬 Create Animation")
    
    c1, c2 = st.columns([1, 2])
    with c1:
        fps = st.slider("Speed (FPS)", 1, 15, 5)
        if st.button("Generate Video"):
            with st.spinner("Processing video..."):
                try:
                    video_col = limited_col.map(lambda img: apply_vis(img, parameter, cfg))
                    video_url = video_col.getVideoThumbURL({
                        'dimensions': 480,
                        'region': roi,
                        'framesPerSecond': fps,
                        'format': 'gif',
                        'crs': 'EPSG:3857'
                    })
                    st.image(video_url, caption="Generated Time-Lapse")
                except Exception as ve:
                    st.error(f"Video Generation Error: {ve}")

else:
    st.warning("No imagery found. Try a different location or wider date range.")
