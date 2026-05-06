import os
import re
import json
import time
import math
import random
import statistics
from decimal import Decimal, ROUND_CEILING
from urllib.parse import urljoin, urlparse

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


BASE_URL = "https://www.bookdelivery.com/"
ISRAEL_URL = "https://www.bookdelivery.com/il-en/"
MAX_PAGES_PER_CATEGORY = 1 
OUTPUT_DIR = "output"
EXCHANGE_RATE = 3.01

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

REQUEST_DELAY_MIN = 4
REQUEST_DELAY_MAX = 7
MAX_AUTO_RETRIES = 3


# -----------------------------
# Basic helpers
# -----------------------------

def clean_text(text):
    if text is None:
        return None
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if text else None


def ceil_2(x):
    if x is None or pd.isna(x):
        return None
    d = Decimal(str(float(x)))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_CEILING))


def polite_sleep():
    time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))


def normalize_url(url):
    if not url:
        return None
    return url.split("#")[0]


def soup_from_html(html):
    return BeautifulSoup(html, "html.parser")


def is_bad_html(html):
    if not html:
        return True

    low = html.lower()

    bad_markers = [
        "javascript is disabled",
        "enable javascript",
        "human verification",
        "verify you are human",
        "checking your browser",
        "access denied",
        "captcha",
    ]

    return any(marker in low for marker in bad_markers)


def looks_like_book_page(html):
    if is_bad_html(html):
        return False

    soup = soup_from_html(html)
    text = soup.get_text(" ", strip=True).lower()

    if "javascript is disabled" in text:
        return False

    # Book pages usually include at least some of these fields.
    indicators = [
        "isbn",
        "author",
        "publisher",
        "language",
        "format",
        "dimensions",
        "weight",
    ]
    return sum(ind in text for ind in indicators) >= 1

def clean_soup_for_parsing(soup):
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return soup


def get_numeric_values(key, record):
    values = []

    for book_info in record:
        if key not in book_info:
            continue

        val = book_info[key]

        if val is None or val == "" or val == "None":
            continue

        try:
            values.append(float(val))
        except (ValueError, TypeError):
            continue

    return values


def num_of_rows(key, record):
    return len(get_numeric_values(key, record))


def find_min(key, record):
    values = get_numeric_values(key, record)
    return min(values) if values else None


def find_max(key, record):
    values = get_numeric_values(key, record)
    return max(values) if values else None


def calculate_mean(key, record):
    values = get_numeric_values(key, record)
    return statistics.mean(values) if values else None


def calculate_median(key, record):
    values = get_numeric_values(key, record)
    return statistics.median(values) if values else None


def calculate_stdev(key, record):
    values = get_numeric_values(key, record)

    if len(values) < 2:
        return 0

    return float(np.std(values, ddof=1))

# -----------------------------
# Selenium only for first manual verification + cookies
# -----------------------------

def make_driver():
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--remote-debugging-port=9222")

    driver = webdriver.Chrome(options=chrome_options)
    return driver


# def make_session():
#     session = requests.Session()
#     session.headers.update({
#         "User-Agent": USER_AGENT,
#         "Accept": (
#             "text/html,application/xhtml+xml,application/xml;q=0.9,"
#             "image/avif,image/webp,image/apng,*/*;q=0.8"
#         ),
#         "Accept-Language": "en-US,en;q=0.9,he;q=0.8",
#         "Accept-Encoding": "gzip, deflate, br",
#         "Connection": "keep-alive",
#         "Upgrade-Insecure-Requests": "1",
#         "Sec-Fetch-Dest": "document",
#         "Sec-Fetch-Mode": "navigate",
#         "Sec-Fetch-Site": "same-origin",
#         "Sec-Fetch-User": "?1",
#     })
#     return session

def make_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.bookdelivery.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    })
    return session


