import os
import re
import json
import time
import math
import pandas as pd
import statistics
import numpy as np
import json

from bs4 import BeautifulSoup
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.options import Options


BASE_URL = "https://www.bookdelivery.com/"
COUNTRY_NAME = "Israel"
MAX_PAGES_PER_CATEGORY = 5
OUTPUT_DIR = "output"
EXCHANGE_RATE = 3.01


def clean_text(text):
    if not text:
        return None
    return re.sub(r"\s+", " ", text).strip()


def ceil_2(x):
    if x is None:
        return None
    return math.ceil(float(x) * 100) / 100


def get_soup(driver):
    return BeautifulSoup(driver.page_source, "html.parser")


def open_israel_site(driver):
    """
    This function is choosing the Israel page according to it's url
    """
    print("Opening site...", flush=True)
    driver.get(BASE_URL)

    print("\nSolve Human Verification manually if needed.")
    input("When the country page is loaded, press ENTER here...")

    soup = get_soup(driver)

    israel_url = None
    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text(" ", strip=True))
        if text == COUNTRY_NAME:
            israel_url = urljoin(BASE_URL, a["href"])
            break

    if not israel_url:
        raise RuntimeError("Could not find Israel link.")

    print("Opening Israel site:", israel_url)
    driver.get(israel_url)
    time.sleep(3)


def extract_category_links(driver):
    """
    This function extracts all the links of the categories
    """
    soup = get_soup(driver)
    categories = {}

    print("\n========== CATEGORY LINKS ==========")

    # Building the url of each category
    for a in soup.find_all("a", href=True):
        text = clean_text(a.get_text(" ", strip=True))
        full_url = urljoin(BASE_URL, a["href"])
        href_lower = full_url.lower()

        if not text:
            continue

        # Real Israel-English category pages:
        # https://www.bookdelivery.com/il-en/books/arts
        if "bookdelivery.com/il-en/books/" in href_lower:
            # avoid sub-subject pages like /subject-...
            if "/subject-" in href_lower:
                continue

            categories[text] = full_url
            print(text, "->", full_url)

    print(f"\nFound {len(categories)} categories.")
    return categories


def build_category_page_url(category_url, page_num):
    """
    This function builds the category page url
    """
    if page_num == 1:
        return category_url

    sep = "&" if "?" in category_url else "?"
    return f"{category_url}{sep}page={page_num}"


def extract_book_links_from_category_page(driver, page_url):
    """
    This function extracts the links of books from the category page
    """
    print("\nOpening category page:", page_url)
    driver.get(page_url)
    time.sleep(3)

    soup = get_soup(driver)
    book_links = set()

    for a in soup.find_all("a", href=True):
        full_url = urljoin(BASE_URL, a["href"])
        href_lower = full_url.lower()

        # Real book pages:
        # /il-en/book-berserk-deluxe-volume-1/9781506711980/p/51598673
        if "/book-" in href_lower and "/p/" in href_lower:
            book_links.add(full_url)

    print("Book links found:", len(book_links))

    for url in list(book_links)[:10]:
        print("BOOK:", url)

    return list(book_links)


def extract_price(text):
    if not text:
        return None

    text = text.replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def find_field_by_label(soup, label):
    lines = [clean_text(x) for x in soup.get_text("\n", strip=True).split("\n")]
    lines = [x for x in lines if x]

    label_lower = label.lower()

    for i, line in enumerate(lines):
        if label_lower == line.lower() or label_lower in line.lower():
            if i + 1 < len(lines):
                return lines[i + 1]

    return None


