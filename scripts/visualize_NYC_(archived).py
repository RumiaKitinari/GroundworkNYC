import osmnx as ox

place = "Kamppi, Helsinki, Finland"
aoi = ox.geocoder.geocode_to_gdf(place)
aoi.explore()
# import folium
# folium.Map(
#     location=(-38.625, -12.875),
#     control_scale=True,
# )

# print("Ran!")