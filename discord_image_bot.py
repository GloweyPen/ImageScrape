import os
import asyncio
import time
import requests
import discord
from discord.ext import commands
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SCRAPE_URL = os.getenv("SCRAPE_URL")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 5))
DELAY_BETWEEN_BATCHES = int(os.getenv("DELAY_BETWEEN_BATCHES", 30))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))

# CHANNEL_ID fallback (optional, can be None)
try:
    ENV_CHANNEL_ID = int(os.getenv("CHANNEL_ID")) if os.getenv("CHANNEL_ID") else None
except Exception:
    ENV_CHANNEL_ID = None

# --- HEADERS ---
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
}

# --- STATE ---
active_scrapers = {}  # channel_id -> {queue, sent, page, task}

def debug(msg):
    print(f"[DEBUG] {time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}", flush=True)

# --- SCRAPER ---
def scrape_images_for_channel(channel_id):
    """Scrape new images for a specific channel using its page state."""
    state = active_scrapers[channel_id]
    page_number = state["page"]
    offset = page_number * 42
    url = SCRAPE_URL if offset == 0 else f"{SCRAPE_URL}+&pid={offset}"

    debug(f"[{channel_id}] Scraping page {page_number + 1}: {url}")

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        debug(f"[{channel_id}] HTTP GET -> {r.status_code}")
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        new_images = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue
            full_url = urljoin(SCRAPE_URL, src)
            if full_url not in state["sent"] and full_url not in state["queue"]:
                new_images.append(full_url)

        if new_images:
            debug(f"[{channel_id}] Found {len(new_images)} new images.")
            state["queue"].extend(new_images)
            state["page"] = 0  # reset to first page
        else:
            state["page"] += 1  # advance to next page if none found
            debug(f"[{channel_id}] No new images, moving to page {state['page'] + 1}.")
    except Exception as e:
        debug(f"[{channel_id}] Scraping error: {e}")

# --- BOT SETUP ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- SCRAPER LOOP FOR ONE CHANNEL ---
async def scraper_loop(channel_id):
    """Loop for one channel: scrape, queue, send."""
    debug(f"[{channel_id}] Scraper task started.")
    channel = await bot.fetch_channel(channel_id)

    while channel_id in active_scrapers:
        state = active_scrapers[channel_id]

        # Scrape if queue empty
        if not state["queue"]:
            scrape_images_for_channel(channel_id)
            if not state["queue"]:
                debug(f"[{channel_id}] Queue empty. Sleeping {CHECK_INTERVAL}s.")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

        # Send batches
        batch = [state["queue"].pop(0) for _ in range(min(BATCH_SIZE, len(state["queue"])))]
        content = "\n".join(batch)
        try:
            await channel.send(content)
            state["sent"].update(batch)
            debug(f"[{channel_id}] Sent batch of {len(batch)} links.")
        except Exception as e:
            debug(f"[{channel_id}] Failed to send batch: {e}")
            # return batch to queue
            state["queue"][0:0] = batch

        await asyncio.sleep(DELAY_BETWEEN_BATCHES)

    debug(f"[{channel_id}] Scraper task stopped.")

# --- COMMANDS ---
@bot.tree.command(name="cookie", description="Start scraping and sending images to a channel.")
async def cookie(interaction: discord.Interaction, channel: discord.TextChannel = None):
    """Start a scraper in this or another channel."""
    target = channel or interaction.channel

    if target.id in active_scrapers:
        await interaction.response.send_message(f"🍪 Already running in {target.mention}.", ephemeral=True)
        return

    active_scrapers[target.id] = {
        "queue": [],
        "sent": set(),
        "page": 0,
        "task": asyncio.create_task(scraper_loop(target.id))
    }
    await interaction.response.send_message(f"🍪 Scraper started in {target.mention}.", ephemeral=True)

@bot.tree.command(name="stop", description="Stop a running scraper in a channel.")
async def stop(interaction: discord.Interaction, channel: discord.TextChannel = None):
    """Stop a scraper in a specific channel."""
    target = channel or interaction.channel

    if target.id not in active_scrapers:
        await interaction.response.send_message(f"No scraper running in {target.mention}.", ephemeral=True)
        return

    # Remove and cancel task
    task = active_scrapers[target.id]["task"]
    del active_scrapers[target.id]
    task.cancel()
    await interaction.response.send_message(f"🛑 Scraper stopped in {target.mention}.", ephemeral=True)

@bot.tree.command(name="status", description="Show the status of all scrapers.")
async def status(interaction: discord.Interaction):
    if not active_scrapers:
        await interaction.response.send_message("No active scrapers.", ephemeral=True)
        return

    lines = []
    for cid, state in active_scrapers.items():
        lines.append(
            f"- <#{cid}>: Queue={len(state['queue'])}, Sent={len(state['sent'])}, Page={state['page']+1}"
        )
    await interaction.response.send_message("**Active Scrapers:**\n" + "\n".join(lines), ephemeral=True)

# --- EVENTS ---
@bot.event
async def on_ready():
    debug(f"Bot ready: {bot.user} (id: {bot.user.id})")
    await bot.tree.sync()
    debug("Slash commands synced globally.")

# --- RUN ---
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN env var is required!")
    if not SCRAPE_URL:
        raise ValueError("SCRAPE_URL env var is required!")
    debug("Starting bot...")
    bot.run(DISCORD_TOKEN)