def copy_selenium_cookies_to_session(driver, session):
    session.cookies.clear()

    for cookie in driver.get_cookies():
        name = cookie.get("name")
        value = cookie.get("value")
        domain = cookie.get("domain")
        path = cookie.get("path", "/")

        if not name or value is None:
            continue

        # requests is picky about domains. Try with domain, then fallback without it.
        try:
            session.cookies.set(name, value, domain=domain, path=path)
        except Exception:
            session.cookies.set(name, value)

    print(f"Copied {len(driver.get_cookies())} cookies from Selenium to requests.")


def initial_verification(driver, session):
    print("Opening BookDelivery in Chrome...")
    driver.get(ISRAEL_URL)

    print("Waiting for initial load...")
    time.sleep(15)

    driver.get(ISRAEL_URL)
    time.sleep(5)

    copy_selenium_cookies_to_session(driver, session)

    try:
        warmup = session.get(ISRAEL_URL, timeout=40)
        print("Warmup status:", warmup.status_code)
    except Exception as e:
        print("Warmup failed:", e)


def refresh_cookies_with_selenium(driver, session, url):
    print("\nRefreshing cookies automatically:")
    print(url)

    driver.get(url)
    time.sleep(12)

    copy_selenium_cookies_to_session(driver, session)

    try:
        warmup = session.get(url, timeout=40)
        print("Refresh warmup status:", warmup.status_code)
    except Exception as e:
        print("Refresh warmup failed:", e)

    polite_sleep()


# -----------------------------
# requests fetcher with strict validation
# -----------------------------

# def fetch_html(session, driver, url, validator=None, allow_manual_refresh=True):
#     """
#     Fetch with requests. If the returned page is bad, refresh cookies from Selenium
#     and retry the SAME url. This avoids collecting 'JavaScript is disabled' as data.
#     """
#     url = normalize_url(url)

#     attempt = 0
#     while True:
#         attempt += 1
#         try:
#             polite_sleep()
#             response = session.get(url, timeout=40, allow_redirects=True)
#             html = response.text

#             ok_status = 200 <= response.status_code < 300
#             ok_html = not is_bad_html(html)
#             ok_validator = True if validator is None else validator(html)

#             if ok_status and ok_html and ok_validator:
#                 return html

#             print("\nBad response from requests:")
#             print("URL:", url)
#             print("Status:", response.status_code)
#             print("Attempt:", attempt)
#             print("Page title:", get_page_title(html))

#         except requests.RequestException as e:
#             print("\nRequests error:")
#             print("URL:", url)
#             print("Attempt:", attempt)
#             print("Error:", e)

#         if attempt < MAX_AUTO_RETRIES:
#             print("Retrying same URL after delay...")
#             continue

#         if allow_manual_refresh:
#             refresh_cookies_with_selenium(driver, session, url)
#             attempt = 0
#             continue

#         raise RuntimeError(f"Could not fetch valid HTML from {url}")


def fetch_html(session, driver, url, validator=None, allow_manual_refresh=True):
    url = normalize_url(url)

    attempt = 0
    while True:
        attempt += 1

        try:
            polite_sleep()

            response = session.get(url, timeout=40, allow_redirects=True)
            html = response.text

            ok_status = response.status_code == 200
            ok_html = not is_bad_html(html)
            ok_validator = True if validator is None else validator(html)

            if ok_status and ok_html and ok_validator:
                return html

            print("\nBad response from requests:")
            print("URL:", url)
            print("Status:", response.status_code)
            print("Attempt:", attempt)
            print("Page title:", get_page_title(html))

            if response.status_code == 202:
                refresh_cookies_with_selenium(driver, session, url)
                attempt = 0
                continue

        except requests.RequestException as e:
            print("\nRequests error:")
            print("URL:", url)
            print("Attempt:", attempt)
            print("Error:", e)

        if attempt < MAX_AUTO_RETRIES:
            print("Retrying same URL after delay...")
            continue

        if allow_manual_refresh:
            refresh_cookies_with_selenium(driver, session, url)
            attempt = 0
            continue

        raise RuntimeError(f"Could not fetch valid HTML from {url}")

