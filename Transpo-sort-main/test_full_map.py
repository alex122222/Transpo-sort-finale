import folium
from folium.plugins import HeatMap
m = folium.Map([0, 0], zoom_start=2)

folium.map.CustomPane("heat_pane", z_index=200).add_to(m)
HeatMap([[0,0,1]], radius=15, blur=20, pane="heat_pane").add_to(m)
folium.map.CustomPane("stops_pane", z_index=999).add_to(m)
fg = folium.FeatureGroup(name="Proposed Stops", overlay=True).add_to(m)
folium.CircleMarker([0,0], radius=10, pane="stops_pane").add_to(fg)
folium.LayerControl().add_to(m)

m.save("test_full_map.html")
print("Saved map")
