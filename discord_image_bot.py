import requests
from bs4 import BeautifulSoup
import time
import os
import sys
from urllib.parse import urljoin

# --- CONFIGURATION FROM ENVIRONMENT ---
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SCRAPE_URL = os.getenv("SCRAPE_URL")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 5))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))
DELAY_BETWEEN_BATCHES = int(os.getenv("DELAY_BETWEEN_BATCHES", 30))

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
sent_images = set()  # Track already-sent images to avoid duplicates

# --- LOGGING HELPER ---
def debug(message):
    print(f"[DEBUG] {time.strftime('%Y-%m-%d %H:%M:%S')} - {message}", flush=True)

# --- SCRAPE AND SEND FUNCTION ---
def scrape_and_send():
    debug(f"Starting scrape of: {SCRAPE_URL}")
    try:
        # Fetch HTML
        response = requests.get(SCRAPE_URL, headers=HEADERS, timeout=10)
        debug(f"HTTP GET {SCRAPE_URL} -> Status {response.status_code}")
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract image URLs
        new_images = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if src:
                # Skip thumbnails
                if src.split("/")[-1].lower().startswith("thumbnail_"):
                    debug(f"Skipping thumbnail image: {src}")
                    continue

                full_url = urljoin(SCRAPE_URL, src)
                if full_url not in sent_images:
                    new_images.append(full_url)

        debug(f"Found {len(new_images)} new image(s) after skipping thumbnails.")
        if not new_images:
            return

        # Send URLs in batches
        for i in range(0, len(new_images), BATCH_SIZE):
            batch = new_images[i:i + BATCH_SIZE]
            debug(f"Preparing to send batch of {len(batch)} links.")
            send_links(batch)
            sent_images.update(batch)
            debug(f"Batch sent successfully. Sleeping {DELAY_BETWEEN_BATCHES}s before next batch...")
            time.sleep(DELAY_BETWEEN_BATCHES)

    except Exception as e:
        debug(f"Error scraping or sending images: {e}")
        sys.stderr.write(f"[ERROR] {str(e)}\n")

# --- DISCORD SENDER (Links Only) ---
def send_links(batch):
    content = "\n".join(batch)
    try:
        debug(f"Sending batch of {len(batch)} links to Discord webhook: {WEBHOOK_URL}")
        response = requests.post(
            WEBHOOK_URL,
            data={"content": content}
        )
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
    debug(f"SCRAPE_URL: {SCRAPE_URL}")
    debug(f"BATCH_SIZE: {BATCH_SIZE}")
    debug(f"CHECK_INTERVAL: {CHECK_INTERVAL}")
    debug(f"DELAY_BETWEEN_BATCHES: {DELAY_BETWEEN_BATCHES}")

    while True:
        scrape_and_send()
        debug(f"Waiting {CHECK_INTERVAL} seconds before next scrape...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    run()