def get_page_title(html):
    try:
        soup = soup_from_html(html)
        if soup.title:
            return clean_text(soup.title.get_text(" ", strip=True))
    except Exception:
        pass
    return None


# -----------------------------
# Category discovery and pagination
# -----------------------------

def extract_category_links(session, driver):
    html = fetch_html(session, driver, ISRAEL_URL)
    soup = soup_from_html(html)

    categories = {}

    print("\n========== CATEGORY LINKS ==========")

    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text(" ", strip=True))
        full_url = normalize_url(urljoin(ISRAEL_URL, a["href"]))

        if not text or not full_url:
            continue

        low = full_url.lower()

        # Top-level Israel English category pages.
        if "bookdelivery.com/il-en/books/" not in low:
            continue

        # Avoid sub-subject/filter pages.
        if "/subject-" in low:
            continue

        # Avoid pagination/filter duplicates.
        parsed = urlparse(full_url)
        if parsed.query:
            continue

        categories[text] = full_url

    for name, url in categories.items():
        print(f"{name} -> {url}")

    print(f"\nFound {len(categories)} categories.")
    return categories


def build_category_page_url(category_url, page_num):
    if page_num == 1:
        return category_url
    sep = "&" if "?" in category_url else "?"
    return f"{category_url}{sep}page={page_num}"


def category_page_has_book_links(html):
    if is_bad_html(html):
        return False
    soup = soup_from_html(html)
    links = extract_book_links_from_soup(soup)
    return len(links) > 0


def extract_book_links_from_soup(soup):
    book_links = set()

    for a in soup.find_all("a", href=True):
        full_url = normalize_url(urljoin(ISRAEL_URL, a["href"]))
        if not full_url:
            continue

        low = full_url.lower()

        # Real book pages look like:
        # /il-en/book-title/isbn/p/productid
        if "/il-en/book-" in low and "/p/" in low:
            book_links.add(full_url)

    return sorted(book_links)


def extract_book_links_from_category_page(session, driver, page_url):
    print("\nOpening category page:", page_url)

    html = fetch_html(
        session,
        driver,
        page_url,
        validator=category_page_has_book_links,
        allow_manual_refresh=True,
    )
    soup = soup_from_html(html)
    book_links = extract_book_links_from_soup(soup)

    print("Book links found:", len(book_links))
    for url in book_links[:10]:
        print("BOOK:", url)

    return book_links


# -----------------------------
# Book parsing helpers
# -----------------------------

def find_field_by_label(soup, labels):
    if isinstance(labels, str):
        labels = [labels]

    labels = [x.lower().strip(":") for x in labels]

    lines = [
        clean_text(x)
        for x in soup.get_text("\n", strip=True).split("\n")
    ]
    lines = [x for x in lines if x]

    bad_values = {
        "select your country",
        "change country",
        "recommended books new",
        "customer reviews",
        "my orders",
        "help",
    }

    for i, line in enumerate(lines):
        low = line.lower().strip(":")

        for label in labels:
            if low == label or low.startswith(label + ":"):
                if ":" in line:
                    value = clean_text(line.split(":", 1)[1])
                    if value and value.lower() not in bad_values:
                        return value

                for j in range(i + 1, min(i + 5, len(lines))):
                    value = lines[j]
                    if value and value.lower() not in bad_values:
                        return value

    return None

def extract_title_and_authors(soup):
    h1 = soup.find("h1")
    raw_title = clean_text(h1.get_text(" ", strip=True)) if h1 else None

    if not raw_title and soup.title:
        raw_title = clean_text(soup.title.get_text(" ", strip=True))

    title = raw_title
    authors = None

    if raw_title and " - " in raw_title:
        title, authors = raw_title.rsplit(" - ", 1)
        title = clean_text(title)
        authors = clean_text(authors)

    field_author = find_field_by_label(soup, ["Author", "Authors"])
    if field_author and "schema.org" not in field_author and "Buscalibre" not in field_author:
        authors = field_author

    if authors:
        parts = re.split(r"\s*;\s*|\s*,\s*|\s+ and \s+|\s+&\s+", authors)
        parts = [clean_text(p) for p in parts if clean_text(p)]
        authors = ", ".join(parts)

    return title, authors

