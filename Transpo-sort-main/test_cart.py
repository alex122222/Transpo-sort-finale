import cart

# Monkeypatch limits for fast testing
cart.TIME_LIMIT_S = 10
cart.num_points = 200 # faster heatmap
cart.WORKERS = 4

try:
    res = cart.run_cart_optimization('Plovdiv, Bulgaria', 600, 300, 40)
    print('SUCCESS:', res)
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR:', e)
