import streamlit as st
import ee
import folium
import pandas as pd
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date
import time
from datetime import datetime

# ---------------- Page Config ----------------
st.set_page_config(layout="wide")
st.title("🌍 Streamlit + Google Earth Engine")

# ---------------- Session State ----------------
for k in ["ul_lat", "ul_lon", "lr_lat", "lr_lon"]:
    st.session_state.setdefault(k, None)

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
    ul_lat = st.number_input("Upper-Left Latitude", value=st.session_state.ul_lat or 0.0)
    ul_lon = st.number_input("Upper-Left Longitude", value=st.session_state.ul_lon or 0.0)
    lr_lat = st.number_input("Lower-Right Latitude", value=st.session_state.lr_lat or 0.0)
    lr_lon = st.number_input("Lower-Right Longitude", value=st.session_state.lr_lon or 0.0)

    st.header("📅 Date Filter")
    start_date = st.date_input("Start Date", date(2024, 1, 1))
    end_date = st.date_input("End Date", date(2024, 12, 31))

    st.header("🛰️ Satellite")
    satellite = st.selectbox(
        "Select Satellite",
        ["Sentinel-2", "Landsat-8", "Landsat-9"]
    )

    # Start button to trigger filtering
    start_button = st.button("Start")

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
map_data = st_folium(m, height=550, width="100%", key="initial_map")

# ---------------- Rectangle Handling ----------------
roi = None

if map_data["all_drawings"]:
    geom = map_data["all_drawings"][-1]["geometry"]
    coords = geom["coordinates"][0]

    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]

    st.session_state.ul_lat = max(lats)
    st.session_state.ul_lon = min(lons)
    st.session_state.lr_lat = min(lats)
    st.session_state.lr_lon = max(lons)

    roi = ee.Geometry.Rectangle(
        [
            st.session_state.ul_lon,
            st.session_state.lr_lat,
            st.session_state.lr_lon,
            st.session_state.ul_lat,
        ]
    )

    bounds_df = pd.DataFrame([{
        "Upper-Left Lat": st.session_state.ul_lat,
        "Upper-Left Lon": st.session_state.ul_lon,
        "Lower-Right Lat": st.session_state.lr_lat,
        "Lower-Right Lon": st.session_state.lr_lon,
    }])

    st.subheader("⬛ Drawn Rectangle Bounds")
    st.table(bounds_df)

# ---------------- GEE PROCESSING ----------------
if roi and start_button:
    collection_ids = {
        "Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED",
        "Landsat-8": "LANDSAT/LC08/C02/T1_L2",
        "Landsat-9": "LANDSAT/LC09/C02/T1_L2",
    }

    collection = (
        ee.ImageCollection(collection_ids[satellite])
        .filterBounds(roi)
        .filterDate(str(start_date), str(end_date))
    )

    # Get the total count of images
    total_image_count = collection.size().getInfo()
    st.success(f"🖼️ Total Images Found: {total_image_count}")

    # Get the images that fall within the selected date range
    filtered_images = []
    if total_image_count > 0:
        image_list = collection.toList(total_image_count)

        # Filter images based on date range
        for i in range(total_image_count):
            image = ee.Image(image_list.get(i))
            timestamp = image.get("system:time_start").getInfo()
            image_date = datetime.utcfromtimestamp(timestamp / 1000).date()

            if start_date <= image_date <= end_date:
                filtered_images.append(image)

    filtered_count = len(filtered_images)
    st.success(f"🖼️ Filtered Images Displayed: {filtered_count}")

    # Create the folium map and display all filtered images
    folium_map = folium.Map(location=[22.0, 69.0], zoom_start=7)

    if filtered_count > 0:
        for image in filtered_images:
            timestamp = image.get("system:time_start").getInfo()
            date_time = datetime.utcfromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')

            if satellite == "Sentinel-2":
                vis = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}
            else:
                vis = {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0, "max": 30000}

            map_id = image.getMapId(vis)

            # Add each image as a tile layer to the folium map
            folium.TileLayer(
                tiles=map_id["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                name=f"{satellite} - {date_time}",
                overlay=True,
            ).add_to(folium_map)

        # Render the map with all images
        st.subheader("🛰️ All Clipped Satellite Images")
        st_folium(folium_map, height=550, width="100%")
    else:
        st.write("No images were found within the selected date range.")
