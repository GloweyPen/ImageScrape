# discord_image_bot.py
import os
import asyncio
import time
import requests
import discord
from discord.ext import commands, tasks
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# --- CONFIGURATION FROM ENVIRONMENT ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ENV_CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))  # optional fallback
SCRAPE_URL = os.getenv("SCRAPE_URL")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 5))
DELAY_BETWEEN_BATCHES = int(os.getenv("DELAY_BETWEEN_BATCHES", 30))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))

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
}

# --- STATE ---
sent_images = set()   # URLs already sent
image_queue = []      # queued URLs to send
page_number = 0       # pagination counter (0 = base)
TARGET_CHANNEL_ID = None  # set when /cookie is invoked

# --- LOGGING ---
def debug(message):
    print(f"[DEBUG] {time.strftime('%Y-%m-%d %H:%M:%S')} - {message}", flush=True)

# --- SCRAPER (uses +&pid=42 pagination) ---
def scrape_new_images():
    global page_number
    offset = page_number * 42
    url = SCRAPE_URL if offset == 0 else f"{SCRAPE_URL}+&pid={offset}"

    debug(f"Scraping page {page_number + 1}: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        debug(f"HTTP GET {url} -> Status {r.status_code}")
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        new_images = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue
            full_url = urljoin(SCRAPE_URL, src)
            if full_url not in sent_images and full_url not in image_queue:
                new_images.append(full_url)

        if new_images:
            debug(f"Found {len(new_images)} new images on page {page_number + 1}.")
            image_queue.extend(new_images)
            page_number = 0  # reset to start after finding new images
        else:
            debug(f"No new images on page {page_number + 1}. Advancing page.")
            page_number += 1

    except Exception as e:
        debug(f"Error scraping images: {e}")

# --- BOT SETUP ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- HELPER: resolve channel object from id (tries cache then fetch) ---
async def get_channel_by_id(channel_id):
    ch = bot.get_channel(channel_id)
    if ch is None:
        try:
            ch = await bot.fetch_channel(channel_id)
        except Exception as e:
            debug(f"Failed to fetch channel {channel_id}: {e}")
            return None
    return ch

# --- BACKGROUND TASK: sends batches to TARGET_CHANNEL_ID ---
@tasks.loop(seconds=1.0)
async def continuous_scrape_and_send():
    global TARGET_CHANNEL_ID
    if TARGET_CHANNEL_ID is None:
        debug("No target channel set; waiting.")
        await asyncio.sleep(CHECK_INTERVAL)
        return

    # resolve channel
    channel = await get_channel_by_id(TARGET_CHANNEL_ID)
    if channel is None:
        debug(f"Target channel {TARGET_CHANNEL_ID} could not be resolved.")
        await asyncio.sleep(CHECK_INTERVAL)
        return

    # Step 1: if queue empty -> scrape until queue fills or we've tried pages
    if not image_queue:
        scrape_new_images()
        if not image_queue:
            debug(f"No images found; sleeping {CHECK_INTERVAL}s before next scrape attempt.")
            await asyncio.sleep(CHECK_INTERVAL)
            return

    # Step 2: drain the queue in batches until empty
    while image_queue:
        # build batch
        batch = [image_queue.pop(0) for _ in range(min(BATCH_SIZE, len(image_queue)))]
        content = "\n".join(batch)

        # attempt to send
        try:
            # check send permissions quickly
            perms = channel.permissions_for(channel.guild.me) if channel.guild else None
            if perms and not perms.send_messages:
                debug(f"Bot lacks send_messages permission in channel {channel.id}. Stopping.")
                return

            await channel.send(content)
            sent_images.update(batch)
            debug(f"Sent batch of {len(batch)} links to channel {channel.id}. Queue size now: {len(image_queue)}")
        except Exception as e:
            debug(f"Failed to send batch to channel {channel.id}: {e}")
            # If sending fails, push batch back onto front of queue to retry later
            image_queue[0:0] = batch
            await asyncio.sleep(CHECK_INTERVAL)
            return

        # wait between batches
        debug(f"Waiting {DELAY_BETWEEN_BATCHES}s before next batch.")
        await asyncio.sleep(DELAY_BETWEEN_BATCHES)

# --- SLASH COMMANDS (global) ---
@bot.tree.command(name="cookie", description="Start scraping and sending image links to a channel.")
async def cookie_command(interaction: discord.Interaction, channel: discord.TextChannel = None):
    """
    /cookie [channel] - start continuous scraping/sending to 'channel' (or current channel if omitted)
    """
    global TARGET_CHANNEL_ID

    # choose channel: explicit param -> env fallback -> interaction.channel
    target = channel or (await get_channel_by_id(ENV_CHANNEL_ID) if ENV_CHANNEL_ID else interaction.channel)
    if target is None:
        await interaction.response.send_message("❌ Could not determine a channel to send to.", ephemeral=True)
        return

    # permissions check: attempt to send a simple ephemeral test (or check perms)
    perms = target.permissions_for(target.guild.me) if target.guild else None
    if perms is not None and not perms.send_messages:
        await interaction.response.send_message(f"❌ I don't have permission to send messages in {target.mention}.", ephemeral=True)
        return

    TARGET_CHANNEL_ID = target.id
    if continuous_scrape_and_send.is_running():
        await interaction.response.send_message(f"🍪 Already running; now targeting {target.mention}.", ephemeral=True)
    else:
        continuous_scrape_and_send.start()
        await interaction.response.send_message(f"🍪 Cookie scraper started; sending to {target.mention}.", ephemeral=True)

@bot.tree.command(name="stop", description="Stop the cookie scraper.")
async def stop_command(interaction: discord.Interaction):
    global TARGET_CHANNEL_ID
    if continuous_scrape_and_send.is_running():
        continuous_scrape_and_send.stop()
        TARGET_CHANNEL_ID = None
        await interaction.response.send_message("🛑 Cookie scraper stopped.", ephemeral=True)
    else:
        await interaction.response.send_message("The scraper is not running.", ephemeral=True)

@bot.tree.command(name="status", description="Show cookie scraper status.")
async def status_command(interaction: discord.Interaction):
    queue_size = len(image_queue)
    sent_count = len(sent_images)
    running = continuous_scrape_and_send.is_running()
    tgt = TARGET_CHANNEL_ID or ENV_CHANNEL_ID or "None"
    tgt_mention = f"<#{tgt}>" if isinstance(tgt, int) else str(tgt)
    await interaction.response.send_message(
        f"**Cookie Scraper Status**\n"
        f"- Running: {running}\n"
        f"- Queue size: {queue_size}\n"
        f"- Total sent: {sent_count}\n"
        f"- Current page: {page_number + 1}\n"
        f"- Target channel: {tgt_mention}",
        ephemeral=True
    )

# --- EVENTS ---
@bot.event
async def on_ready():
    debug(f"Bot ready: {bot.user} (id: {bot.user.id})")
    # sync global commands (may take up to 1 hour to appear globally on first publish;
    # for immediate testing you can sync to a specific guild instead)
    try:
        await bot.tree.sync()
        debug("Slash commands synced (global).")
    except Exception as e:
        debug(f"Error syncing commands: {e}")

# --- RUN ---
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN environment variable is not set!")
    if not SCRAPE_URL:
        raise ValueError("SCRAPE_URL environment variable is not set!")

    debug("Starting bot...")
    bot.run(DISCORD_TOKEN)
