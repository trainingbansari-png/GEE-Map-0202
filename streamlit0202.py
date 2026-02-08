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
                st.error("Secrets not found. Check Streamlit Cloud configuration.")
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
    st.
