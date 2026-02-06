import streamlit as st
import ee
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date, datetime
import numpy as np
import moviepy.editor as mpy  # This is for creating the video

# ---------------- Page Config ----------------
st.set_page_config(layout="wide", page_title="GEE Satellite Data Viewer")
st.title("🌍 GEE Satellite Data Viewer")

# ---------------- Session State ----------------
for k in ["ul_lat", "ul_lon", "lr_lat", "lr_lon", "frame_idx", "is_playing", "index"]:
    if k not in st.session_state:
        st.session_state[k] = None

# Initialize `frame_idx`, `is_playing`, and `index` if not set already
if st.session_state.frame_idx is None:
    st.session_state.frame_idx = 1

if st.session_state.is_playing is None:
    st.session_state.is_playing = False

if st.session_state.index is None:
    st.session_state.index = "Level 1"  # Default to Level 1

# ---------------- EE Init ----------------
def initialize_ee():
    try:
        # Authenticate and initialize Earth Engine
        service_account_info = dict(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/earthengine.readonly"],
        )
        ee.Initialize(credentials)  # Initialize Earth Engine with service account credentials
        st.success("Earth Engine initialized successfully.")
    except Exception as e:
        st.error(f"Error initializing Earth Engine: {e}")

initialize_ee()

# ---------------- Cloud Masking Functions ----------------
def mask_clouds(image, satellite):
    if satellite == "Sentinel-2":
        qa = image.select('QA60')
        cloud_bit_mask = 1 << 10
        cirrus_bit_mask = 1 << 11
        mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
        return image.updateMask(mask)
   
    elif satellite in ["Landsat-8", "Landsat-9"]:
        qa = image.select('QA_PIXEL')
        cloud_bit_mask = 1 << 3
        shadow_bit_mask = 1 << 4
        mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(shadow_bit_mask).eq(0))
        return image.updateMask(mask)
   
    else:
        raise ValueError(f"Unsupported satellite: {satellite}")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("🧭 Area of Interest")
    st.info("Draw a rectangle on the map to define your ROI.")
    if st.session_state.ul_lat and st.session_state.ul_lon and st.session_state.lr_lat and st.session_state.lr_lon:
        st.write(f"**Upper Left Corner**: Latitude: {st.session_state.ul_lat}, Longitude: {st.session_state.ul_lon}")
        st.write(f"**Lower Right Corner**: Latitude: {st.session_state.lr_lat}, Longitude: {st.session_state.lr_lon}")
    else:
        st.write("Draw a rectangle on the map to define your area.")

    st.header("✏️ Edit Coordinates")
    ul_lat = st.number_input("Upper Left Latitude", value=st.session_state.ul_lat, format="%.6f")
    ul_lon = st.number_input("Upper Left Longitude", value=st.session_state.ul_lon, format="%.6f")
    lr_lat = st.number_input("Lower Right Latitude", value=st.session_state.lr_lat, format="%.6f")
    lr_lon = st.number_input("Lower Right Longitude", value=st.session_state.lr_lon, format="%.6f")
    st.session_state.ul_lat = ul_lat
    st.session_state.ul_lon = ul_lon
    st.session_state.lr_lat = lr_lat
    st.session_state.lr_lon = lr_lon

    st.header("📅 Date Filter")
    start_date = st.date_input("Start Date", date(2023, 1, 1))
    end_date = st.date_input("End Date", date(2023, 12, 31))

    st.header("🛰️ Satellite")
    satellite = st.selectbox(
        "Select Satellite",
        ["Sentinel-2", "Landsat-8", "Landsat-9"]
    )

    st.header("🔢 Select Parameter")
    parameter = st.selectbox(
        "Select Parameter",
        ["Level 1", "NDVI", "NDWI", "EVI", "NDMI", "NDSI", "GNDVI", "LSWI", "SAVI", "MSAVI", "DVI", "VIs"]
    )
    st.session_state.index = parameter  # Store selected parameter