# def extract_categories(soup, fallback_category):
#     categories_text = find_field_by_label(soup, ["Categories", "Category"])

#     if categories_text:
#         parts = re.split(r",|\n|;", categories_text)
#         parts = [clean_text(p) for p in parts if clean_text(p)]

#         if parts:
#             return ", ".join(parts)

#     return fallback_category

def extract_categories(soup, fallback_category):
    lines = [
        clean_text(x)
        for x in soup.get_text("\n", strip=True).split("\n")
    ]
    lines = [x for x in lines if x]

    stop_words = {
        "type", "author", "publisher", "language", "page", "format",
        "dimensions", "weight", "isbn", "isbn13",
        "synopsis", "recommended books new", "recommended books",
        "new", "customer reviews", "my orders", "change country",
        "help", "add to cart", "share", "copy link", "link copied!"
    }

    garbage_fragments = [
        "affiliate", "whatsapp", "facebook", "pinterest",
        "linkedin", "copy", "http", "bookdelivery.com",
        "author", "recommended", "customer reviews"
    ]

    for i, line in enumerate(lines):
        if line.lower().strip(":") == "categories":
            categories = []

            for j in range(i + 1, min(i + 15, len(lines))):
                value = lines[j]
                low = value.lower().strip(":")

                if low in stop_words:
                    break

                if any(g in low for g in garbage_fragments):
                    break

                if value not in categories:
                    value = value.replace(" / ", ", ")
                    categories.append(value)

            if categories:
                return ", ".join(categories)

    return fallback_category

def extract_price_nis(soup):
    """
    Avoid the old bug where shipping/free-delivery text like 99 is captured.
    Prefer price-looking elements/classes and NIS/₪ near the product area.
    """
    candidates = []

    # 1. Prefer elements whose class/id mentions price.
    for tag in soup.find_all(True):
        attrs = " ".join(
            str(v) for k, v in tag.attrs.items()
            if k in {"class", "id", "data-testid", "itemprop"}
        ).lower()

        if "price" not in attrs and "amount" not in attrs:
            continue

        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt:
            continue

        if "₪" in txt or "nis" in txt.lower() or "ils" in txt.lower():
            val = parse_price_from_text(txt)
            if val is not None:
                candidates.append((0, val, txt))

    # 2. Look for text with explicit currency.
    for text_node in soup.find_all(string=True):
        txt = clean_text(text_node)
        if not txt:
            continue

        low = txt.lower()
        if "₪" not in txt and "nis" not in low and "ils" not in low:
            continue

        # Skip obvious shipping/non-product lines.
        skip_words = ["shipping", "delivery", "free", "minimum", "above", "over"]
        if any(w in low for w in skip_words):
            continue

        val = parse_price_from_text(txt)
        if val is not None:
            candidates.append((1, val, txt))

    # 3. Sometimes prices appear without currency in JSON/script near "price".
    html = str(soup)
    for m in re.finditer(r'"price"\s*:\s*"?(\d+(?:[.,]\d{1,2})?)"?', html, re.I):
        val = parse_price_from_text(m.group(1))
        if val is not None:
            candidates.append((2, val, m.group(0)))

    if not candidates:
        return None

    # Filter out suspicious tiny/huge values.
    filtered = [(rank, val, txt) for rank, val, txt in candidates if 5 <= val <= 2000]
    if not filtered:
        filtered = candidates

    # Prefer best-ranked candidate; if there are several, choose the first.
    filtered.sort(key=lambda x: x[0])
    return ceil_2(filtered[0][1])


def parse_price_from_text(text):
    if not text:
        return None

    # Convert Israeli/European decimal comma if used.
    text = text.replace("\xa0", " ")

    matches = re.findall(r"\d+(?:[.,]\d{1,2})?", text)
    if not matches:
        return None

    nums = []
    for m in matches:
        try:
            nums.append(float(m.replace(",", ".")))
        except ValueError:
            pass

    if not nums:
        return None

    # Product price is usually the decimal-looking number if exists.
    decimal_nums = [n for n in nums if not float(n).is_integer()]
    if decimal_nums:
        return decimal_nums[0]

    return nums[0]