def extract_book_data(driver, book_url, category_name):
    """
    This function extracts all needed data from the book page
    """
    total_nis = []
    print("Opening book:", book_url)
    driver.get(book_url)
    time.sleep(2)

    soup = get_soup(driver)
    page_text = soup.get_text("\n", strip=True)

    h1 = soup.find("h1")
    title = clean_text(h1.get_text(" ", strip=True)) if h1 else None

    if not title and soup.title:
        title = clean_text(soup.title.get_text(" ", strip=True))

    authors = find_field_by_label(soup, "Author")
    language = find_field_by_label(soup, "Language")
    book_format = find_field_by_label(soup, "Format")
    dimensions = find_field_by_label(soup, "Dimensions")
    weight = find_field_by_label(soup, "Weight")
    isbn = find_field_by_label(soup, "ISBN")

    year = None
    year_match = re.search(r"\b(19|20)\d{2}\b", page_text)
    if year_match:
        year = int(year_match.group(0))

    price_nis = None
    for txt in soup.find_all(string=re.compile(r"(₪|NIS|ILS|\d+\.\d{2})")):
        txt = str(txt)
        if "₪" in txt or "NIS" in txt or "ILS" in txt:
            price_nis = ceil_2(extract_price(txt))
            total_nis.append(price_nis)
            break

    price_usd = ceil_2(price_nis / EXCHANGE_RATE) if price_nis else None

    synopsis = None
    for label in ["Synopsis", "Description", "Book Description"]:
        found = soup.find(string=re.compile(label, re.I))
        if found:
            parent = found.find_parent()
            if parent:
                next_el = parent.find_next()
                if next_el:
                    synopsis = clean_text(next_el.get_text(" ", strip=True))
                    break

    synopsis_length = len(synopsis) if synopsis else 0

    reviews = 0
    review_match = re.search(r"(\d+)\s+reviews?", page_text, re.I)
    if review_match:
        reviews = int(review_match.group(1))

    star_rating = "None" if reviews == 0 else None

    median = statistics.median(total_nis)

    return {
        "url": book_url,
        "Title": title,
        "Category": category_name,
        "Categories": category_name,
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
        "Dimensions unit": None,
        "Weight": weight,
        "Weight unit": None,
        "ISBN/ISBN13": isbn
    }

def create_new_features(file_location):
    df = pd.read_csv(file_location)
    prices_list = df['Price in NIS'].to_list()
    median_calc = statistics.median(prices_list)
    df['IsExpensive'] = np.where(df["Price in NIS"] > median_calc, 1, 0)

    df['NumberOfAuthors'] = df['Authors'].str.split(',').str.len()
    return df



def save_json_records(df, path):
    records = []

    for i, row in df.iterrows():
        record = {
            "id": str(i + 1),
            "url": row.get("url"),
        }

        for col, val in row.items():
            if pd.isna(val):
                continue
            record[col] = val

        records.append(record)

    data = {"records": {"record": records}}

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def summarised_statistics():
    try:
        with open("output/books_processed.json", 'r',encoding='utf-8') as file:
            data = json.load(file)
            records=data["records"]
            record=records["record"]
            summary={
    "Statistic": ["Mean", "Standard Deviation", "Min", "Max", "Median", "Total Rows"],

    "Price in USD": [
        calculate_mean("Price in USD", record),
        calculate_stdev("Price in USD", record),
        find_min("Price in USD", record),
        find_max("Price in USD", record),
        calculate_median("Price in USD", record),
        num_of_rows("Price in USD",record) # Total rows for the whole dataset
    ],

    "Year": [
        calculate_mean("Year", record),
        calculate_stdev("Year", record),
        find_min("Year", record),
        find_max("Year", record),
        calculate_median("Year", record),
        num_of_rows("Year",record)
    ],

    "StarRating": [
        calculate_mean("StarRating", record),
        calculate_stdev("StarRating", record),
        find_min("StarRating", record),
        find_max("StarRating", record),
        calculate_median("StarRating", record),
        num_of_rows("StarRating",record)
    ],

    "NumberOfReviews": [
        calculate_mean("NumberOfReviews", record),
        calculate_stdev("NumberOfReviews", record),
        find_min("NumberOfReviews", record),
        find_max("NumberOfReviews", record),
        calculate_median("NumberOfReviews", record),
        num_of_rows("NumberOfReviews",record)
    ],

    "NumberOfAuthors": [
        calculate_mean("NumberOfAuthors", record),
        calculate_stdev("NumberOfAuthors", record),
        find_min("NumberOfAuthors", record),
        find_max("NumberOfAuthors", record),
        calculate_median("NumberOfAuthors", record),
       num_of_rows("NumberOfAuthors",record)
    ]

        }
        df= pd.DataFrame(summary)
        df.to_csv("output/books_summary.csv", index=False)
        print("books?_summary created")
        
    except FileNotFoundError:
        print("Error: The file 'books_processed.json' was not found.")