# ---------------- Map Selection ----------------
st.subheader("1. Select your Area")
m = folium.Map(location=[22.0, 69.0], zoom_start=6)
draw = Draw(draw_options={"polyline": False, "polygon": False, "circle": False,
                          "marker": False, "circlemarker": False, "rectangle": True})
draw.add_to(m)

map_data = st_folium(m, height=400, width="100%", key="roi_map")

if map_data and map_data["all_drawings"]:
    geom = map_data["all_drawings"][-1]["geometry"]
    coords = geom["coordinates"][0]
    lats, lons = [c[1] for c in coords], [c[0] for c in coords]
    st.session_state.ul_lat = min(lats)
    st.session_state.ul_lon = min(lons)
    st.session_state.lr_lat = max(lats)
    st.session_state.lr_lon = max(lons)

# ---------------- Processing Logic ----------------
roi = None
if st.session_state.ul_lat and st.session_state.ul_lon and st.session_state.lr_lat and st.session_state.lr_lon:
    roi = ee.Geometry.Rectangle([st.session_state.ul_lon, st.session_state.ul_lat,
                                 st.session_state.lr_lon, st.session_state.lr_lat])

    collection_ids = {
        "Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED",
        "Landsat-8": "LANDSAT/LC08/C02/T1_L2",
        "Landsat-9": "LANDSAT/LC09/C02/T1_L2",
    }

    collection = (ee.ImageCollection(collection_ids[satellite])
                  .filterBounds(roi)
                  .filterDate(str(start_date), str(end_date))
                  .map(lambda img: mask_clouds(img, satellite))  # Map with cloud masking
                  .sort("system:time_start")
                  .limit(30))  # Limit to a smaller number of frames (e.g., 30)

    total_count = collection.size().getInfo()

    def get_frame_date(image):
        """Extracts the acquisition date."""
        timestamp = ee.Date(image.get("system:time_start"))
        timestamp_seconds = timestamp.millis().divide(1000)  # Convert to seconds
        timestamp_python = datetime.utcfromtimestamp(timestamp_seconds.getInfo())  # Convert to Python datetime
        formatted_date = timestamp_python.strftime('%Y-%m-%d')  # Format date
        formatted_time = timestamp_python.strftime('%H:%M:%S')  # Format time
        return formatted_date, formatted_time

    def compute_index(image, index):
        """Computes different indices based on the selected parameter."""
        if index == "NDVI":
            # Calculate NDVI
            ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
            return ndvi
        elif index == "NDWI":
            # Calculate NDWI
            ndwi = image.normalizedDifference(['B3', 'B8']).rename('NDWI')
            return ndwi
        elif index == "EVI":
            # Calculate EVI
            evi = image.expression(
                "2.5 * ((B8 - B4) / (B8 + 6 * B4 - 7.5 * B2 + 10000))",
                {'B8': image.select('B8'), 'B4': image.select('B4'), 'B2': image.select('B2')}
            ).rename('EVI')
            return evi
        # Add other indices here following a similar approach
        else:
            # For "Level 1", just return the default RGB bands
            return image.select(['B4', 'B3', 'B2'])

    if total_count > 0:
        st.divider()
        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("2. Generate Timelapse Video")

            # Prepare images for video
            images_for_video = []
            for i in range(total_count):
                img = ee.Image(collection.toList(total_count).get(i))
                result = compute_index(img, st.session_state.index)
                
                # Generate a thumbnail URL for each image
                vis_params = {
                    'min': -1, 'max': 1, 'palette': ['blue', 'white', 'green']
                }
                map_id = result.getMapId(vis_params)
                thumbnail_url = map_id["tile_fetcher"].url_format

                images_for_video.append(thumbnail_url)
            
            # Use moviepy to create video from the images
            video_file_path = "timelapse_video.mp4"
            video_clips = [mpy.ImageClip(img).set_duration(0.5) for img in images_for_video]
            video = mpy.concatenate_videoclips(video_clips, method="compose")
            video.write_videofile(video_file_path, fps=24)

            # Display the video in Streamlit
            st.video(video_file_path)
