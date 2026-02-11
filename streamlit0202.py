import streamlit as st
import ee
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date

# ---------------- Session State ----------------
if "ul_lat" not in st.session_state: st.session_state.ul_lat = 22.5
if "ul_lon" not in st.session_state: st.session_state.ul_lon = 69.5
if "lr_lat" not in st.session_state: st.session_state.lr_lat = 21.5
if "lr_lon" not in st.session_state: st.session_state.lr_lon = 70.5
if "frame_idx" not in st.session_state: st.session_state.frame_idx = 1
if "probe_mode" not in st.session_state: st.session_state.probe_mode = False  # Probe mode state

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

    probe_button = st.button("Activate Probe Mode", key="probe_button")
    if probe_button:
        st.session_state.probe_mode = not st.session_state.probe_mode
        if st.session_state.probe_mode:
            st.success("Probe Mode Activated: Click on the map to get the value of the selected parameter.")

# ---------------- Main Logic ----------------
st.subheader("1. Area Selection")
center_lat = (st.session_state.ul_lat + st.session_state.lr_lat) / 2
center_lon = (st.session_state.ul_lon + st.session_state.lr_lon) / 2
m = folium.Map(location=[center_lat, center_lon], zoom_start=8)

# Adding Draw feature to the map
Draw(draw_options={"rectangle": True, "polyline": False, "polygon": False, "circle": False, "marker": False}).add_to(m)

# Handle map data from the user's click
map_data = st_folium(m, height=350, width="100%", key="roi_map")

if st.session_state.probe_mode and map_data and map_data.get("last_active_drawing"):
    # Get the coordinates of the last drawing
    new_coords = map_data["last_active_drawing"]["geometry"]["coordinates"][0]
    lons, lats = zip(*new_coords)
    st.session_state.ul_lat, st.session_state.ul_lon = max(lats), min(lons)
    st.session_state.lr_lat, st.session_state.lr_lon = min(lats), max(lons)

    # --- Probing the clicked area ---
    click_lat, click_lon = map_data["last_active_drawing"]["geometry"]["coordinates"][0][0]
    
    # Create a point at the clicked location
    point = ee.Geometry.Point(click_lon, click_lat)

    # Get the image collection for the current ROI
    roi = ee.Geometry.Rectangle([st.session_state.ul_lon, st.session_state.lr_lat, st.session_state.lr_lon, st.session_state.ul_lat])
    col_id = {"Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED", "Landsat-8": "LANDSAT/LC08/C02/T1_L2", "Landsat-9": "LANDSAT/LC09/C02/T1_L2"}[satellite]
    full_collection = ee.ImageCollection(col_id).filterBounds(roi).filterDate(str(start_date), str(end_date)).map(lambda img: mask_clouds(img, satellite))

    img = ee.Image(full_collection.toList(30).get(st.session_state.frame_idx - 1))
    processed_img = apply_parameter(img, parameter, satellite)
    
    # Get the value of the parameter at the clicked location
    value = processed_img.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=point,
        scale=30,
        maxPixels=1e9
    ).getInfo()

    if value:
        st.subheader(f"📍 Probed Area: ({click_lat:.4f}, {click_lon:.4f})")
        st.metric(label=f"Mean {parameter}", value=f"{value.get(parameter, 'N/A'):.4f}")
    else:
        st.warning("No value found for the selected location.")
