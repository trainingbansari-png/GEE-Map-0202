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
for k in ["ul_lat", "ul_lon", "lr_lat", "lr_lon", "frame_idx"]:
    if k not in st.session_state:
        st.session_state[k] = None

if st.session_state.frame_idx is None:
    st.session_state.frame_idx = 1

# ---------------- EE Init ----------------
def initialize_ee():
    try:
        if not ee.data._credentials:
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
    """Maps common names to satellite-specific band IDs to prevent errors."""
    if "Sentinel" in satellite:
        return {'red': 'B4', 'green': 'B3', 'blue': 'B2', 'nir': 'B8', 'swir1': 'B11'}
    else: # Landsat 8 & 9
        return {'red': 'B4', 'green': 'B3', 'blue': 'B2', 'nir': 'B5', 'swir1': 'B6'}

def mask_clouds(image, satellite):
    if "Sentinel" in satellite:
        qa = image.select('QA60')
        mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
    else: # Landsat
        qa = image.select('QA_PIXEL')
        mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
    return image.updateMask(mask)

def apply_parameter(image, parameter, satellite):
    bm = get_band_map(satellite)
    if parameter == "Level1":
        return image
    
    if parameter == "NDVI":
        idx = image.normalizedDifference([bm['nir'], bm['red']])
    elif parameter == "NDWI":
        idx = image.normalizedDifference([bm['green'], bm['nir']])
    elif parameter == "MNDWI":
        idx = image.normalizedDifference([bm['green'], bm['swir1']])
    elif parameter == "EVI":
        idx = image.expression(
            '2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {'NIR': image.select(bm['nir']), 'RED': image.select(bm['red']), 'BLUE': image.select(bm['blue'])}
        )
    elif parameter == "SAVI":
        idx = image.expression(
            '((NIR - RED) * 1.5) / (NIR + RED + 0.5)',
            {'NIR': image.select(bm['nir']), 'RED': image.select(bm['red'])}
        )
    return idx.rename(parameter)

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("📅 Date & Satellite")
    start_date = st.date_input("Start Date", date(2023, 1, 1))
    end_date = st.date_input("End Date", date(2023, 12, 31))
    satellite = st.selectbox("Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
    
    st.header("📊 Analysis")
    parameter = st.selectbox("Parameter", ["Level1", "NDVI", "NDWI", "MNDWI", "EVI", "SAVI"])
    
    st.header("🎨 Visualization")
    palette_choice = st.selectbox(
        "Color Palette (for Indices)",
        ["Vegetation (Green)", "Water (Blue)", "Thermal (Red)", "Terrain (Brown)"]
    )

    palettes = {
        "Vegetation (Green)": ['#ffffff', '#ce7e45', '#df923d', '#f1b555', '#fcd163', '#99b718', '#74a901', '#66a000', '#529400', '#3e8601', '#207401', '#056201', '#004c00', '#023b01', '#012e01'],
        "Water (Blue)": ['#ffffd9', '#edf8b1', '#c7e9b4', '#7fcdbb', '#41b6c4', '#1d91c0', '#225ea8', '#0c2c84'],
        "Thermal (Red)": ['#ffffff', '#fee0d2', '#fc9272', '#fb6a4a', '#ef3b2c', '#cb181d', '#a50f15', '#67000d'],
        "Terrain (Brown)": ['#332808', '#644614', '#946920', '#a08144', '#30eb5b', '#219c44', '#134e1c']
    }
    selected_palette = palettes[palette_choice]

# ---------------- Map Selection ----------------
st.subheader("1. Define Area of Interest")
m = folium.Map(location=[22.0, 69.0], zoom_start=6)
Draw(draw_options={"polyline":False,"polygon":False,"circle":False,"marker":False,"rectangle":True}).add_to(m)
map_data = st_folium(m, height=350, width="100%", key="roi_map")

if map_data and map_data["all_drawings"]:
    coords = map_data["all_drawings"][-1]["geometry"]["coordinates"][0]
    lons, lats = zip(*coords)
    st.session_state.ul_lat, st.session_state.ul_lon = min(lats), min(lons)
    st.session_state.lr_lat, st.session_state.lr_lon = max(lats), max(lons)

# ---------------- Processing ----------------
if st.session_state.ul_lat:
    roi = ee.Geometry.Rectangle([st.session_state.ul_lon, st.session_state.ul_lat, 
                                 st.session_state.lr_lon, st.session_state.lr_lat])
    
    col_id = {"Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED", 
              "Landsat-8": "LANDSAT/LC08/C02/T1_L2", 
              "Landsat-9": "LANDSAT/LC09/C02/T1_L2"}[satellite]

    collection = (ee.ImageCollection(col_id)
                  .filterBounds(roi)
                  .filterDate(str(start_date), str(end_date))
                  .map(lambda img: mask_clouds(img, satellite))
                  .sort("system:time_start")
                  .limit(30))

    count = collection.size().getInfo()

    if count > 0:
        st.divider()
        c1, c2 = st.columns([1, 1])
        
        # Setup Visualization Logic
        if parameter == "Level1":
            bm = get_band_map(satellite)
            # Landsat Collection 2 Scale requires different max than Sentinel
            max_val = 3000 if "Sentinel" in satellite else 15000 
            vis = {"bands": [bm['red'], bm['green'], bm['blue']], "min": 0, "max": max_val}
        else:
            vis = {"min": -1, "max": 1, "palette": selected_palette}

        with c1:
            st.subheader("2. Review Frames")
            idx = st.slider("Timeline", 1, count, st.session_state.frame_idx)
            st.session_state.frame_idx = idx
            
            img = ee.Image(collection.toList(count).get(idx-1))
            processed_img = apply_parameter(img, parameter, satellite)
            
            try:
                map_id = processed_img.clip(roi).getMapId(vis)
                f_map = folium.Map(location=[(st.session_state.ul_lat + st.session_state.lr_lat)/2, 
                                             (st.session_state.ul_lon + st.session_state.lr_lon)/2], zoom_start=12)
                folium.TileLayer(tiles=map_id["tile_fetcher"].url_format, attr="GEE", overlay=True).add_to(f_map)
                st_folium(f_map, height=400, width="100%", key=f"f_{idx}")
                
                date_str = ee.Date(img.get("system:time_start")).format("YYYY-MM-DD").getInfo()
                st.caption(f"Frame {idx} | Date: {date_str} | Satellite: {satellite}")
            except Exception as e:
                st.error(f"Visualization error: {e}")

        with c2:
            st.subheader("3. Export")
            fps = st.slider("Speed (FPS)", 1, 20, 5)
            if st.button("🚀 Generate Timelapse"):
                with st.spinner("Stitching frames together..."):
                    try:
                        video_col = collection.map(lambda i: apply_parameter(i, parameter, satellite).visualize(**vis).clip(roi))
                        video_url = video_col.getVideoThumbURL({
                            'dimensions': 600, 
                            'region': roi, 
                            'framesPerSecond': fps, 
                            'crs': 'EPSG:3857'
                        })
                        st.image(video_url, caption=f"{parameter} Timelapse Preview")
                        st.markdown(f"### [📥 Download GIF]({video_url})")
                    except Exception as e:
                        st.error(f"Export failed: {e}")
    else:
        st.warning("No images found for this area/date range. Try a larger range or different satellite.")
else:
    st.info("Please draw a box on the map above to start.")
