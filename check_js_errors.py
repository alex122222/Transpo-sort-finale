from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument("--headless")
driver = webdriver.Chrome(options=options)
driver.get("file:///c:/Users/User/Downloads/Transpo-sort-main/Transpo-sort-main/test_full_map.html")
for entry in driver.get_log('browser'):
    print(entry)
driver.quit()