def extract_year(soup):
    value = find_field_by_label(soup, ["Publication date", "Published", "Date Published", "Year"])
    search_texts = []

    if value:
        search_texts.append(value)

    search_texts.append(soup.get_text(" ", strip=True))

    for text in search_texts:
        m = re.search(r"\b(19|20)\d{2}\b", text)
        if m:
            return int(m.group(0))

    return None


def extract_synopsis(soup):
    # labels = ["Synopsis", "Description", "Book Description", "Overview", "About the Book"]

    # # Try headings/labels and take the next meaningful block.
    # for tag in soup.find_all(["h2", "h3", "h4", "strong", "b", "div", "span"]):
    #     txt = clean_text(tag.get_text(" ", strip=True))
    #     if not txt:
    #         continue

    #     if any(label.lower() in txt.lower() for label in labels):
    #         for next_el in tag.find_all_next(["p", "div"], limit=8):
    #             val = clean_text(next_el.get_text(" ", strip=True))
    #             if val and len(val) > 40 and not any(label.lower() == val.lower() for label in labels):
    #                 return val

    # # Fallback: meta description.
    # meta = soup.find("meta", attrs={"name": "description"})
    # if meta and meta.get("content"):
    #     return clean_text(meta["content"])

    # return None

    target = soup.find(id="texto-descripcion")
    if target:
        # Cleaning whitespace to get an accurate character count
        text = re.sub(r"\s+", " ", target.get_text(" ", strip=True)).strip()
        return text if text else None
    return None

def extract_reviews_and_rating(soup):
    # text = soup.get_text(" ", strip=True)

    # reviews = 0
    # m = re.search(r"(\d+)\s+(?:customer\s+)?reviews?", text, re.I)
    # if m:
    #     reviews = int(m.group(1))

    # if reviews == 0:
    #     m = re.search(r"NumberOfReviews[^0-9]*(\d+)", str(soup), re.I)
    #     if m:
    #         reviews = int(m.group(1))

    # if reviews == 0:
    #     return "None", 0

    # # Try direct rating like 4.35 out of 5.
    # rating_patterns = [
    #     r"(\d+(?:\.\d+)?)\s*out of\s*5",
    #     r"rating[^0-9]*(\d+(?:\.\d+)?)",
    #     r"starRating[^0-9]*(\d+(?:\.\d+)?)",
    # ]

    # html_text = str(soup)
    # for pat in rating_patterns:
    #     m = re.search(pat, html_text, re.I)
    #     if m:
    #         val = float(m.group(1))
    #         if 0 <= val <= 5:
    #             return ceil_2(val), reviews

    # # Try star distribution: 5 stars: 10, 4 stars: 2, etc.
    # dist = {}
    # all_text = soup.get_text("\n", strip=True)
    # for star, count in re.findall(r"([1-5])\s*stars?.{0,30}?(\d+)", all_text, re.I):
    #     dist[int(star)] = int(count)

    # if dist:
    #     total = sum(dist.values())
    #     if total > 0:
    #         weighted = sum(star * count for star, count in dist.items()) / total
    #         return ceil_2(weighted), reviews

    # return None, reviews

    eval_ul = soup.find('ul', class_='evaluacion')
    if not eval_ul:
        return "None", 0

    dist = {}
    total_reviews = 0
    
    for li in eval_ul.find_all('li'):
        classes = " ".join(li.get('class', []))
        match_star = re.search(r'stars-(\d)', classes)
        if not match_star: continue
        
        star_level = int(match_star.group(1))
        li_text = li.get_text(strip=True)
        match_count = re.search(r'\((\d+)\)', li_text)
        
        if match_count:
            count = int(match_count.group(1))
            dist[star_level] = count
            total_reviews += count

    if total_reviews == 0: return "None", 0

    # Manual Weighted Average: (Sum of Stars * Count) / Total
    weighted_sum = sum(star * count for star, count in dist.items())
    raw_rating = weighted_sum / total_reviews
    return ceil_2(raw_rating), total_reviews


