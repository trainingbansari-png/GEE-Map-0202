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

    # Limit the collection to the slider value
    collection = collection.limit(image_count)

    count = collection.size().getInfo()
    st.success(f"🖼️ Images Displayed: {count}")

    if count > 0:
        # Convert the collection to a list and process images
        image_list = collection.toList(count)
        
        # Display the images on the map
        for i in range(count):
            image = ee.Image(image_list.get(i))  # Get each image from the list
            if satellite == "Sentinel-2":
                vis = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000}
            else:
                vis = {"bands": ["SR_B4", "SR_B3", "SR_B2"], "min": 0, "max": 30000}

            map_id = image.getMapId(vis)

            folium.TileLayer(
                tiles=map_id["tile_fetcher"].url_format,
                attr="Google Earth Engine",
                name=satellite,
                overlay=True,
            ).add_to(m)

        # Display the updated map
        st.subheader("🛰️ Clipped Satellite Image")
        st_folium(m, height=550, width="100%")
