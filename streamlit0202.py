import streamlit as st
import ee
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date, datetime

# ---------------- Page Config ----------------
st.set_page_config(layout="wide", page_title="GEE Timelapse Pro")
st.title("🌍 GEE Satellite Video Generator")

# ---------------- Session State ----------------
if "ul_lat" not in st.session_state: st.session_state.ul_lat = 22.5
if "ul_lon" not in st.session_state: st.session_state.ul_lon = 69.5
if "lr_lat" not in st.session_state: st.session_state.lr_lat = 21.5
if "lr_lon" not in st.session_state: st.session_state.lr_lon = 70.5
if "frame_idx" not in st.session_state: st.session_state.frame_idx = 1

# ---------------- EE Init ----------------
def initialize_ee():
    try:
        ee.GetLibraryVersion()
    except Exception:
        try:
            if "GCP_SERVICE_ACCOUNT_JSON" in st.secrets:
                service_account_info = dict(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
                credentials = service_account.Credentials.from_service_account_info(
                    service_account_info,
                    scopes=["https://www.googleapis.com/auth/earthengine.readonly"],
                )
                ee.Initialize(credentials)
                st.sidebar.success("Earth Engine Initialized")
        except Exception as e:
            st.sidebar.error(f"EE Init Error: {e}")

initialize_ee()

# ---------------- Helper Functions ----------------
def get_band_map(satellite):
    if "Sentinel" in satellite:
        return {'red': 'B4', 'green': 'B3', 'blue': 'B2', 'nir': 'B8', 'swir1': 'B11'}
    else: 
        return {'red': 'B4', 'green': 'B3', 'blue': 'B2', 'nir': 'B5', 'swir1': 'B6'}

def mask_clouds(image, satellite):
    if "Sentinel" in satellite:
        qa = image.select('QA60')
        mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
    else: 
        qa = image.select('QA_PIXEL')
        mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
    return image.updateMask(mask)

def apply_parameter(image, parameter, satellite, custom_value=None):
    bm = get_band_map(satellite)
    if parameter == "Level1": return image
    if parameter == "NDVI":
        ndvi = image.normalizedDifference([bm['nir'], bm['red']]).rename(parameter)
        if custom_value:
            ndvi = ndvi.updateMask(ndvi.gt(custom_value))  # Apply threshold based on custom_value
        return ndvi
    if parameter == "NDWI":
        ndwi = image.normalizedDifference([bm['green'], bm['nir']]).rename(parameter)
        if custom_value:
            ndwi = ndwi.updateMask(ndwi.gt(custom_value))  # Apply threshold based on custom_value
        return ndwi
    if parameter == "MNDWI":
        mndwi = image.normalizedDifference([bm['green'], bm['swir1']]).rename(parameter)
        if custom_value:
            mndwi = mndwi.updateMask(mndwi.gt(custom_value))  # Apply threshold based on custom_value
        return mndwi
    if parameter == "EVI":
        evi = image.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {'NIR': image.select(bm['nir']), 'RED': image.select(bm['red']), 'BLUE': image.select(bm['blue'])}
        ).rename(parameter)
        if custom_value:
            evi = evi.updateMask(evi.gt(custom_value))  # Apply threshold based on custom_value
        return evi
    return image

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("📍 Coordinate Editor")
    u_lat = st.number_input("Upper Lat", value=float(st.session_state.ul_lat), format="%.4f")
    u_lon = st.number_input("Left Lon", value=float(st.session_state.ul_lon), format="%.4f")
    l_lat = st.number_input("Lower Lat", value=float(st.session_state.lr_lat), format="%.4f")
    l_lon = st.number_input("Right Lon", value=float(st.session_state.lr_lon), format="%.4f")
    
    st.session_state.ul_lat, st.session_state.ul_lon = u_lat, u_lon
    st.session_state.lr_lat, st.session_state.lr_lon = l_lat, l_lon

    st.header("📅 Configuration")
    start_date = st.date_input("Start Date", date(2024, 1, 1))
    end_date = st.date_input("End Date", date(2024, 12, 31))
    satellite = st.selectbox("Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
    parameter = st.selectbox("Parameter", ["Level1", "NDVI", "NDWI", "MNDWI", "EVI"])

    # Allow user to input a custom value for parameter
    custom_value = st.slider("Set Parameter Threshold", min_value=0.0, max_value=1.0, value=0.2, step=0.01)
    
    palette_choice = st.selectbox("Color Theme", ["Vegetation (Green)", "Water (Blue)", "Thermal (Red)", "No Color (Grayscale)"])
    palettes = {
        "Vegetation (Green)": ['#ffffff', '#ce7e45', '#fcd163', '#66a000', '#056201', '#011301'],
        "Water (Blue)": ['#ffffd9', '#7fcdbb', '#41b6c4', '#1d91c0', '#0c2c84'],
        "Thermal (Red)": ['#ffffff', '#fc9272', '#ef3b2c', '#a50f15', '#67000d'],
        "No Color (Grayscale)": None 
    }
    selected_palette = palettes[palette_choice]

# ---------------- Map Selection ----------------
st.subheader("1. Area Selection")
center = [(st.session_state.ul_lat + st.session_state.lr_lat)/2, (st.session_state.ul_lon + st.session_state.lr_lon)/2]
m = folium.Map(location=center, zoom_start=8)
Draw(draw_options={"polyline":False,"polygon":False,"circle":False,"marker":False,"rectangle":True}).add_to(m)
map_data = st_folium(m, height=350, width="100%", key="roi_map")

if map_data and map_data["all_drawings"]:
    new_coords = map_data["all_drawings"][-1]["geometry"]["coordinates"][0]
    lons, lats = zip(*new_coords)
    st.session_state.ul_lat, st.session_state.ul_lon = max(lats), min(lons)
    st.session_state.lr_lat, st.session_state.lr_lon = min(lats), max(lons)
    st.rerun()

# ---------------- Main Processing ----------------
roi = ee.Geometry.Rectangle([st.session_state.ul_lon, st.session_state.lr_lat, 
                             st.session_state.lr_lon, st.session_state.ul_lat])

col_id = {"Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED", "Landsat-8": "LANDSAT/LC08/C02/T1_L2", "Landsat-9": "LANDSAT/LC09/C02/T1_L2"}[satellite]

# Build the initial collection
full_collection = (ee.ImageCollection(col_id)
                  .filterBounds(roi)
                  .filterDate(str(start_date), str(end_date))
                  .map(lambda img: mask_clouds(img, satellite)))

# Get total count available in Earth Engine
total_available = full_collection.size().getInfo()

# Limit for visualization/timelapse performance
preview_limit = 30
display_collection = full_collection.sort("system:time_start").limit(preview_limit)
display_count = display_collection.size().getInfo()

if total_available > 0:
    st.divider()
    # SHOW TOTAL IMAGES FOUND
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Images in Archive", total_available)
    m2.metric("Images in Preview", display_count)
    m3.metric("Satellite Sensor", satellite)

    c1, c2 = st.columns([1, 1])
    
    vis = {"min": -1, "max": 1}
    if parameter == "Level1":
        bm = get_band_map(satellite)
        vis = {"bands": [bm['red'], bm['green'], bm['blue']], "min": 0, "max": 3000 if "Sentinel" in satellite else 15000}
    elif selected_palette:
        vis["palette"] = selected_palette

    with c1:
        st.subheader("2. Visual Review")
        idx = st.slider("Select Frame", 1, display_count, st.session_state.frame_idx)
        img = ee.Image(display_collection.toList(display_count).get(idx-1))
        
        timestamp = ee.Date(img.get("system:time_start")).format("YYYY-MM-DD HH:mm:ss").getInfo()
        st.write(f"**Frame Timestamp:** {timestamp}")
        
        map_id = apply_parameter(img, parameter, satellite, custom_value).clip(roi).getMapId(vis)
        f_map = folium.Map(location=[(st.session_state.ul_lat + st.session_state.lr_lat)/2, (st.session_state.ul_lon + st.session_state.lr_lon)/2], zoom_start=12)
        folium.TileLayer(tiles=map_id["tile_fetcher"].url_format, attr="GEE", overlay=True).add_to(f_map)
        st_folium(f_map, height=400, width="100%", key=f"rev_{idx}_{parameter}_{palette_choice}")

    with c2:
        st.subheader("3. Export")
        fps = st.slider("Frames Per Second", 1, 15, 5)
        if st.button("🎬 Generate Animated Timelapse"):
            with st.spinner("Generating..."):
                video_col = display_collection.map(lambda i: apply_parameter(i, parameter, satellite, custom_value).visualize(**vis).clip(roi))
                video_url = video_col.getVideoThumbURL({'dimensions': 720, 'region': roi, 'framesPerSecond': fps, 'crs': 'EPSG:3857'})
                st.image(video_url, caption=f"Timelapse: {parameter}")
                st.markdown(f"### [📥 Download Result]({video_url})")
else:
    st.warning(f"No images found for {satellite} in this area/date range. Try a larger ROI or date span.")
