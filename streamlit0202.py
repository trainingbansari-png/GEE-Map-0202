import streamlit as st
import ee
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date, datetime, timezone

# ---------------- Page Config ----------------
st.set_page_config(layout="wide", page_title="GEE Satellite Time-Lapse")
st.title("🌍 GEE Satellite Data Viewer & Animator")

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
    else: # Landsat
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
    end_date = st.date_input("End", date(2023, 6, 1))

# ---------------- Map ----------------
st.subheader("1. Define Area of Interest")
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
# Standardize the ROI to a simple list for the API
roi_coords = [st.session_state.ul_lon, st.session_state.lr_lat, 
              st.session_state.lr_lon, st.session_state.ul_lat]
roi = ee.Geometry.Rectangle(roi_coords)

if satellite == "Sentinel-2":
    cfg = {"id": "COPERNICUS/S2_SR_HARMONIZED", "red": "B4", "green": "B3", "blue": "B2", "nir": "B8", "max": 3000}
else:
    cfg = {"id": f"LANDSAT/LC0{satellite[-1]}/C02/T1_L2", "red": "SR_B4", "green": "SR_B3", "blue": "SR_B2", "nir": "SR_B5", "max": 20000}

collection = (ee.ImageCollection(cfg["id"])
              .filterBounds(roi)
              .filterDate(str(start_date), str(end_date))
              .map(lambda img: mask_clouds(img, satellite))
              .sort("system:time_start"))

# Limit the collection to keep metadata calls fast
collection = collection.limit(50)
total_count = int(collection.size().getInfo())

if total_count > 0:
    # ---------------- Manual Scrubber ----------------
    st.divider()
    st.subheader(f"2. Preview Frames ({total_count} found)")
    
    frame_idx = st.slider("Select Frame", 1, total_count, st.session_state.frame_idx)
    st.session_state.frame_idx = frame_idx

    img_list = collection.toList(total_count)
    selected_img = ee.Image(img_list.get(frame_idx - 1))
    
    try:
        timestamp = selected_img.get('system:time_start').getInfo()
        dt_object = datetime.fromtimestamp(float(timestamp) / 1000.0, tz=timezone.utc)
        acq_datetime = dt_object.strftime('%B %d, %Y | %H:%M:%S UTC')
        st.info(f"📅 **Selected:** {acq_datetime}")
    except:
        acq_datetime = "Date Unknown"

    # --- Robust Thumbnail Rendering ---
    vis_img = apply_vis(selected_img, parameter, cfg)
    try:
        # Reduced dimension to 768 for better stability on large ROIs
        thumb_url = vis_img.getThumbURL({
            'dimensions': 768, 
            'region': roi, 
            'format': 'png',
            'crs': 'EPSG:3857'
        })
        st.image(thumb_url, use_container_width=True, caption=f"Frame {frame_idx}: {acq_datetime}")
    except Exception as e:
        st.error(f"Thumbnail Error: Area too large or resolution too high. Try drawing a smaller rectangle.")

    # ---------------- Video Generation ----------------
    st.divider()
    st.subheader("3. 🎬 Generate Animated Time-Lapse")
    
    c1, c2 = st.columns([1, 2])
    with c1:
        fps = st.slider("Frames Per Second", 1, 15, 5)
        video_btn = st.button("Create Animation")
    
    if video_btn:
        with st.spinner("Compiling video..."):
            try:
                video_col = collection.map(lambda img: apply_vis(img, parameter, cfg))
                video_url = video_col.getVideoThumbURL({
                    'dimensions': 512, # Lower res for video to ensure success
                    'region': roi,
                    'framesPerSecond': fps,
                    'format': 'gif',
                    'crs': 'EPSG:3857'
                })
                with c2:
                    st.image(video_url, caption="Time-Lapse Result")
                    st.markdown(f"📥 [Download GIF]({video_url})")
            except Exception as e:
                st.error(f"Video limit exceeded. Try a smaller ROI or shorter date range.")

else:
    st.warning("No images found. Adjust your area or dates.")
