import requests
from bs4 import BeautifulSoup
import time
import io
import os

# --- CONFIGURATION FROM ENVIRONMENT ---
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Discord webhook URL from GitHub Actions secret
SCRAPE_URL = os.getenv("SCRAPE_URL")    # Target URL to scrape
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 5))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))  # How often to re-check the site
DELAY_BETWEEN_BATCHES = int(os.getenv("DELAY_BETWEEN_BATCHES", 30))  # Delay between sends

# --- STATE ---
sent_images = set()  # Track already-sent images to avoid duplicates

# --- SCRAPE AND SEND FUNCTION ---
def scrape_and_send():
    try:
        print(f"Scraping images from: {SCRAPE_URL}")
        response = requests.get(SCRAPE_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract image URLs
        new_images = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if src and src not in sent_images:
                new_images.append(src)

        if not new_images:
            print("No new images found.")
            return

        print(f"Found {len(new_images)} new images. Sending now...")

        # Send images in real-time, as they are discovered
        for i in range(0, len(new_images), BATCH_SIZE):
            batch = new_images[i:i + BATCH_SIZE]
            send_images(batch)
            sent_images.update(batch)
            print(f"Sent batch of {len(batch)} images. Waiting {DELAY_BETWEEN_BATCHES}s before next batch...")
            time.sleep(DELAY_BETWEEN_BATCHES)

    except Exception as e:
        print(f"Error scraping or sending images: {e}")

# --- DISCORD SENDER ---
def send_images(batch):
    files = []
    for url in batch:
        try:
            print(f"Downloading image: {url}")
            img_data = requests.get(url, stream=True).content
            files.append(("file", (url.split("/")[-1], io.BytesIO(img_data), "image/png")))
        except Exception as e:
            print(f"Failed to download image {url}: {e}")

    if files:
        try:
            response = requests.post(WEBHOOK_URL, files=files, data={"content": "New images found:"})
            if response.status_code == 204:
                print(f"Successfully sent {len(files)} images to Discord.")
            else:
                print(f"Failed to send images: {response.status_code} {response.text}")
        except Exception as e:
            print(f"Webhook error: {e}")

# --- MAIN LOOP ---
def run():
    if not WEBHOOK_URL:
        raise ValueError("WEBHOOK_URL environment variable is not set!")
    if not SCRAPE_URL:
        raise ValueError("SCRAPE_URL environment variable is not set!")

    print("Starting continuous scraper and sender...")
    while True:
        scrape_and_send()
        print(f"Waiting {CHECK_INTERVAL} seconds before scraping again...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    run()
