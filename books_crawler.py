from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time

BASE_URL = "https://www.bookdelivery.com/"

options = Options()
options.add_argument("--start-maximized")

driver = webdriver.Chrome(options=options)

try:
    print("Opening site...", flush=True)
    driver.get(BASE_URL)

    print("Current title:", repr(driver.title), flush=True)

    print("\nLook at the Chrome window.", flush=True)
    print("If you see Human Verification, solve it manually.", flush=True)
    input("Only after the REAL homepage loads, press ENTER here...")

    time.sleep(3)

    html = driver.page_source
    soup = BeautifulSoup(html, "html.parser")
    links = soup.find_all("a", href=True)

    print("\n========== PAGE DEBUG ==========")
    print("Current URL:", driver.current_url)
    print("Title:", repr(driver.title))
    print("HTML length:", len(html))

    print("\n========== LINKS DEBUG ==========")
    print("Total links:", len(links))

    for i, a in enumerate(links[:150]):
        text = a.get_text(" ", strip=True)
        href = a.get("href")
        full_url = urljoin(BASE_URL, href)

        if text:
            print(f"[{i}] {repr(text)} -> {full_url}")

    print("\n========== POSSIBLE CATEGORIES ==========")

    categories = {}

    for a in links:
        text = a.get_text(" ", strip=True)
        href = a.get("href", "")
        full_url = urljoin(BASE_URL, href)

        if not text:
            continue

        if urlparse(full_url).netloc != urlparse(BASE_URL).netloc:
            continue

        href_lower = href.lower()

        if (
            "category" in href_lower
            or "categories" in href_lower
            or "subject" in href_lower
            or "browse" in href_lower
            or "books" in href_lower
        ):
            categories[text] = full_url
            print(text, "->", full_url)

    print("\nFound possible categories:", len(categories))

finally:
    driver.quit()
