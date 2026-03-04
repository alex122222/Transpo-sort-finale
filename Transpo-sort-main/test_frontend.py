from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import time
import json
import traceback

def run_test():
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    
    try:
        driver.get("http://127.0.0.1:5000/neighborhood")
        print("Page loaded")
        time.sleep(2)
        
        # We need to simulate drawing on the map:
        script = """
        // Draw a simple polygon in Leaflet
        var latlngs = [
          [40.78, -73.97],
          [40.785, -73.97],
          [40.785, -73.965],
          [40.78, -73.965]
        ];
        var polygon = L.polygon(latlngs, {color: 'red'}).addTo(drawnItems);
        // Force the optimize run
        window.fetch = async function(url, options) {
            console.log("FETCH URL: ", url);
            console.log("FETCH BODY: ", options.body);
            const r = await fetch.prototype.apply(this, arguments);
            const text = await r.clone().text();
            console.log("FETCH RESULT: ", text);
            return r;
        };
        runOptimization();
        """
        
        driver.execute_script(script)
        print("Executed script")
        time.sleep(5)
        
        for entry in driver.get_log('browser'):
            print("BROWSER LOG:", entry)
            
    except Exception as e:
        traceback.print_exc()
    finally:
        driver.quit()

if __name__ == "__main__":
    run_test()
