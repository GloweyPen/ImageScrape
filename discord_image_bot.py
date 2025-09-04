import requests
from bs4 import BeautifulSoup
import time
import io
import os
import sys
from urllib.parse import urljoin

# --- CONFIGURATION FROM ENVIRONMENT ---
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SCRAPE_URL = os.getenv("SCRAPE_URL")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 5))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))
DELAY_BETWEEN_BATCHES = int(os.getenv("DELAY_BETWEEN_BATCHES", 30))

# --- STATE ---
sent_images = set()  # Track already-sent images to avoid duplicates

# --- LOGGING HELPER ---
def debug(message):
    """Print debug messages with timestamps."""
    print(f"[DEBUG] {time.strftime('%Y-%m-%d %H:%M:%S')} - {message}", flush=True)

# --- SCRAPE AND SEND FUNCTION ---
def scrape_and_send():
    debug(f"Starting scrape of: {SCRAPE_URL}")
    try:
        # Fetch HTML
        response = requests.get(SCRAPE_URL, timeout=10)
        debug(f"HTTP GET {SCRAPE_URL} -> Status {response.status_code}")
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract image URLs
        new_images = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if src:
                # Convert relative URLs to absolute
                full_url = urljoin(SCRAPE_URL, src)
                if full_url not in sent_images:
                    new_images.append(full_url)

        debug(f"Found {len(new_images)} new image(s).")
        if not new_images:
            return

        # Send images immediately as they are discovered
        for i in range(0, len(new_images), BATCH_SIZE):
            batch = new_images[i:i + BATCH_SIZE]
            debug(f"Preparing to send batch of {len(batch)} image(s).")
            send_images(batch)
            sent_images.update(batch)
            debug(f"Batch sent successfully. Sleeping {DELAY_BETWEEN_BATCHES} seconds before next batch...")
            time.sleep(DELAY_BETWEEN_BATCHES)

    except Exception as e:
        debug(f"Error scraping or sending images: {e}")
        sys.stderr.write(f"[ERROR] {str(e)}\n")

# --- DISCORD SENDER ---
def send_images(batch):
    debug("Starting to download images for Discord batch send...")
    files = []

    for url in batch:
        try:
            debug(f"Downloading image: {url}")
            img_response = requests.get(url, stream=True, timeout=10)
            debug(f"Image GET {url} -> Status {img_response.status_code}")
            img_response.raise_for_status()
            files.append((
                "file",
                (url.split("/")[-1] or "image.png", io.BytesIO(img_response.content), "image/png")
            ))
        except Exception as e:
            debug(f"Failed to download image {url}: {e}")

    if not files:
        debug("No images downloaded successfully. Skipping Discord send.")
        return

    try:
        debug(f"Sending {len(files)} file(s) to Discord webhook: {WEBHOOK_URL}")
        response = requests.post(
            WEBHOOK_URL,
            files=files,
            data={"content": f"New batch of {len(files)} image(s)!"}
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
