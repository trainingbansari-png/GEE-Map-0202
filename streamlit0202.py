import streamlit as st
import ee
import folium
import pandas as pd
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date, datetime

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
    if parameter == "Level1": return image
    
    if parameter in ["NDVI", "NDWI", "MNDWI", "NDSI"]:
        pairs = {"NDVI": [bm['nir'], bm['red']], "NDWI": [bm['green'], bm['nir']],
                 "MNDWI": [bm['green'], bm['swir1']], "NDSI": [bm['green'], bm['swir1']]}
        return image.normalizedDifference(pairs[parameter]).rename(parameter)
    
    if parameter == "EVI":
        return image.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {'NIR': image.select(bm['nir']), 'RED': image.select(bm['red']), 'BLUE': image.select(bm['blue'])}).rename(parameter)
    return image

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("📍 ROI & Config")
    u_lat = st.number_input("Upper Lat", value=float(st.session_state.ul_lat), format="%.4f")
    u_lon = st.number_input("Left Lon", value=float(st.session_state.ul_lon), format="%.4f")
    l_lat = st.number_input("Lower Lat", value=float(st.session_state.lr_lat), format="%.4f")
    l_lon = st.number_input("Right Lon", value=float(st.session_state.lr_lon), format="%.4f")
    st.session_state.ul_lat, st.session_state.ul_lon = u_lat, u_lon
    st.session_state.lr_lat, st.session_state.lr_lon = l_lat, l_lon

    start_date = st.date_input("Start Date", date(2024, 1, 1))
    end_date = st.date_input("End Date", date(2024, 12, 31))
    satellite = st.selectbox("Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
    
    # PARAMETER SELECTION WITH DESCRIPTIONS
    param_options = {
        "Level1": "Natural Color (RGB)",
        "NDVI": "NDVI - Normalized Difference Vegetation Index",
        "NDWI": "NDWI - Normalized Difference Water Index",
        "MNDWI": "MNDWI - Modified Normalized Difference Water Index",
        "NDSI": "NDSI - Normalized Difference Snow Index",
        "EVI": "EVI - Enhanced Vegetation Index"
    }
    param_label = st.selectbox("Select Parameter", list(param_options.values()))
    parameter = param_label.split(" - ")[0] if " - " in param_label else "Level1"
    
    palette_choice = st.selectbox("Color Theme", ["Vegetation (Green)", "Water (Blue)", "Thermal (Red)", "No Color (Grayscale)"])
    palettes = {
        "Vegetation (Green)": ['#ffffff', '#ce7e45', '#fcd163', '#66a000', '#056201', '#011301'],
        "Water (Blue)": ['#ffffd9', '#7fcdbb', '#41b6c4', '#1d91c0', '#225ea8', '#0c2c84'],
        "Thermal (Red)": ['#ffffff', '#fc9272', '#ef3b2c', '#cb181d', '#a50f15', '#67000d'],
        "No Color (Grayscale)": None 
    }
    selected_palette = palettes[palette_choice]

    # --- FULL FORM & RANGE GUIDE TABLE ---
    st.divider()
    st.header("📖 Parameter Full Forms & Guide")
    
    if parameter == "NDVI":
        st.write("**Full Form:** Normalized Difference Vegetation Index")
        st.table({
            "Color Name": ["Dark Green", "Light Green", "Yellow/Brown", "Blue"],
            "Range": ["0.6 to 1.0", "0.2 to 0.6", "0.0 to 0.2", "-1.0 to -0.1"],
            "Meaning": ["Forest", "Crops/Grass", "Soil/Urban", "Water/Snow"]
        })
    elif parameter == "NDWI":
        st.write("**Full Form:** Normalized Difference Water Index")
        st.table({
            "Color Name": ["Dark Blue", "Light Blue", "White"],
            "Range": ["0.3 to 1.0", "0.0 to 0.3", "-1.0 to 0.0"],
            "Meaning": ["Deep Water", "Shallow Water", "Dry Land"]
        })
    elif parameter == "MNDWI":
        st.write("**Full Form:** Modified Normalized Difference Water Index")
        st.info("Uses SWIR band to better distinguish water from urban buildings.")
    elif parameter == "NDSI":
        st.write("**Full Form:** Normalized Difference Snow Index")
        st.table({
            "Color Name": ["Bright White", "Grey", "Black"],
            "Range": ["0.4 to 1.0", "0.1 to 0.4", "-1.0 to 0.1"],
            "Meaning": ["Snow Cover", "Ice/Clouds", "Land/Water"]
        })
    elif parameter == "EVI":
        st.write("**Full Form:** Enhanced Vegetation Index")
        st.info("Improves on NDVI by reducing atmospheric noise and soil background interference.")

# ---------------- Main Logic ----------------
st.subheader("1. Area Selection")
center_lat = (st.session_state.ul_lat + st.session_state.lr_lat)/2
center_lon = (st.session_state.ul_lon + st.session_state.lr_lon)/2
m = folium.Map(location=[center_lat, center_lon], zoom_start=8)

folium.Rectangle(bounds=[[st.session_state.lr_lat, st.session_state.ul_lon], [st.session_state.ul_lat, st.session_state.lr_lon]],
                 color="red", weight=2, fill=True, fill_opacity=0.1).add_to(m)

Draw(draw_options={"rectangle":True, "polyline":False, "polygon":False, "circle":False, "marker":False}).add_to(m)
map_data = st_folium(m, height=350, width="100%", key="roi_map")

if map_data and map_data["all_drawings"]:
    new_coords = map_data["all_drawings"][-1]["geometry"]["coordinates"][0]
    lons, lats = zip(*new_coords)
    st.session_state.ul_lat, st.session_state.ul_lon = max(lats), min(lons)
    st.session_state.lr_lat, st.session_state.lr_lon = min(lats), max(lons)
    st.rerun()

# Processing
roi = ee.Geometry.Rectangle([st.session_state.ul_lon, st.session_state.lr_lat, st.session_state.lr_lon, st.session_state.ul_lat])
col_id = {"Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED", "Landsat-8": "LANDSAT/LC08/C02/T1_L2", "Landsat-9": "LANDSAT/LC09/C02/T1_L2"}[satellite]
full_collection = ee.ImageCollection(col_id).filterBounds(roi).filterDate(str(start_date), str(end_date)).map(lambda img: mask_clouds(img, satellite))

total_available = full_collection.size().getInfo()
display_collection = full_collection.sort("system:time_start").limit(30)
display_count = display_collection.size().getInfo()

if total_available > 0:
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("Archive Images", total_available)
    m2.metric("Preview Frames", display_count)
    m3.metric("Sensor", satellite)

    c1, c2 = st.columns([1, 1])

    with c1:
        st.subheader("2. Review & Stats")
        idx = st.slider("Select Frame", 1, display_count, st.session_state.frame_idx)
        st.session_state.frame_idx = idx
        img = ee.Image(display_collection.toList(display_count).get(idx-1))
        processed_img = apply_parameter(img, parameter, satellite)
        
        if parameter != "Level1":
            with st.spinner("Calculating mean..."):
                mean_dict = processed_img.reduceRegion(
                    reducer=ee.Reducer.mean(),
                    geometry=roi,
                    scale=30,
                    maxPixels=1e9
                ).getInfo()
                val = mean_dict.get(parameter)
                if val is not None:
                    st.metric(label=f"Mean {parameter}", value=f"{val:.4f}")

        timestamp = ee.Date(img.get("system:time_start")).format("YYYY-MM-DD HH:mm:ss").getInfo()
        st.caption(f"📅 **Time:** {timestamp}")

        vis = {"min": -1, "max": 1}
        if parameter == "Level1":
            bm = get_band_map(satellite)
            max_val = 3000 if "Sentinel" in satellite else 15000
            vis = {"bands": [bm['red'], bm['green'], bm['blue']], "min": 0, "max": max_val}
        elif selected_palette: 
            vis["palette"] = selected_palette
        
        map_id = processed_img.clip(roi).getMapId(vis)
        f_map = folium.Map(location=[center_lat, center_lon], zoom_start=12)
        folium.TileLayer(tiles=map_id["tile_fetcher"].url_format, attr="GEE", overlay=True).add_to(f_map)
        st_folium(f_map, height=400, width="100%", key=f"rev_{idx}_{parameter}_{palette_choice}")

    with c2:
        st.subheader("3. Export")
        fps = st.slider("Speed (FPS)", 1, 15, 5)
        if st.button("🎬 Generate Animated Timelapse"):
            with st.spinner("Generating..."):
                video_col = display_collection.map(lambda i: apply_parameter(i, parameter, satellite).visualize(**vis).clip(roi))
                video_url = video_col.getVideoThumbURL({'dimensions': 720, 'region': roi, 'framesPerSecond': fps, 'crs': 'EPSG:3857'})
                st.image(video_url, caption=f"Timelapse: {parameter}")
                st.markdown(f"### [📥 Download Result]({video_url})")
else:
    st.warning("No images found. Adjust your settings.")