def split_dimensions(value):
    if not value:
        return None, None

    val = value.replace("×", "x").replace("*", "x")
    nums = re.findall(r"\d+(?:[.,]\d+)?", val)
    nums = [n.replace(",", ".") for n in nums]

    unit = None
    low = val.lower()
    if "inch" in low or "inches" in low or re.search(r"\bin\b", low):
        unit = "inch"
    elif "cm" in low:
        unit = "cm"
    elif "mm" in low:
        unit = "mm"

    return (",".join(nums) if nums else None), unit


def split_weight(value):
    if not value:
        return None, None

    m = re.search(r"(\d+(?:[.,]\d+)?)", value)
    number = float(m.group(1).replace(",", ".")) if m else None

    low = value.lower()
    unit = None
    if "kg" in low:
        unit = "kg"
    elif "gram" in low or re.search(r"\bg\b", low):
        unit = "g"
    elif "pound" in low or "lb" in low:
        unit = "lb"
    elif "ounce" in low or "oz" in low:
        unit = "oz"

    return number, unit


def extract_isbn(soup, book_url):
    isbn = find_field_by_label(soup, ["ISBN", "ISBN13", "ISBN-13", "ISBN10", "ISBN-10"])

    if isbn:
        m = re.search(r"(97[89]\d{10}|\d{9}[\dXx])", isbn.replace("-", ""))
        if m:
            return m.group(1)

    # URL often contains ISBN.
    m = re.search(r"/(97[89]\d{10}|\d{9}[\dXx])/", book_url)
    if m:
        return m.group(1)

    return isbn


def extract_book_data(session, driver, book_url, category_name):
    print("Opening book:", book_url)

    try:
        html = fetch_html(
            session,
            driver,
            book_url,
            validator=looks_like_book_page,
            allow_manual_refresh=True,
        )
    except:
        print("Requests blocked → switching to Selenium")

        driver.get(book_url)
        time.sleep(5)
        html = driver.page_source

    if is_bad_html(html):
        print("Bad HTML → switching to Selenium")

        driver.get(book_url)
        time.sleep(5)
        html = driver.page_source

    soup = soup_from_html(html)
    soup = clean_soup_for_parsing(soup)

    title, authors = extract_title_and_authors(soup)
    categories = extract_categories(soup, category_name)

    price_nis = extract_price_nis(soup)
    price_usd = ceil_2(price_nis / EXCHANGE_RATE) if price_nis is not None else None

    year = extract_year(soup)
    synopsis = extract_synopsis(soup)
    synopsis_length = len(synopsis) if synopsis else 0

    star_rating, reviews = extract_reviews_and_rating(soup)

    language = find_field_by_label(soup, ["Language"])
    book_format = find_field_by_label(soup, ["Format", "Binding", "Product format"])

    dim_raw = find_field_by_label(soup, ["Dimensions"])
    dimensions, dimensions_unit = split_dimensions(dim_raw)

    weight_raw = find_field_by_label(soup, ["Weight"])
    weight, weight_unit = split_weight(weight_raw)

    isbn = extract_isbn(soup, book_url)

    if not title or title.lower() == "javascript is disabled":
        raise RuntimeError(f"Invalid title extracted from {book_url}: {title}")

    return {
        "url": book_url,
        "Title": title,
        "Category": category_name,
        "Categories": categories,
        "Authors": authors,
        "Price in NIS": price_nis,
        "Price in USD": price_usd,
        "Year": year,
        "Synopsis": synopsis,
        "Synopsis length": synopsis_length,
        "StarRating": star_rating,
        "NumberOfReviews": reviews,
        "Language": language,
        "Format": book_format,
        "Dimensions": dimensions,
        "Dimensions unit": dimensions_unit,
        "Weight": weight,
        "Weight unit": weight_unit,
        "ISBN/ISBN13": isbn,
    }


