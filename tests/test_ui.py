import os
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")


def test_frontend_sentiment():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,800")

    driver = webdriver.Chrome(options=options)
    try:
        driver.get(BASE_URL)

        text_input = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "text-input"))
        )
        text_input.send_keys("This product is absolutely great, I love it!")

        submit_btn = driver.find_element(By.ID, "submit-btn")
        submit_btn.click()

        # Give the backend (DistilBERT inference) time to respond
        result = WebDriverWait(driver, 60).until(
            lambda d: d.find_element(By.ID, "result-output").text.strip() != ""
        )

        result_text = driver.find_element(By.ID, "result-output").text

        assert result_text.strip() != ""
        assert any(
            keyword in result_text
            for keyword in ["POSITIVE", "NEGATIVE", "Confidence"]
        )
    finally:
        driver.quit()
