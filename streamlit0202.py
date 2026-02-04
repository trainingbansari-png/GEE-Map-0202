import streamlit as st
import ee
from datetime import date, datetime
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium
from google.oauth2 import service_account

# Initialize Earth Engine
def initialize_ee():
    try:
        service_account_info = dict(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/earthengine.readonly"]
        )
        ee.Initialize(credentials)
        st.success("Earth Engine initialized successfully.")
    except Exception as e:
        st.error(f"Error initializing Earth Engine: {e}")

initialize_ee()

# Cloud Masking Function
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

# Function to add date and time text to each frame
def add_time_to_image(image, dt):
    # Create a feature collection with the date as a property
    feature_collection = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([st.session_state.ul_lon, st.session_state.ul_lat]), {'time': dt})
    ])

    # Paint the image with the feature collection and add the date text
    painted_image = image.paint(
        feature_collection,
        color='black',  # Text color
        width=2
    )
    return painted_image

# Sidebar and User Inputs
st.sidebar.header("🧭 Area of Interest")
st.sidebar.info("Draw a rectangle on the map to define your ROI.")
start_date = st.sidebar.date_input("Start Date", date(2023, 1, 1))
end_date = st.sidebar.date_input("End Date", date(2023, 12, 31))
satellite = st.sidebar.selectbox("Select Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])

# Create a map for area selection
m = folium.Map(location=[22.0, 69.0], zoom_start=6)
draw = Draw(draw_options={"polyline": False, "polygon": False, "circle": False, 
                          "marker": False, "circlemarker": False, "rectangle": True})
draw.add_to(m)

# Get the coordinates of the drawn rectangle
map_data = st_folium(m, height=400, width="100%", key="roi_map")
if map_data and map_data["all_drawings"]:
    geom = map_data["all_drawings"][-1]["geometry"]
    coords = geom["coordinates"][0]
    lats, lons = [c[1] for c in coords], [c[0] for c in coords]
    st.session_state.ul_lat = min(lats)
    st.session_state.ul_lon = min(lons)
    st.session_state.lr_lat = max(lats)
    st.session_state.lr_lon = max(lons)

# Processing the image collection
roi = ee.Geometry.Rectangle([st.session_state.ul_lon, st.session_state.ul_lat,
                             st.session_state.lr_lon, st.session_state.lr_lat])

# Setup Earth Engine Image Collection
collection_ids = {
    "Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED",
    "Landsat-8": "LANDSAT/LC08/C02/T1_L2",
    "Landsat-9": "LANDSAT/LC09/C02/T1_L2",
}

collection = ee.ImageCollection(collection_ids[satellite]) \
    .filterBounds(roi) \
    .filterDate(str(start_date), str(end_date)) \
    .map(lambda img: mask_clouds(img, satellite)) \
    .sort("system:time_start")

total_count = collection.size().getInfo()

if total_count > 0:
    st.subheader("2. Manual Frame Scrubber")
    frame_idx = st.slider("Slide to 'play' through time", 1, total_count, 1)

    # Get specific image
    img_list = collection.toList(total_count)
    selected_img = ee.Image(img_list.get(frame_idx - 1))

    # Metadata
    ts = selected_img.get("system:time_start").getInfo()
    dt = datetime.utcfromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M:%S')
    st.caption(f"Showing Frame {frame_idx} | Date: {dt}")

    # Add time to the selected image
    selected_img_with_time = add_time_to_image(selected_img, dt)

    # Visualization
    vis = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000} if satellite == "Sentinel-2" \
          else {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0, "max": 30000}
    
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
