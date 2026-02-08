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
            else:
                st.error("Secrets not found. Check Streamlit Cloud secrets.")
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
    st.header("📅 Configuration")
    start_date = st.date_input("Start Date", date(2024, 1, 1))
    end_date = st.date_input("End Date", date(2024, 12, 31))
    satellite = st.selectbox("Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
    
    st.header("📊 Analysis")
    parameter = st.selectbox("Parameter", ["Level1", "NDVI", "NDWI", "MNDWI", "EVI", "SAVI"])
    
    st.header("🎨 Palette")
    # Added "No Color (Grayscale)" to the list
    palette_choice = st.selectbox(
        "Color Theme",
        ["Vegetation (Green)", "Water (Blue)", "Thermal (Red)", "Terrain (Brown)", "No Color (Grayscale)"]
    )

    palettes = {
        "Vegetation (Green)": ['#ffffff', '#ce7e45', '#fcd163', '#66a000', '#056201', '#011301'],
        "Water (Blue)": ['#ffffd9', '#7fcdbb', '#41b6c4', '#1d91c0', '#0c2c84'],
        "Thermal (Red)": ['#ffffff', '#fc9272', '#ef3b2c', '#a50f15', '#67000d'],
        "Terrain (Brown)": ['#332808', '#946920', '#30eb5b', '#134e1c'],
        "No Color (Grayscale)": None # Setting to None to handle black and white
    }
    selected_palette = palettes[palette_choice]

# ---------------- Map Selection ----------------
st.subheader("1. Select Area of Interest")
m = folium.Map(location=[22.0, 69.0], zoom_start=6)
Draw(draw_options={"polyline":False,"polygon":False,"circle":False,"marker":False,"rectangle":True}).add_to(m)
map_data = st_folium(m, height=350, width="100%", key="roi_map")

if map_data and map_data["all_drawings"]:
    coords = map_data["all_drawings"][-1]["geometry"]["coordinates"][0]
    lons, lats = zip(*coords)
    st.session_state.ul_lat, st.session_state.ul_lon = min(lats), min(lons)
    st.session_state.lr_lat, st.session_state.lr_lon = max(lats), max(lons)

# ---------------- Main Processing ----------------
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

    try:
        count = collection.size().getInfo()
    except Exception as e:
        st.error(f"Error fetching collection: {e}")
        count = 0

    if count > 0:
        st.divider()
        c1, c2 = st.columns([1, 1])
        
        # Setup Vis Parameters
        if parameter == "Level1":
            bm = get_band_map(satellite)
            max_val = 3000 if "Sentinel" in satellite else 15000 
            vis = {"bands": [bm['red'], bm['green'], bm['blue']], "min": 0, "max": max_val}
        else:
            # Handle No Color Option
            vis = {"min": -1, "max": 1}
            if selected_palette:
                vis["palette"] = selected_palette

        with c1:
            st.subheader("2. Visual Review")
            idx = st.slider("Select Frame", 1, count, st.session_state.frame_idx)
            st.session_state.frame_idx = idx
            
            img = ee.Image(collection.toList(count).get(idx-1))
            processed_img = apply_parameter(img, parameter, satellite)
            
            timestamp = ee.Date(img.get("system:time_start"))
            date_time_str = timestamp.format("YYYY-MM-DD HH:mm:ss").getInfo()
            st.metric(label="Acquisition Timestamp (UTC)", value=date_time_str)
            
            try:
                map_id = processed_img.clip(roi).getMapId(vis)
                center_lat = (st.session_state.ul_lat + st.session_state.lr_lat) / 2
                center_lon = (st.session_state.ul_lon + st.session_state.lr_lon) / 2
                
                f_map = folium.Map(location=[center_lat, center_lon], zoom_start=12)
                folium.TileLayer(tiles=map_id["tile_fetcher"].url_format, attr="GEE", overlay=True).add_to(f_map)
                st_folium(f_map, height=400, width="100%", key=f"viewer_{idx}")
            except Exception as e:
                st.error(f"Map Rendering Error: {e}")

        with c2:
            st.subheader("3. Export")
            fps = st.slider("Frames Per Second", 1, 15, 5)
            
            if st.button("🎬 Generate Animated Timelapse"):
                with st.spinner("Processing video..."):
                    try:
                        # Map visualization across the collection
                        video_col = collection.map(lambda i: apply_parameter(i, parameter, satellite).visualize(**vis).clip(roi))
                        
                        video_url = video_col.getVideoThumbURL({
                            'dimensions': 720, 
                            'region': roi, 
                            'framesPerSecond': fps, 
                            'crs': 'EPSG:3857'
                        })
                        
                        st.image(video_url, caption=f"{parameter} Timelapse ({satellite})")
                        st.markdown(f"### [📥 Download Result]({video_url})")
                    except Exception as e:
                        st.error(f"Video Generation Error: {e}")
    else:
        st.warning("No images found. Try a wider date range.")
else:
    st.info("💡 Draw a rectangle on the map to select your region.")
