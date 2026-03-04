import cart
try:
    res = cart.run_cart_optimization('Plovdiv, Bulgaria', 600, 300, 180)
    print(f"SUCCESS: {res}")
except Exception as e:
    print(f"ERROR: {e}")
