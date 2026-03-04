from cart import run_cart_optimization
url = run_cart_optimization(
    place_query="Plovdiv, Bulgaria",
    walk_distance_m=600,
    min_stop_distance_m=300,
    num_candidate_points=180
)
print("Map URL:", url)
