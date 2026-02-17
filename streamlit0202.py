import streamlit as st
import ee
import folium
import pandas as pd
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date

# ---------------- PAGE CONFIG ----------------
st.set_page_config(layout="wide")

# ---------------- EE INIT (STREAMLIT CLOUD SAFE) ----------------
def initialize_ee():
    try:
        # Check if credentials exist in Streamlit secrets
        if "GCP_SERVICE_ACCOUNT_JSON" not in st.secrets:
            st.error("❌ Missing GCP service account in secrets.toml")
            st.stop()

        service_account_info = dict(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])

        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/earthengine"]
        )

        ee.Initialize(credentials)

    except Exception as e:
        st.error(f"❌ Earth Engine Initialization Failed: {e}")
        st.stop()

initialize_ee()

# ---------------- SESSION STATE ----------------
if "ul_lat" not in st.session_state:
    st.session_state.ul_lat = 22.5
if "ul_lon" not in st.session_state:
    st.session_state.ul_lon = 69.5
if "lr_lat" not in st.session_state:
    st.session_state.lr_lat = 21.5
if "lr_lon" not in st.session_state:
    st.session_state.lr_lon = 70.5
if "frame_idx" not in st.session_state:
    st.session_state.frame_idx = 1

# ---------------- HELPER FUNCTIONS ----------------
def get_band_map(satellite):
    if "Sentinel" in satellite:
        return {"red": "B4", "green": "B3", "blue": "B2", "nir": "B8", "swir1": "B11"}
    else:
        return {"red": "B4", "green": "B3", "blue": "B2", "nir": "B5", "swir1": "B6"}


def mask_clouds(image, satellite):
    if "Sentinel" in satellite:
        qa = image.select("QA60")
        mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
    else:
        qa = image.select("QA_PIXEL")
        mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
    return image.updateMask(mask)


def apply_parameter(image, parameter, satellite):
    bm = get_band_map(satellite)

    if parameter == "Level1":
        return image

    if parameter in ["NDVI", "NDWI", "MNDWI", "NDSI"]:
        pairs = {
            "NDVI": [bm["nir"], bm["red"]],
            "NDWI": [bm["green"], bm["nir"]],
            "MNDWI": [bm["green"], bm["swir1"]],
            "NDSI": [bm["green"], bm["swir1"]],
        }
        return image.normalizedDifference(pairs[parameter]).rename(parameter)

    if parameter == "EVI":
        return image.expression(
            "2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))",
            {
                "NIR": image.select(bm["nir"]),
                "RED": image.select(bm["red"]),
                "BLUE": image.select(bm["blue"]),
            },
        ).rename(parameter)

    return image


# ---------------- SIDEBAR ----------------
with st.sidebar:
    st.header("📍 ROI & Config")

    u_lat = st.number_input("Upper Lat", value=float(st.session_state.ul_lat))
    u_lon = st.number_input("Left Lon", value=float(st.session_state.ul_lon))
    l_lat = st.number_input("Lower Lat", value=float(st.session_state.lr_lat))
    l_lon = st.number_input("Right Lon", value=float(st.session_state.lr_lon))

    st.session_state.ul_lat = u_lat
    st.session_state.ul_lon = u_lon
    st.session_state.lr_lat = l_lat
    st.session_state.lr_lon = l_lon

    start_date = st.date_input("Start Date", date(2024, 1, 1))
    end_date = st.date_input("End Date", date(2024, 12, 31))
    satellite = st.selectbox("Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
    parameter = st.selectbox("Parameter", ["Level1", "NDVI", "NDWI", "MNDWI", "NDSI", "EVI"])

# ---------------- PROCESSING ----------------
roi = ee.Geometry.Rectangle([
    st.session_state.ul_lon,
    st.session_state.lr_lat,
    st.session_state.lr_lon,
    st.session_state.ul_lat,
])

col_id = {
    "Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED",
    "Landsat-8": "LANDSAT/LC08/C02/T1_L2",
    "Landsat-9": "LANDSAT/LC09/C02/T1_L2",
}[satellite]

full_collection = (
    ee.ImageCollection(col_id)
    .filterBounds(roi)
    .filterDate(str(start_date), str(end_date))
    .map(lambda img: mask_clouds(img, satellite))
)

total_available = full_collection.size().getInfo()

if total_available == 0:
    st.warning("No images found.")
    st.stop()

display_collection = full_collection.sort("system:time_start").limit(30)
display_count = display_collection.size().getInfo()

st.success("✅ Earth Engine Connected Successfully")

st.metric("Total Images Found", total_available)
st.metric("Preview Frames", display_count)