def num_of_rows(key,record):
    row_num=0.0
    for book_info in record:
        if(key in book_info and book_info[key] is not None):
            row_num+=1
    return row_num

def find_min(key,record):

    min=None
    for book_info in record:
        if (key in book_info and book_info[key] is not None):
            if (book_info[key] == "None"):
                val=0
            else:
                val=book_info[key]
            if(min is None or val<=min):
                min=val
    return min

def find_max(key,record):
    max =0.0
    for book_info in record:
        if (key in book_info and book_info[key] is not None):
            if (book_info[key] == "None"):
                val=0
            else:
                val=book_info[key]
            if (val>=max):
                max = val
    return max

def calculate_mean(key,record):
      key_val_list=[]
      for book_info in record:
          if (key in book_info and book_info[key] is not None):
            if (book_info[key] == "None"):
                val=0
            else:
                val=book_info[key]
            key_val_list.append(val)
      return statistics.mean(key_val_list)

def calculate_median(key, record):
    key_val_list = []
    for book_info in record:
        if (key in book_info and book_info[key] is not None):
            if (book_info[key] == "None"):
                val=0
            else:
                val=book_info[key]
            key_val_list.append(val)
    return statistics.median(key_val_list)

def calculate_stdev(key, record):
    key_val_list = []
    for book_info in record:
        if (key in book_info and book_info[key] is not None):
            if (book_info[key] == "None"):
                val=0
            else:
                val=book_info[key]
            key_val_list.append(val)
    return statistics.stdev(key_val_list)

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    options = Options()
    options.add_argument("--start-maximized")

    driver = webdriver.Chrome(options=options)

    all_books = []
    seen_books = set()

    try:
        # Step 1
        open_israel_site(driver)

        categories = extract_category_links(driver)

        if not categories:
            print("No categories found. Stop.")
            return

        # Traversing all the categories
        for category_name, category_url in categories.items():
            print(f"\n\n========== CATEGORY: {category_name} ==========")

            for page_num in range(1, MAX_PAGES_PER_CATEGORY + 1):
                page_url = build_category_page_url(category_url, page_num)

                book_links = extract_book_links_from_category_page(driver, page_url)

                if not book_links:
                    print("No book links found, stopping this category.")
                    break

                for book_url in book_links:
                    if book_url in seen_books:
                        continue

                    seen_books.add(book_url)

                    try:
                        book_data = extract_book_data(driver, book_url, category_name)
                        all_books.append(book_data)
                        print("Collected:", book_data["Title"])
                    except Exception as e:
                        print("Failed to parse book:", book_url)
                        print("Error:", e)

                    time.sleep(3)

        if not all_books:
            print("No books collected. Stopping before DataFrame processing.")
            return
    

        # Step 2
        df_books = pd.DataFrame(all_books)

        numeric_columns = [
            "Price in NIS",
            "Price in USD",
            "Year",
            "Synopsis length",
            "NumberOfReviews",
        ]

        for col in numeric_columns:
            df_books[col] = pd.to_numeric(df_books[col], errors="coerce")

        df_books.to_csv(
            os.path.join(OUTPUT_DIR, "books_raw.csv"),
            index=False,
            encoding="utf-8-sig",
        )

        save_json_records(
            df_books,
            os.path.join(OUTPUT_DIR, "books_raw.json"),
        )

        save_json_records(
            df_books.head(1),
            os.path.join(OUTPUT_DIR, "books_example.json"),
        )

        driver.get(df_books.iloc[0]["url"])
        time.sleep(2)
        driver.save_screenshot(os.path.join(OUTPUT_DIR, "books_example.jpg"))

        # Step 3
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

        ## Step 4
        df_n_features = create_new_features("output/books_raw.csv")
        df_n_features.to_csv(os.path.join(OUTPUT_DIR, "books_processed.csv"),
            index=False,
            encoding="utf-8-sig",
        )

        save_json_records(
            df_n_features.head(1),
            os.path.join(OUTPUT_DIR, "books_processed.json"),
        )

        process_ten_rows = df_n_features.head(10)
        print(process_ten_rows)
        process_ten_rows.to_csv(
            os.path.join(OUTPUT_DIR, "books processed preview.csv"),
            index=False,
            encoding="utf-8-sig",
        )
        summarised_statistics()

        print("\nDone. Files saved in output/")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()

