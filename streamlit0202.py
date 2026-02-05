import streamlit as st
import ee
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date, datetime
import time

# ---------------- Page Config ----------------
st.set_page_config(layout="wide", page_title="GEE Timelapse Pro")
st.title("🌍 GEE Satellite Video Generator")

# ---------------- Session State ----------------
for k in ["ul_lat", "ul_lon", "lr_lat", "lr_lon", "frame_idx", "is_playing"]:
    if k not in st.session_state:
        st.session_state[k] = None

# Initialize `frame_idx` and `is_playing` if not set already
if st.session_state.frame_idx is None:
    st.session_state.frame_idx = 1

if st.session_state.is_playing is None:
    st.session_state.is_playing = False

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
        if qa is None:
            raise ValueError("QA60 band not found in Sentinel-2 image.")
        cloud_bit_mask = 1 << 10
        cirrus_bit_mask = 1 << 11
        mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
        return image.updateMask(mask)
   
    elif satellite in ["Landsat-8", "Landsat-9"]:
        qa = image.select('QA_PIXEL')
        if qa is None:
            raise ValueError(f"QA_PIXEL band not found in {satellite} image.")
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

    def add_timestamp_to_image(image, timestamp):
        """Adds timestamp to the image as a label."""
        # Create a feature collection with timestamp information
        feature_collection = ee.FeatureCollection([ 
            ee.Feature(ee.Geometry.Point([st.session_state.ul_lon, st.session_state.ul_lat]), {
                'time': timestamp  # Store timestamp as a property
            })
        ])
        # Paint the timestamp and return the updated image
        painted_image = image.paint(feature_collection, color='black', width=2)
        return painted_image

    if total_count > 0:
        st.divider()
        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("2. Export Timelapse")
            fps = st.number_input("Frames Per Second", min_value=1, max_value=20, value=5)

            play_button = st.button("▶️ Play")
            pause_button = st.button("⏸️ Pause")

            # Manage play/pause functionality
            if play_button:
                st.session_state.is_playing = True
            if pause_button:
                st.session_state.is_playing = False

            if st.session_state.is_playing:
                # Automatic frame progression for play
                while st.session_state.frame_idx < total_count and st.session_state.is_playing:
                    time.sleep(1 / fps)  # Control the playback speed
                    st.session_state.frame_idx += 1  # Move to the next frame
                    st.experimental_rerun()  # Re-run to refresh the app with new frame

            # Now, generate the video with timestamps
            if st.button("🎬 Generate Animated Video"):
                with st.spinner("Stitching images..."):
                    # Add timestamps to each image in the collection
                    video_collection = collection.map(lambda img: img.visualize(**vis).clip(roi))

                    # Apply the timestamp to each frame
                    def add_timestamp_to_frame(img):
                        timestamp_ms = img.get("system:time_start").getInfo()
                        timestamp = datetime.utcfromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d')
                        # Apply timestamp to image and return it
                        return add_timestamp_to_image(img, timestamp)

                    # Apply timestamp function to all images
                    video_collection = video_collection.map(add_timestamp_to_frame)
                    
                    try:
                        video_url = video_collection.getVideoThumbURL({
                            'dimensions': 400,  # Reduced size
                            'region': roi,
                            'framesPerSecond': fps,
                            'crs': 'EPSG:3857'
                        })
                        st.image(video_url, caption="Generated Timelapse with Timestamps", use_container_width=True)
                        st.markdown(f"[📥 Download GIF]({video_url})")

                    except Exception as e:
                        st.error(f"Error generating video: {e}")
