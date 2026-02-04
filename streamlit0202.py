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
for k in ["ul_lat", "ul_lon", "lr_lat", "lr_lon"]:
    st.session_state.setdefault(k, None)

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
        # Sentinel-2: QA60 band for cloud masking
        qa = image.select('QA60')
        
        # Check if QA60 band exists
        if qa is None:
            raise ValueError("QA60 band not found in Sentinel-2 image.")
        
        # Cloud and cirrus bitmask (10th and 11th bits)
        cloud_bit_mask = 1 << 10
        cirrus_bit_mask = 1 << 11
        
        # Create mask where both cloud and cirrus bits are zero
        mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(cirrus_bit_mask).eq(0))
        return image.updateMask(mask)
    
    elif satellite in ["Landsat-8", "Landsat-9"]:
        # Landsat cloud masking (QA_PIXEL band)
        qa = image.select('QA_PIXEL')
        
        # Check if QA_PIXEL band exists
        if qa is None:
            raise ValueError(f"QA_PIXEL band not found in {satellite} image.")
        
        # Bitmask for cloud (3rd bit) and cloud shadow (4th bit)
        cloud_bit_mask = 1 << 3
        shadow_bit_mask = 1 << 4
        
        # Create mask where both cloud and shadow bits are zero
        mask = qa.bitwiseAnd(cloud_bit_mask).eq(0).And(qa.bitwiseAnd(shadow_bit_mask).eq(0))
        return image.updateMask(mask)
    
    else:
        raise ValueError(f"Unsupported satellite: {satellite}")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("🧭 Area of Interest")
    st.info("Draw a rectangle on the map to define your ROI.")
    
    # Display the selected area (latitude and longitude)
    if st.session_state.ul_lat and st.session_state.ul_lon and st.session_state.lr_lat and st.session_state.lr_lon:
        st.write(f"**Upper Left Corner**: Latitude: {st.session_state.ul_lat}, Longitude: {st.session_state.ul_lon}")
        st.write(f"**Lower Right Corner**: Latitude: {st.session_state.lr_lat}, Longitude: {st.session_state.lr_lon}")
    else:
        st.write("Draw a rectangle on the map to define your area.")

    # Allow user to manually edit the coordinates (latitude and longitude)
    st.header("✏️ Edit Coordinates")
    ul_lat = st.number_input("Upper Left Latitude", value=st.session_state.ul_lat, format="%.6f")
    ul_lon = st.number_input("Upper Left Longitude", value=st.session_state.ul_lon, format="%.6f")
    lr_lat = st.number_input("Lower Right Latitude", value=st.session_state.lr_lat, format="%.6f")
    lr_lon = st.number_input("Lower Right Longitude", value=st.session_state.lr_lon, format="%.6f")

    # Update session state with the manually edited values
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

# Get the coordinates of the drawn rectangle and update session state
map_data = st_folium(m, height=400, width="100%", key="roi_map")

if map_data and map_data["all_drawings"]:
    geom = map_data["all_drawings"][-1]["geometry"]
    coords = geom["coordinates"][0]
    lats, lons = [c[1] for c in coords], [c[0] for c in coords]
    
    # Update session state with the current rectangle coordinates
    st.session_state.ul_lat = min(lats)
    st.session_state.ul_lon = min(lons)
    st.session_state.lr_lat = max(lats)
    st.session_state.lr_lon = max(lons)

# ---------------- Processing Logic ----------------
roi = None

# Initialize roi only if the coordinates are valid (i.e. non-empty)
if st.session_state.ul_lat and st.session_state.ul_lon and st.session_state.lr_lat and st.session_state.lr_lon:
    roi = ee.Geometry.Rectangle([st.session_state.ul_lon, st.session_state.ul_lat,
                                 st.session_state.lr_lon, st.session_state.lr_lat])

# Only proceed if roi is valid
if roi:
    try:
        # Check if the roi has valid bounds
        bounds = roi.bounds().getInfo()
        if bounds and len(bounds['coordinates'][0]) > 0:
            collection_ids = {
                "Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED",
                "Landsat-8": "LANDSAT/LC08/C02/T1_L2",
                "Landsat-9": "LANDSAT/LC09/C02/T1_L2",
            }

            collection = (ee.ImageCollection(collection_ids[satellite])
                        .filterBounds(roi)
                        .filterDate(str(start_date), str(end_date))
                        .map(lambda img: mask_clouds(img, satellite))  # Map with cloud masking
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

                    # Add time text to image
                    selected_img_with_time = add_time_to_image(selected_img, dt)

                    # Ensure the region is valid and clip the image
                    map_id = selected_img_with_time.clip(roi).getMapId(vis)

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
                st.error("No images found in the selected date range.")
        else:
            st.warning("Invalid region of interest.")
    except Exception as e:
        st.error(f"Error: {e}")
else:
    st.warning("Please define a valid region of interest (ROI) by selecting a rectangle on the map.")