# -----------------------------
# Saving outputs
# -----------------------------

def save_json_records(df, path):
    records = []

    for i, row in df.iterrows():
        record = {
            "id": str(i + 1),
            "url": row.get("url"),
        }

        for col, val in row.items():
            if col == "url":
                continue

            if pd.isna(val):
                continue

            if isinstance(val, (np.integer,)):
                val = int(val)
            elif isinstance(val, (np.floating,)):
                val = float(val)

            record[col] = val

        records.append(record)

    data = {"records": {"record": records}}

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_numeric_casts(df_books):
    numeric_columns = [
        "Price in NIS",
        "Price in USD",
        "Year",
        "Synopsis length",
        "NumberOfReviews",
        "Weight",
    ]

    for col in numeric_columns:
        if col in df_books.columns:
            df_books[col] = pd.to_numeric(df_books[col], errors="coerce")

    # StarRating can be "None", so create numeric only for stats later if needed.
    return df_books

def create_new_features(file_location):
    df = pd.read_csv(file_location)

    prices_list = df["Price in NIS"].dropna().to_list()
    median_calc = statistics.median(prices_list)

    df["IsExpensive"] = np.where(df["Price in NIS"] > median_calc, 1, 0)

    df["NumberOfAuthors"] = (
        df["Authors"]
        .fillna("")
        .apply(lambda x: len([a for a in str(x).split(",") if a.strip()]))
    )

    return df



def summarised_statistics(df):
    record = df.to_dict(orient="records")

    summary = {
        "Statistic": ["Mean", "Standard Deviation", "Min", "Max", "Median", "Total Rows"],

        "Price in USD": [
            calculate_mean("Price in USD", record),
            calculate_stdev("Price in USD", record),
            find_min("Price in USD", record),
            find_max("Price in USD", record),
            calculate_median("Price in USD", record),
            num_of_rows("Price in USD", record),
        ],

        "Year": [
            calculate_mean("Year", record),
            calculate_stdev("Year", record),
            find_min("Year", record),
            find_max("Year", record),
            calculate_median("Year", record),
            num_of_rows("Year", record),
        ],

        "StarRating": [
            calculate_mean("StarRating", record),
            calculate_stdev("StarRating", record),
            find_min("StarRating", record),
            find_max("StarRating", record),
            calculate_median("StarRating", record),
            num_of_rows("StarRating", record),
        ],

        "NumberOfReviews": [
            calculate_mean("NumberOfReviews", record),
            calculate_stdev("NumberOfReviews", record),
            find_min("NumberOfReviews", record),
            find_max("NumberOfReviews", record),
            calculate_median("NumberOfReviews", record),
            num_of_rows("NumberOfReviews", record),
        ],

        "NumberOfAuthors": [
            calculate_mean("NumberOfAuthors", record),
            calculate_stdev("NumberOfAuthors", record),
            find_min("NumberOfAuthors", record),
            find_max("NumberOfAuthors", record),
            calculate_median("NumberOfAuthors", record),
            num_of_rows("NumberOfAuthors", record),
        ],
    }

    summary_df = pd.DataFrame(summary)
    summary_df.to_csv("output/books_summary.csv", index=False, encoding="utf-8-sig")
    print("books_summary.csv created")

