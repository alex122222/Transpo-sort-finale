import traceback
from cart import run_cart_optimization

try:
    print("Starting optimization...")
    res = run_cart_optimization("Plovdiv, Bulgaria", 600, 300, 180)
    print("Success. Result:", res)
except Exception as e:
    with open("error.log", "w", encoding="utf-8") as f:
         f.write(traceback.format_exc())
    print("Error occurred, see error.log")
