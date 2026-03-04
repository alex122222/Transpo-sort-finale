import folium
m = folium.Map()
folium.CircleMarker([0, 0], pane='markerPane').add_to(m)
m.save('test_pane.html')
