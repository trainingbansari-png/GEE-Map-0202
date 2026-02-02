import streamlit as st
import ee
import folium
import pandas as pd
import time
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

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("🧭 Area of Interest")

    ul_lat = st.number_input("Upper-Left Latitude", value=22.0)
    ul_lon = st.number_input("Upper-Left Longitude", value=69.0)
    lr_lat = st.number_input("Lower-Right Latitude", value=21.0)
    lr_lon = st.number_input("Lower-Right Longitude", value=70.0)

    st.header("📅 Date Filter")
    start_date = st.date_input("Start Date", date(2024, 1, 1))
    end_date = st.date_input("End Date", date(2024, 12, 31))

    st.header("🛰️ Satellite")
    satellite = st.selectbox(
        "Select Satellite",
        ["Sentinel-2", "Landsat-8", "Landsat-9"]
    )

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

# ---------------- Rectangle Handling ----------------
roi = None

if map_data["all_drawings"]:
    geom = map_data["all_drawings"][-1]["geometry"]
    coords = geom["coordinates"][0]

    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]

    roi = ee.Geometry.Rectangle(
        [
            min(lons),
            min(lats),
            max(lons),
            max(lats),
        ]
    )

# ---------------- GEE Processing ----------------
if roi:
    collection_ids = {
        "Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED",
        "Landsat-8": "LANDSAT/LC08/C02/T1_L2",
        "Landsat-9": "LANDSAT/LC09/C02/T1_L2",
    }

    collection = (
        ee.ImageCollection(collection_ids[satellite])
        .filterBounds(roi)
        .filterDate(str(start_date), str(end_date))
        .sort("system:time_start")  # Ensure images are sorted by date
    )

    count = collection.size().getInfo()
    st.success(f"🖼️ Images Found: {count}")

    if count > 0:
        # Start the animation loop
        for i, image in enumerate(collection.getInfo()['features']):
            # Extract image timestamp (milliseconds)
            image_timestamp = ee.Date(image['properties']['system:time_start']).format("YYYY-MM-dd HH:mm:ss").getInfo()

            img = ee.Image(image['id'])

            # Clip image to ROI
            clipped_image = img.clip(roi)

            # Visualization parameters
            vis = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000} if satellite == "Sentinel-2" else {"min": 0, "max": 30000}

            # Get map ID and URL
            map_id = clipped_image.getMapId(vis)

            # Clear previous layers
            m = folium.Map(location=[22.0, 69.0], zoom_start=7)
            
            folium.TileLayer(
                tiles=map_id["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                name=satellite,
                overlay=True,
            ).add_to(m)

            folium.Rectangle(
                bounds=[
                    [min(lats), min(lons)],
                    [max(lats), max(lons)],
                ],
                color="red",
                fill=False,
            ).add_to(m)

            # Add the timestamp text on the map using a Marker with a popup
            folium.Marker(
                location=[(min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2],
                icon=None,  # No icon
                popup=f"🗓️ Image Date: {image_timestamp}",
            ).add_to(m)

            # Use `st.empty()` to refresh the map and make it like an animation
            with st.empty():
                # Use a unique key for each map rendering to avoid duplicates
                st_folium(m, height=550, width="100%", key=f"map_{i}")  # Key based on loop index
                st.write(f"🕒 Image Time: {image_timestamp}")  # Show timestamp on the side as well
                time.sleep(1)  # Pause for animation effect

        st.success("🎬 Animation Finished")
