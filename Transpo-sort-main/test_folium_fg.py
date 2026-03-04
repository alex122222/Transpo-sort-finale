import folium
m = folium.Map(location=[0, 0], zoom_start=2)
fg = folium.FeatureGroup(name="Test FG").add_to(m)
folium.CircleMarker([0, 0], radius=10, popup="I am here").add_to(fg)
m.save("test_fg.html")
print("Saved!")
