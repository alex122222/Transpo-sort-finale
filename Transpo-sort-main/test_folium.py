import folium
m2 = folium.Map(location=[42, 24])
stops_group = folium.FeatureGroup(name="Proposed Stops")
folium.Marker(location=[42, 24], icon=folium.Icon(color="red")).add_to(stops_group)
stops_group.add_to(m2)
m2.save("test_folium.html")
print("Saved test_folium.html")