def save_outputs(df_books, driver):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    df_books = add_numeric_casts(df_books)

    # Step 2 raw outputs
    raw_csv = os.path.join(OUTPUT_DIR, "books_raw.csv")
    raw_json = os.path.join(OUTPUT_DIR, "books_raw.json")

    df_books.to_csv(raw_csv, index=False, encoding="utf-8-sig")
    save_json_records(df_books, raw_json)

    # Example JSON + screenshot
    save_json_records(df_books.head(1), os.path.join(OUTPUT_DIR, "books_example.json"))

    if len(df_books) > 0:
        example_url = df_books.iloc[0]["url"]
        driver.get(example_url)
        time.sleep(3)
        driver.save_screenshot(os.path.join(OUTPUT_DIR, "books_example.jpg"))

    # Step 3 preview before/after sort
    before_sort = df_books.head(10)
    before_sort.to_csv(
        os.path.join(OUTPUT_DIR, "books_before_sort.csv"),
        index=False,
        encoding="utf-8-sig",
    )

    after_sort = df_books.sort_values(by="Title", ascending=True).head(10)
    after_sort.to_csv(
        os.path.join(OUTPUT_DIR, "books_after_sort.csv"),
        index=False,
        encoding="utf-8-sig",
    )

    print("\n========== FIRST 10 BEFORE SORT ==========")
    print(before_sort)

    print("\n========== FIRST 10 AFTER SORT ==========")
    print(after_sort)

    # Step 4 processed outputs
    processed = create_new_features(os.path.join(OUTPUT_DIR, "books_raw.csv"))
    processed.to_csv(
        os.path.join(OUTPUT_DIR, "books_processed.csv"),
        index=False,
        encoding="utf-8-sig",
    )

    save_json_records(
        processed,
        os.path.join(OUTPUT_DIR, "books_processed.json"),
    )

    processed_preview = processed.head(10)
    processed_preview.to_csv(
        os.path.join(OUTPUT_DIR, "books_processed_preview.csv"),
        index=False,
        encoding="utf-8-sig",
    )

    print("\n========== FIRST 10 AFTER PROCESSING ==========")
    print(processed_preview)

    # Step 5 summary
    summarised_statistics(processed)


# -----------------------------
# Main
# -----------------------------

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    driver = make_driver()
    session = make_session()

    all_books = []
    seen_books = set()

    try:
        initial_verification(driver, session)

        categories = extract_category_links(session, driver)

        if not categories:
            print("No categories found. Stopping.")
            return

        test_category = list(categories.items())[:1]
        for category_name, category_url in test_category:
            print(f"\n\n========== CATEGORY: {category_name} ==========")
            refresh_cookies_with_selenium(driver, session, category_url)

            for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
                page_url = build_category_page_url(category_url, page_num)

                try:
                    book_links = extract_book_links_from_category_page(session, driver, page_url)
                except Exception as e:
                    print("\nCould not get a valid category page.")
                    print("Category:", category_name)
                    print("Page:", page_num)
                    print("Error:", e)
                    print("Stopping this category.")
                    break

                if not book_links:
                    print("No book links found. Stopping this category.")
                    break

                for book_url in book_links:
                    if book_url in seen_books:
                        continue

                    # Mark as seen only after successful collection? 
                    # Here we mark before, but failures retry manually and should not skip.
                    seen_books.add(book_url)

                    while True:
                        try:
                            book_data = extract_book_data(session, driver, book_url, category_name)
                            all_books.append(book_data)
                            print(f"Collected: book: {book_data['Title']}, with categories: {book_data['Categories']}, Authors: {book_data['Authors']} and price : {book_data['Price in NIS']}")
                            print("---------------------------------------------------------------------------------------------------------------------")
                            break

                        except Exception as e:
                            print("\nFailed to parse the current book, but NOT skipping it.")
                            print("URL:", book_url)
                            print("Error:", e)
                            print("Options:")
                            print("1. Press ENTER to refresh cookies with Selenium and retry this same book.")
                            print("2. Type STOP to stop the whole run safely and save what was collected.")
                            choice = input("> ").strip().lower()

                            if choice == "stop":
                                raise KeyboardInterrupt

                            refresh_cookies_with_selenium(driver, session, book_url)
                           

        if not all_books:
            print("No books collected. Stopping before output.")
            return

    except KeyboardInterrupt:
        print("\nStopped by user. Saving collected data so far...")

    finally:
        if all_books:
            df_books = pd.DataFrame(all_books)
            save_outputs(df_books, driver)
            print("\nDone. Files saved in output/")
        else:
            print("\nNo data to save.")

        driver.quit()


if __name__ == "__main__":
    main()
