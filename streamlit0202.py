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
    )

    # Get the total count of images
    total_image_count = collection.size().getInfo()
    st.success(f"🖼️ Total Images Found: {total_image_count}")

    # Add image count slider with a dynamic maximum value based on total available images
    image_count = st.slider(
        "Number of Images to Show",
        min_value=1,
        max_value=total_image_count,
        value=min(5, total_image_count),  # Default is 5, but ensure it's not higher than total count
    )

    # Limit the collection to the selected image count
    collection = collection.limit(image_count)

    count = collection.size().getInfo()
    st.success(f"🖼️ Images Displayed: {count}")

    if count > 0:
        # Convert the collection to a list and process images
        image_list = collection.toList(count)

        # Create a new map to display all images
        folium_map = folium.Map(location=[22.0, 69.0], zoom_start=7)

        # Display all images within the selected date range
        for i in range(count):
            image = ee.Image(image_list.get(i))  # Get each image from the list

            # Get the timestamp (system:time_start) of the image
            timestamp = image.get("system:time_start").getInfo()
            date_time = datetime.utcfromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')

            # Check if the image date falls within the selected date range
            if start_date <= datetime.utcfromtimestamp(timestamp / 1000).date() <= end_date:
               
                # Set visualization parameters for each satellite type
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
