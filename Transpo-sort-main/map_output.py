import folium
from folium.plugins import HeatMap

def build_map(
    center,
    city_polygon,
    neighborhood_polygon,
    streets,
    buildings,
    demand,
    new_stops,
    filename="outputs/result.html"
):
    m = folium.Map(location=center)
    
    # Calculate bounds for auto-zoom [[lat_min, lon_min], [lat_max, lon_max]]
    min_lon, min_lat, max_lon, max_lat = neighborhood_polygon.bounds
    m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])

    folium.GeoJson(
        neighborhood_polygon.__geo_interface__,
        style_function=lambda x: {
            "color": "red",
            "fillColor": "red",
            "fillOpacity": 0.25,
            "weight": 3,
        },
        name="New neighborhood",
    ).add_to(m)

    for s in streets:
        folium.GeoJson(s.__geo_interface__).add_to(m)

    for b in buildings:
        folium.GeoJson(
            b.__geo_interface__,
            style_function=lambda x: {
                "color": "#666",
                "fillColor": "#bbb",
                "fillOpacity": 0.6,
                "weight": 1,
            },
        ).add_to(m)

    HeatMap([[lat, lon, w] for lat, lon, w in demand]).add_to(m)

    folium.map.CustomPane("stops_pane", z_index=999).add_to(m)

    stops_fg = folium.FeatureGroup(name="Proposed Stops", overlay=True).add_to(m)
    
    for lat, lon in new_stops:
        folium.CircleMarker(
            location=[lat, lon],
            radius=10,
            color="black",
            weight=3,
            fill=True,
            fill_color="cyan",
            fill_opacity=1.0,
            pane="stops_pane",
            tooltip=f"{lat:.6f}, {lon:.6f}",
        ).add_to(stops_fg)

    folium.LayerControl(collapsed=False).add_to(m)

    m.save(filename)
    return filename
