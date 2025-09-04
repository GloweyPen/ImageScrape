# discord_image_bot.py
import os
import asyncio
import time
import requests
import discord
from discord.ext import commands, tasks
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# --- CONFIGURATION FROM ENVIRONMENT (CHANNEL_ID optional) ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
# Parse CHANNEL_ID if present and numeric, otherwise None
_ch = os.getenv("CHANNEL_ID")
try:
    ENV_CHANNEL_ID = int(_ch) if _ch and _ch.strip() != "" else None
except Exception:
    ENV_CHANNEL_ID = None

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
sent_images = set()
image_queue = []
page_number = 0
TARGET_CHANNEL_ID = None  # set by /cookie command (or fallback to ENV_CHANNEL_ID)

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
            page_number = 0
        else:
            debug(f"No new images on page {page_number + 1}. Advancing page.")
            page_number += 1

    except Exception as e:
        debug(f"Error scraping images: {e}")

# --- BOT SETUP ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- HELPER: resolve channel by id (cache then fetch) ---
async def get_channel_by_id(channel_id):
    if channel_id is None:
        return None
    ch = bot.get_channel(channel_id)
    if ch is None:
        try:
            ch = await bot.fetch_channel(channel_id)
        except Exception as e:
            debug(f"Failed to fetch channel {channel_id}: {e}")
            return None
    return ch

# --- BACKGROUND TASK: sends batches to TARGET_CHANNEL_ID (or ENV fallback) ---
@tasks.loop(seconds=1.0)
async def continuous_scrape_and_send():
    global TARGET_CHANNEL_ID

    # determine current effective target
    effective_target = TARGET_CHANNEL_ID or ENV_CHANNEL_ID
    if effective_target is None:
        debug("No target channel set (TARGET_CHANNEL_ID and ENV_CHANNEL_ID are None). Waiting.")
        await asyncio.sleep(CHECK_INTERVAL)
        return

    channel = await get_channel_by_id(effective_target)
    if channel is None:
        debug(f"Target channel {effective_target} could not be resolved.")
        await asyncio.sleep(CHECK_INTERVAL)
        return

    # Step 1: if queue empty -> scrape until queue fills (or advance pages)
    if not image_queue:
        scrape_new_images()
        if not image_queue:
            debug(f"No images found; sleeping {CHECK_INTERVAL}s before next scrape attempt.")
            await asyncio.sleep(CHECK_INTERVAL)
            return

    # Step 2: drain the queue in batches
    while image_queue:
        batch = [image_queue.pop(0) for _ in range(min(BATCH_SIZE, len(image_queue)))]
        content = "\n".join(batch)

        try:
            perms = channel.permissions_for(channel.guild.me) if channel.guild else None
            if perms and not perms.send_messages:
                debug(f"Bot lacks send_messages permission in channel {channel.id}. Stopping loop.")
                return

            await channel.send(content)
            sent_images.update(batch)
            debug(f"Sent batch of {len(batch)} links to channel {channel.id}. Queue size: {len(image_queue)}")
        except Exception as e:
            debug(f"Failed to send batch to channel {channel.id}: {e}")
            image_queue[0:0] = batch  # push back for retry later
            await asyncio.sleep(CHECK_INTERVAL)
            return

        debug(f"Waiting {DELAY_BETWEEN_BATCHES}s before next batch.")
        await asyncio.sleep(DELAY_BETWEEN_BATCHES)

# --- SLASH COMMANDS (global) ---
@bot.tree.command(name="cookie", description="Start scraping and sending image links to a channel.")
async def cookie_command(interaction: discord.Interaction, channel: discord.TextChannel = None):
    """
    /cookie [channel] - start continuous scraping/sending to 'channel' (or current channel if omitted)
    """
    global TARGET_CHANNEL_ID

    # Determine target in order: explicit arg -> ENV_CHANNEL_ID -> interaction.channel
    target_channel_obj = channel
    if target_channel_obj is None:
        if ENV_CHANNEL_ID:
            target_channel_obj = await get_channel_by_id(ENV_CHANNEL_ID)
        else:
            target_channel_obj = interaction.channel

    if target_channel_obj is None:
        await interaction.response.send_message("❌ Could not determine a channel to send to.", ephemeral=True)
        return

    # permission check
    perms = target_channel_obj.permissions_for(target_channel_obj.guild.me) if target_channel_obj.guild else None
    if perms is not None and not perms.send_messages:
        await interaction.response.send_message(f"❌ I don't have permission to send messages in {target_channel_obj.mention}.", ephemeral=True)
        return

    TARGET_CHANNEL_ID = target_channel_obj.id
    if continuous_scrape_and_send.is_running():
        await interaction.response.send_message(f"🍪 Already running; now targeting {target_channel_obj.mention}.", ephemeral=True)
    else:
        continuous_scrape_and_send.start()
        await interaction.response.send_message(f"🍪 Cookie scraper started; sending to {target_channel_obj.mention}.", ephemeral=True)

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
    tgt_id = TARGET_CHANNEL_ID or ENV_CHANNEL_ID
    tgt_mention = f"<#{tgt_id}>" if tgt_id else "None"
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
