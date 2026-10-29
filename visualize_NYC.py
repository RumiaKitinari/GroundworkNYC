import osmnx as ox
import osmium
import geopandas

# place = "Kamppi, Helsinki, Finland"
# aoi = ox.geocoder.geocode_to_gdf(place)
# aoi.explore()

# import folium
# folium.Map(
#     location=(-38.625, -12.875),
#     control_scale=True,
# )

# print("Ran!")

fp = osmium.FileProcessor('new-york-260923.osm.pbf')\
         .with_locations()\
         .with_filter(osmium.filter.EntityFilter(osmium.osm.WAY))\
         .with_filter(osmium.filter.KeyFilter('highway'))\
         .with_filter(osmium.filter.GeoInterfaceFilter())

features = geopandas.GeoDataFrame.from_features(fp)
features.plot()