import streamlit as st
import ee
from datetime import date
import base64
from PIL import Image
import io

# ---------------- EE Init ----------------
def initialize_ee():
    try:
        ee.GetLibraryVersion()
    except Exception:
        try:
            if "GCP_SERVICE_ACCOUNT_JSON" in st.secrets:
                from google.oauth2 import service_account
                service_account_info = dict(st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
                credentials = service_account.Credentials.from_service_account_info(
                    service_account_info,
                    scopes=["https://www.googleapis.com/auth/earthengine.readonly"],
                )
                ee.Initialize(credentials)
                st.success("Earth Engine Initialized")
        except Exception as e:
            st.error(f"EE Init Error: {e}")

initialize_ee()

# ---------------- Helper Functions ----------------
def get_band_map(satellite):
    if "Sentinel" in satellite:
        return {'red': 'B4', 'green': 'B3', 'blue': 'B2', 'nir': 'B8', 'swir1': 'B11'}
    else:
        return {'red': 'B4', 'green': 'B3', 'blue': 'B2', 'nir': 'B5', 'swir1': 'B6'}

def mask_clouds(image, satellite):
    if "Sentinel" in satellite:
        qa = image.select('QA60')
        mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
    else: 
        qa = image.select('QA_PIXEL')
        mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
    return image.updateMask(mask)

def apply_parameter(image, parameter, satellite):
    bm = get_band_map(satellite)
    if parameter == "Level1": return image
    if parameter == "NDVI": return image.normalizedDifference([bm['nir'], bm['red']]).rename(parameter)
    if parameter == "NDWI": return image.normalizedDifference([bm['green'], bm['nir']]).rename(parameter)
    if parameter == "MNDWI": return image.normalizedDifference([bm['green'], bm['swir1']]).rename(parameter)
    if parameter == "EVI":
        return image.expression('2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))',
            {'NIR': image.select(bm['nir']), 'RED': image.select(bm['red']), 'BLUE': image.select(bm['blue'])}
        ).rename(parameter)
    return image

def get_parameter_value(image, parameter, satellite, roi):
    """Return mean value of parameter in ROI"""
    param_image = apply_parameter(image, parameter, satellite)
    value = param_image.reduceRegion(ee.Reducer.mean(), roi, 30).get(parameter if parameter != "Level1" else "B4").getInfo()
    return value

def image_to_base64(image):
    """Convert an image to base64 format."""
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

# ---------------- Sidebar ----------------
st.sidebar.header("Configuration")
start_date = st.sidebar.date_input("Start Date", date(2024, 1, 1))
end_date = st.sidebar.date_input("End Date", date(2024, 12, 31))
satellite = st.sidebar.selectbox("Satellite", ["Sentinel-2", "Landsat-8", "Landsat-9"])
parameter = st.sidebar.selectbox("Parameter", ["Level1", "NDVI", "NDWI", "MNDWI", "EVI"])

# ---------------- ROI ----------------
st.sidebar.header("ROI Coordinates")
ul_lat = st.sidebar.number_input("Upper Lat", 22.5)
ul_lon = st.sidebar.number_input("Left Lon", 69.5)
lr_lat = st.sidebar.number_input("Lower Lat", 21.5)
lr_lon = st.sidebar.number_input("Right Lon", 70.5)
roi = ee.Geometry.Rectangle([ul_lon, lr_lat, lr_lon, ul_lat])

# ---------------- Image Collection ----------------
col_id = {"Sentinel-2": "COPERNICUS/S2_SR_HARMONIZED",
          "Landsat-8": "LANDSAT/LC08/C02/T1_L2",
          "Landsat-9": "LANDSAT/LC09/C02/T1_L2"}[satellite]

collection = (ee.ImageCollection(col_id)
              .filterBounds(roi)
              .filterDate(str(start_date), str(end_date))
              .map(lambda img: mask_clouds(img, satellite))
              .sort("system:time_start"))

total_images = collection.size().getInfo()
st.write(f"Total images available: {total_images}")

if total_images > 0:
    # Get the list of image URLs for the thumbnails
    image_urls = []
    image_list = collection.toList(total_images)
    
    # Generate thumbnails for each image in the collection
    for i in range(min(total_images, 30)):  # Limit to first 30 images for display
        img = ee.Image(image_list.get(i))
        timestamp = ee.Date(img.get("system:time_start")).format("YYYY-MM-DD").getInfo()

        try:
            # Specify only the RGB bands (B4, B3, B2 for Sentinel-2 or similar for Landsat)
            rgb_bands = img.select(['B4', 'B3', 'B2'])  # Update with correct RGB bands
            thumb = rgb_bands.getThumbURL({'dimensions': 60, 'region': roi, 'format': 'png'})
            image_urls.append((thumb, timestamp))
        except Exception as e:
            st.warning(f"Error generating thumbnail for image {i+1}: {str(e)}")
            continue
    
    # Display thumbnails as clickable images
    selected_frame = None
    for idx, (thumb_url, timestamp) in enumerate(image_urls):
        if st.button(f"Image {idx+1} - {timestamp}", key=f"image_{idx}"):
            selected_frame = idx
            st.session_state.selected_frame = selected_frame
    
    # Show the parameter value for the clicked frame
    if selected_frame is not None:
        # Get the selected image
        selected_image = ee.Image(image_list.get(selected_frame))
        parameter_value = get_parameter_value(selected_image, parameter, satellite, roi)
        st.write(f"**Selected Frame Timestamp:** {image_urls[selected_frame][1]}")
        st.write(f"**{parameter} Value in ROI:** {parameter_value}")
    
else:
    st.warning("No images available for this ROI/date range.")
