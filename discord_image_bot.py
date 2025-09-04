import requests
from bs4 import BeautifulSoup
import time
import io
import os

# --- CONFIGURATION FROM ENVIRONMENT ---
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Discord webhook URL from GitHub Actions secret
SCRAPE_URL = os.getenv("SCRAPE_URL")    # Target URL set via env variable
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 5))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))
DELAY_BETWEEN_BATCHES = int(os.getenv("DELAY_BETWEEN_BATCHES", 30))

# --- STATE ---
image_queue = []  # Queue of images to send
sent_images = set()  # Track images already sent to avoid duplicates

# --- SCRAPE FUNCTION ---
def scrape_images():
    try:
        print(f"Scraping images from: {SCRAPE_URL}")
        response = requests.get(SCRAPE_URL, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        found_images = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if src and src not in sent_images:
                found_images.append(src)

        return found_images
    except Exception as e:
        print(f"Scraping error: {e}")
        return []

# --- SEND TO DISCORD ---
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
            response = requests.post(WEBHOOK_URL, files=files, data={"content": "New image batch:"})
            if response.status_code == 204:
                print(f"Successfully sent {len(files)} images to Discord.")
            else:
                print(f"Failed to send images: {response.status_code} {response.text}")
        except Exception as e:
            print(f"Webhook error: {e}")

# --- MAIN LOOP ---
def run():
    global image_queue

    if not WEBHOOK_URL:
        raise ValueError("WEBHOOK_URL environment variable is not set!")
    if not SCRAPE_URL:
        raise ValueError("SCRAPE_URL environment variable is not set!")

    print("Starting continuous image scraper...")
    while True:
        # Scrape for new images
        new_images = scrape_images()
        if new_images:
            image_queue.extend(new_images)
            print(f"Added {len(new_images)} new images to the queue.")

        # Process every image in the queue
        while image_queue:
            batch = [image_queue.pop(0) for _ in range(min(BATCH_SIZE, len(image_queue)))]
            sent_images.update(batch)
            send_images(batch)
            print(f"Waiting {DELAY_BETWEEN_BATCHES} seconds before next batch...")
            time.sleep(DELAY_BETWEEN_BATCHES)

        # Wait before scraping again
        print(f"Waiting {CHECK_INTERVAL} seconds before next scrape...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    run()
