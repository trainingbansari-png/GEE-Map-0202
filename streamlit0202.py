import streamlit as st
import ee
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account
from datetime import date, datetime
import numpy as np
from io import BytesIO
from PIL import Image

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

    def add_time_to_image(image, formatted_date, formatted_time):
        """Adds time and date information to the image."""
        feature_collection = ee.FeatureCollection([ 
            ee.Feature(ee.Geometry.Point([st.session_state.ul_lon, st.session_state.ul_lat]), {
                'time': formatted_date + ' ' + formatted_time  # Concatenate date and time as a string
            })
        ])
        painted_image = image.paint(
            feature_collection,
            color='red',  # Red color for visibility
            width=2
        )
        return painted_image

    if total_count > 0:
        st.divider()
        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("2. Manual Frame Scrubber")
            
            # Ensure that the frame index is within the bounds of the collection
            if "frame_idx" not in st.session_state or st.session_state.frame_idx < 1:
                st.session_state.frame_idx = 1
            elif st.session_state.frame_idx > total_count:
                st.session_state.frame_idx = total_count

            frame_idx = st.slider("Slide to 'play' through time", 1, total_count, st.session_state.frame_idx)

            # Use the frame index to get the image from the collection
            img_list = collection.toList(total_count)
            selected_img = ee.Image(img_list.get(frame_idx - 1))  # Access the image at the correct index
           
            # Get the acquisition date and time
            frame_date, frame_time = get_frame_date(selected_img)
            st.caption(f"Showing Frame {frame_idx} | Date: {frame_date} | Time: {frame_time}")

            selected_img_with_time = add_time_to_image(selected_img, frame_date, frame_time)

            vis = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000} if satellite == "Sentinel-2" \
                  else {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0, "max": 30000}
           
            map_id = selected_img_with_time.clip(roi).getMapId(vis)

            frame_map = folium.Map(location=[sum(lats)/len(lats), sum(lons)/len(lons)], zoom_start=12)
            folium.TileLayer(
                tiles=map_id["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                overlay=True,
                control=False
            ).add_to(frame_map)
            
            # Properly closed parenthesis for st_folium
            st_folium(frame_map, height=400, width="100%", key=f"frame_{frame_idx}")

        with col2:
            st.subheader("3. Export Timelapse")
            fps = st.number_input("Frames Per Second", min_value=1, max_value=20, value=5)

            if st.button("🎬 Generate Animated Video"):
                with st.spinner("Stitching images..."):
                    video_collection = collection.map(lambda img: add_time_to_image(img, *get_frame_date(img))
                                                      .visualize(**vis).clip(roi))
                    
                    try:
                        video_url = video_collection.getVideoThumbURL({
                            'dimensions': 400,  # Reduced size
                            'region': roi,
                            'framesPerSecond': fps,
                            'crs': 'EPSG:3857'
                        })

                        # Display the generated video with date and time info for each frame
                        st.image(video_url, caption="Generated Timelapse | Date: {} | Time: {}".format(frame_date, frame_time), use_container_width=True)
                        st.markdown(f"[📥 Download GIF]({video_url})")

                    except Exception as e:
                        st.error(f"Error generating video: {e}")
