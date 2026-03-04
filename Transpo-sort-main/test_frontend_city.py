from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time
import traceback

def run_test():
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    
    try:
        driver.get("http://127.0.0.1:5000/city_coverage")
        print("Page loaded")
        time.sleep(2)
        
        script = """
        window.fetch = async function(url, options) {
            console.log("FETCH URL: ", url);
            const r = await fetch.prototype.apply(this, arguments);
            const text = await r.clone().text();
            console.log("FETCH RESULT: ", text);
            return r;
        };
        document.getElementById('place-input').value = 'Sofia, Bulgaria';
        document.getElementById('generate-btn').click();
        """
        
        driver.execute_script(script)
        print("Executed script")
        time.sleep(15) # Wait for processing
        
        for entry in driver.get_log('browser'):
            print("BROWSER LOG:", entry)
            
    except Exception as e:
        traceback.print_exc()
    finally:
        driver.quit()

if __name__ == "__main__":
    run_test()
