import streamlit as st
import ee
import folium
import pandas as pd
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date

# ---------------- Page Config ----------------
st.set_page_config(layout="wide")
st.title("🌍 Streamlit + Google Earth Engine")

# ---------------- EE Init ----------------
def initialize_ee():
    service_account_info = dict(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/earthengine.readonly"],
    )
    ee.Initialize(credentials)

initialize_ee()

# ---------------- Map ----------------
m = folium.Map(location=[22.0, 69.0], zoom_start=7)

Draw(
    draw_options={
        "polyline": False,
        "polygon": False,
        "circle": False,
        "marker": False,
        "circlemarker": False,
        "rectangle": True,
    }
).add_to(m)

# ---------------- Render Map ----------------
map_data = st_folium(m, height=550, width="100%")

# ---------------- CLICK COORDINATES ----------------
st.subheader("📍 Click Coordinates")

if map_data["last_clicked"]:
    lat = map_data["last_clicked"]["lat"]
    lon = map_data["last_clicked"]["lng"]

    click_df = pd.DataFrame(
        [{"Latitude": lat, "Longitude": lon}]
    )

    st.table(click_df)

# ---------------- DRAW RECTANGLE COORDINATES ----------------
st.subheader("⬛ Drawn Rectangle Bounds")

if map_data["all_drawings"]:
    geom = map_data["all_drawings"][-1]["geometry"]
    coords = geom["coordinates"][0]

    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]

    bounds_df = pd.DataFrame(
        [{
            "Upper-Left Lat": max(lats),
            "Upper-Left Lon": min(lons),
            "Lower-Right Lat": min(lats),
            "Lower-Right Lon": max(lons),
        }]
    )

    st.table(bounds_df)
