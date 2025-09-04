import requests
from bs4 import BeautifulSoup
import time
import os
from urllib.parse import urljoin

# --- CONFIGURATION FROM ENVIRONMENT ---
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SCRAPE_URL = os.getenv("SCRAPE_URL")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 5))
DELAY_BETWEEN_BATCHES = int(os.getenv("DELAY_BETWEEN_BATCHES", 10))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 20))

# --- HEADERS TO MIMIC WINDOWS CHROME ---
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": SCRAPE_URL,
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0"
}

# --- STATE ---
sent_images = set()
image_queue = []
page_number = 0  # page counter for pagination

# --- LOGGING ---
def debug(message):
    print(f"[DEBUG] {time.strftime('%Y-%m-%d %H:%M:%S')} - {message}", flush=True)

# --- SCRAPE NEW IMAGES ---
def scrape_new_images():
    global page_number
    # Calculate page offset
    page_offset = page_number * 42
    if page_offset == 0:
        url = SCRAPE_URL
    else:
        url = f"{SCRAPE_URL}+&pid={page_offset}"

    debug(f"Scraping page {page_number + 1}: {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        debug(f"HTTP GET {url} -> Status {response.status_code}")
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        new_images = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue

            full_url = urljoin(SCRAPE_URL, src)
            if full_url not in sent_images and full_url not in image_queue:
                new_images.append(full_url)

        if new_images:
            debug(f"Found {len(new_images)} new image(s) on page {page_number + 1}.")
            image_queue.extend(new_images)
            page_number = 0  # reset pagination after finding new images
        else:
            debug(f"No new images found on page {page_number + 1}. Moving to next page...")
            page_number += 1

    except Exception as e:
        debug(f"Error scraping images: {e}")

# --- SEND LINKS IN BATCH ---
def send_links(batch):
    content = "\n".join(batch)
    try:
        debug(f"Sending batch of {len(batch)} links to Discord webhook: {WEBHOOK_URL}")
        response = requests.post(WEBHOOK_URL, data={"content": content})
        debug(f"Discord POST response status: {response.status_code}")
        if response.status_code == 204:
            debug("Discord acknowledged the upload successfully.")
        else:
            debug(f"Discord responded with error: {response.status_code} {response.text}")
    except Exception as e:
        debug(f"Webhook send error: {e}")

# --- MAIN LOOP ---
def run():
    if not WEBHOOK_URL:
        raise ValueError("WEBHOOK_URL environment variable is not set!")
    if not SCRAPE_URL:
        raise ValueError("SCRAPE_URL environment variable is not set!")

    debug("Starting continuous scraper and sender...")
    while True:
        # Step 1: Scrape new images if queue is empty
        if not image_queue:
            scrape_new_images()
            if not image_queue:
                debug(f"No new images in queue. Waiting {CHECK_INTERVAL}s before next scrape...")
                time.sleep(CHECK_INTERVAL)
                continue

        # Step 2: Send batches from queue
        while image_queue:
            batch = [image_queue.pop(0) for _ in range(min(BATCH_SIZE, len(image_queue)))]
            send_links(batch)
            sent_images.update(batch)
            debug(f"Batch sent. Waiting {DELAY_BETWEEN_BATCHES}s before next batch...")
            time.sleep(DELAY_BETWEEN_BATCHES)

if __name__ == "__main__":
    run()
