import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date

# ---------------- Page Config ----------------
st.set_page_config(layout="wide", page_title="GEE Timelapse Pro")
st.title("🌍 GEE Satellite Video Generator")

# ---------------- Session State ----------------
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

def apply_parameter(image, parameter, satellite):
    bm = get_band_map(satellite)
    if parameter == "Level1": return image
    if parameter == "NDVI": return image.normalizedDifference([bm['nir'], bm['red']]).rename(parameter)
    if parameter == "NDWI": return image.normalizedDifference([bm['green'], bm['nir']]).rename(parameter)
    if parameter == "MNDWI": return image.normalizedDifference([bm['green'], bm['swir1']]).rename(parameter)
    if parameter == "EVI":
        return image.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {'NIR': image.select(bm['nir']), 'RED': image.select(bm['red']), 'BLUE': image.select(bm['blue'])}
        ).rename(parameter)
    return image

# ---------------- Function to Get Parameter Values ----------------
def get_parameter_value(image, parameter, satellite, lat, lon):
    bm = get_band_map(satellite)
    point = ee.Geometry.Point([lon, lat])

    if parameter == "NDVI":
        ndvi = image.normalizedDifference([bm['nir'], bm['red']]).rename(parameter)
        return ndvi.reduceRegion(ee.Reducer.mean(), point, 30).get(parameter).getInfo()
    
    if parameter == "NDWI":
        ndwi = image.normalizedDifference([bm['green'], bm['nir']]).rename(parameter)
        return ndwi.reduceRegion(ee.Reducer.mean(), point, 30).get(parameter).getInfo()
    
    if parameter == "MNDWI":
        mndwi = image.normalizedDifference([bm['green'], bm['swir1']]).rename(parameter)
        return mndwi.reduceRegion(ee.Reducer.mean(), point, 30).get(parameter).getInfo()
    
    if parameter == "EVI":
        evi = image.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {'NIR': image.select(bm['nir']), 'RED': image.select(bm['red']), 'BLUE': image.select(bm['blue'])}
        ).rename(parameter)
        return evi.reduceRegion(ee.Reducer.mean(), point, 30).get(parameter).getInfo()

    return None

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("📅 Configuration")
    start_date = st.date_input("Start Date", date(2024, 1, 1))
    end_date = st.date_input("End Date", date(2024, 12, 31))
    satellite = st.selectbox("Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
    parameter = st.selectbox("Parameter", ["Level1", "NDVI", "NDWI", "MNDWI", "EVI"])
    
    palette_choice = st.selectbox("Color Theme", ["Vegetation (Green)", "Water (Blue)", "Thermal (Red)", "No Color (Grayscale)"])
    palettes = {
        "Vegetation (Green)": ['#ffffff', '#ce7e45', '#fcd163', '#66a000', '#056201', '#011301'],
        "Water (Blue)": ['#ffffd9', '#7fcdbb', '#41b6c4', '#1d91c0', '#0c2c84'],
        "Thermal (Red)": ['#ffffff', '#fc9272', '#ef3b2c', '#a50f15', '#67000d'],
        "No Color (Grayscale)": None 
    }
    selected_palette = palettes[palette_choice]

# ---------------- Map Selection ----------------
st.subheader("1. Click on the Map to Select Area")
center = [22.0, 69.5]  # Default center point (you can modify this)
m = folium.Map(location=center, zoom_start=8)

# Add click event listener to the map
def on_map_click(event):
    lat = event.latlng['lat']
    lon = event.latlng['lng']
    
    # Capture the clicked point and display parameter value
    st.session_state.clicked_lat = lat
    st.session_state.clicked_lon = lon
    
    st.write(f"**Clicked Location**: Latitude = {lat}, Longitude = {lon}")
    
    # Get the selected image frame
    col_id = {"Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED", "Landsat-8": "LANDSAT/LC08/C02/T1_L2", "Landsat-9": "LANDSAT/LC09/C02/T1_L2"}[satellite]
    
    full_collection = (ee.ImageCollection(col_id)
                      .filterBounds(ee.Geometry.Point([lon, lat]))
                      .filterDate(str(start_date), str(end_date))
                      .map(lambda img: mask_clouds(img, satellite)))
    
    # Get the first image in the collection
    img = full_collection.first()
    
    if img:
        # Calculate parameter value at the clicked location
        parameter_value = get_parameter_value(img, parameter, satellite, lat, lon)
        st.write(f"**{parameter} Value**: {parameter_value}")
    else:
        st.warning("No image data available for this location at the specified date range.")

m.on('click', on_map_click)

# Show the map in the Streamlit app
st_folium(m, height=350, width="100%")

