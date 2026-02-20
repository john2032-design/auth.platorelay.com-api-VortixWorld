# app.py - Main API script using FastAPI
import time
from fastapi import FastAPI
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from captcha_solver import solve_stage  # Logic for solving captcha, adapted from pow_client.py
from abysm_bypass import bypass_link
from visual_verification import analyze_shape

app = FastAPI()

@app.get("/get_key")
def get_key(start_url: str = "https://auth.platorelay.com"):  # Optional param for start URL if needed
    driver = webdriver.Chrome()  # Assume ChromeDriver is installed and in PATH
    try:
        driver.get(start_url)
        key = perform_process(driver)
        return {"key": key}
    finally:
        driver.quit()

def perform_process(driver):
    completed = 0
    while completed < 2:
        time.sleep(5)
        # Check for completed status
        completed = get_completed_status(driver)
        if completed >= 2:
            break

        # Find and click continue button
        click_continue_button(driver)

        # Wait for sentry
        wait_for_sentry(driver)

        # Solve the captcha on sentry
        solve_captcha_in_browser(driver)

        # Wait for linkvertise or loot
        wait_for_bypass_site(driver)

        # Bypass using Abysm API
        current_url = driver.current_url
        result_url = bypass_link(current_url)
        if result_url is None:
            return "Bypass failed"
        driver.get(result_url)

        # Back to auth, loop
    # After 2/2, wait 5s, click continue/create key
    time.sleep(5)
    click_create_key_button(driver)

    # Extract the key
    key = extract_key(driver)
    return key

def get_completed_status(driver):
    try:
        status_text = driver.find_element(By.XPATH, "//*[contains(text(), 'Completed')]").text
        if "Completed 0/2" in status_text:
            return 0
        elif "Completed 1/2" in status_text:
            return 1
        elif "Completed 2/2" in status_text:
            return 2
    except NoSuchElementException:
        pass
    return 0

def click_continue_button(driver):
    try:
        button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//button[contains(text(), "Continue") or contains(text(), "Lootlabs")]'))
        )
        button.click()
    except TimeoutException:
        raise ValueError("No continue or Lootlabs button found")

def wait_for_sentry(driver):
    WebDriverWait(driver, 30).until(
        lambda d: "sentry.platorelay.com" in d.current_url
    )

def solve_captcha_in_browser(driver):
    # Assume the page has one stage at a time, loop until not on sentry
    while "sentry.platorelay.com" in driver.current_url:
        time.sleep(2)  # Wait for load
        # Extract instruction
        try:
            instruction_elem = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".instruction"))  # Assume class 'instruction'
            )
            instruction = instruction_elem.text
        except TimeoutException:
            raise ValueError("No instruction found on sentry page")

        # Extract images
        try:
            image_elems = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".shape-img"))  # Assume class 'shape-img' for imgs
            )
        except TimeoutException:
            raise ValueError("No shape images found on sentry page")

        shapes = []
        for elem in image_elems:
            b64 = elem.get_attribute("src")
            if b64.startswith("data:"):
                shapes.append({"img": b64})

        # Solve
        stage = {"instruction": instruction, "shapes": shapes}
        answer_idx = solve_stage(stage, 0)  # Stage idx not used

        # Click the chosen image
        image_elems[int(answer_idx)].click()

        # Wait for next stage or redirect
        time.sleep(2)

def wait_for_bypass_site(driver):
    WebDriverWait(driver, 30).until(
        lambda d: "linkvertise" in d.current_url or "loot" in d.current_url
    )

def click_create_key_button(driver):
    try:
        button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//button[contains(text(), "Continue") or contains(text(), "Create Key")]'))
        )
        button.click()
    except TimeoutException:
        raise ValueError("No continue or create key button found")

def extract_key(driver):
    try:
        key_elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[starts-with(text(), 'FREE_')]"))
        )
        return key_elem.text
    except TimeoutException:
        raise ValueError("No FREE_ key found")

# Run with uvicorn app:app --reload