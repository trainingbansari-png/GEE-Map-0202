import streamlit as st
import ee
import folium
import pandas as pd
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date, datetime

# ---------------- Page Config ----------------
st.set_page_config(layout="wide", page_title="GEE Timelapse Pro")
st.title("🌍 GEE Satellite Video Generator")

# ---------------- Session State ----------------
for k in ["ul_lat", "ul_lon", "lr_lat", "lr_lon"]:
    st.session_state.setdefault(k, None)

# ---------------- EE Init ----------------
def initialize_ee():
    if not ee.data._credentials:
        service_account_info = dict(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/earthengine.readonly"],
        )
        ee.Initialize(credentials)

initialize_ee()

# ---------------- Cloud Masking Functions ----------------
def mask_clouds(image, satellite):
    if satellite == "Sentinel-2":
        qa = image.select('QA60')
        cloud_bit_mask = 1 << 10
        cirrus_bit_mask = 1 << 11
        mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).and_(
               qa.bitwiseAnd(cirrus_bit_mask).eq(0))
        return image.updateMask(mask)
    else: # Landsat 8/9
        qa = image.select('QA_PIXEL')
        mask = qa.bitwiseAnd(1 << 3).eq(0).and_(qa.bitwiseAnd(1 << 4).eq(0))
        return image.updateMask(mask)

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("🧭 Area of Interest")
    st.info("Draw a rectangle on the map to define your ROI.")
    
    st.header("📅 Date Filter")
    start_date = st.date_input("Start Date", date(2023, 1, 1))
    end_date = st.date_input("End Date", date(2023, 12, 31))

    st.header("🛰️ Satellite")
    satellite = st.selectbox(
        "Select Satellite",
        ["Sentinel-2", "Landsat-8", "Landsat-9"]
    )

# ---------------- Map Selection ----------------
st.subheader("1. Select your Area")
m = folium.Map(location=[22.0, 69.0], zoom_start=6)
Draw(draw_options={"polyline": False, "polygon": False, "circle": False, 
                   "marker": False, "circlemarker": False, "rectangle": True}).add_to(m)

map_data = st_folium(m, height=400, width="100%", key="roi_map")

# ---------------- Processing Logic ----------------
roi = None
if map_data and map_data["all_drawings"]:
    geom = map_data["all_drawings"][-1]["geometry"]
    coords = geom["coordinates"][0]
    lats, lons = [c[1] for c in coords], [c[0] for c in coords]
    
    roi = ee.Geometry.Rectangle([min(lons), min(lats), max(lons), max(lats)])

    # Setup Collection
    collection_ids = {
        "Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED",
        "Landsat-8": "LANDSAT/LC08/C02/T1_L2",
        "Landsat-9": "LANDSAT/LC09/C02/T1_L2",
    }

    collection = (ee.ImageCollection(collection_ids[satellite])
                  .filterBounds(roi)
                  .filterDate(str(start_date), str(end_date))
                  .map(lambda img: mask_clouds(img, satellite))
                  .sort("system:time_start"))

    total_count = collection.size().getInfo()

    if total_count > 0:
        st.divider()
        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("2. Manual Frame Scrubber")
            frame_idx = st.slider("Slide to 'play' through time", 1, total_count, 1)
            
            # Get specific image
            img_list = collection.toList(total_count)
            selected_img = ee.Image(img_list.get(frame_idx - 1))
            
            # Metadata
            ts = selected_img.get("system:time_start").getInfo()
            dt = datetime.utcfromtimestamp(ts / 1000).strftime('%Y-%m-%d')
            st.caption(f"Showing Frame {frame_idx} | Date: {dt}")

            # Visualization
            vis = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000} if satellite == "Sentinel-2" \
                  else {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0, "max": 30000}
            
            map_id = selected_img.clip(roi).getMapId(vis)
            
            # Display Frame Map
            frame_map = folium.Map(location=[sum(lats)/len(lats), sum(lons)/len(lons)], zoom_start=12)
            folium.TileLayer(
                tiles=map_id["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                overlay=True,
                control=False
            ).add_to(frame_map)
            st_folium(frame_map, height=400, width="100%", key=f"frame_{frame_idx}")

        with col2:
            st.subheader("3. Export Timelapse")
            fps = st.number_input("Frames Per Second", min_value=1, max_value=20, value=5)
            
            if st.button("🎬 Generate Animated Video"):
                with st.spinner("Stitching images..."):
                    video_collection = collection.map(lambda img: img.visualize(**vis).clip(roi))
                    video_url = video_collection.getVideoThumbURL({
                        'dimensions': 600,
                        'region': roi,
                        'framesPerSecond': fps,
                        'crs': 'EPSG:3857'
                    })
                    st.image(video_url, caption="Generated Timelapse", use_container_width=True)
                    st.markdown(f"[📥 Download GIF]({video_url})")
    else:
        st.warning("No clear images found for this area/date. Try a wider date range.")


On Tue, Feb 3, 2026, 4:24 PM Bansari Training <trainingbansari@gmail.com> wrote:
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
