import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer

def run_webserver():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    print(f"🌐 Web server running on port {port}")
    server.serve_forever()

threading.Thread(target=run_webserver, daemon=True).start()
import os
import discord
import random
import asyncio
import shutil
import platform
import subprocess
import imageio_ffmpeg
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import yt_dlp
from collections import deque

# === AUTO-INSTALACJA FFMPEG ===
def ensure_ffmpeg():
    try:
        path = imageio_ffmpeg.get_ffmpeg_exe()
        print(f"✅ Using FFMPEG from imageio-ffmpeg: {path}")
        return path
    except Exception as e:
        print(f"⚠️ Failed to load ffmpeg automatically: {e}")
        return shutil.which("ffmpeg") or "ffmpeg"

# === KONFIGURACJA ===
load_dotenv()
TOKEN = os.getenv("token")
ffmpeg_exe = ensure_ffmpeg()

SONG_QUEUES = {}
CURRENT_SONG = {}
LOOP_MODE = {}
AUTOSHUFFLE = {}

# === POBIERANIE INFORMACJI O UTWORZE ===
async def get_audio_source(query):
    loop = asyncio.get_running_loop()
    ydl_opts_full = {
        "format": "bestaudio/best",
        "quiet": True,
        "noplaylist": True,
        "default_search": "ytsearch",
    }
    full_info = await loop.run_in_executor(
        None, lambda: yt_dlp.YoutubeDL(ydl_opts_full).extract_info(query, download=False)
    )

    if "entries" in full_info:
        full_info = full_info["entries"][0]

    return {
        "url": full_info["url"],
        "title": full_info.get("title", "Unknown Title"),
        "webpage_url": full_info.get("webpage_url", query),
        "thumbnail": full_info.get("thumbnail"),
        "duration": full_info.get("duration"),
    }

# === INICJALIZACJA BOTA ===
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ {bot.user} is online and ready!")
    activity = discord.Activity(type=discord.ActivityType.listening, name="!play <song>")
    await bot.change_presence(status=discord.Status.online, activity=activity)

# === ODTWARZANIE KOLEJNYCH PIOSENEK ===
async def play_next_song(vc, guild_id, channel, message=None):
    guild_loop = LOOP_MODE.get(guild_id, "off")
    guild_autoshuffle = AUTOSHUFFLE.get(guild_id, False)

    if guild_loop == "song" and CURRENT_SONG.get(guild_id):
        info = CURRENT_SONG[guild_id]
    elif SONG_QUEUES.get(guild_id) and SONG_QUEUES[guild_id]:
        if guild_autoshuffle and len(SONG_QUEUES[guild_id]) > 1:
            queue_list = list(SONG_QUEUES[guild_id])
            random.shuffle(queue_list)
            SONG_QUEUES[guild_id] = deque(queue_list)

        query = SONG_QUEUES[guild_id].popleft()
        info = await get_audio_source(query)
        CURRENT_SONG[guild_id] = info

        if guild_loop == "queue":
            SONG_QUEUES[guild_id].append(query)
    else:
        try:
            await vc.disconnect()
        except:
            pass
        SONG_QUEUES[guild_id] = deque()
        CURRENT_SONG[guild_id] = None
        return

    source = discord.PCMVolumeTransformer(
        discord.FFmpegPCMAudio(
            info["url"],
            executable=ffmpeg_exe,
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        ),
        volume=0.5,
    )

    def after_play(error):
        if error:
            print(f"Error playing {info['title']}: {error}")
        asyncio.run_coroutine_threadsafe(
            play_next_song(vc, guild_id, channel), bot.loop
        )

    vc.play(source, after=after_play)

    loop_text = []
    if guild_loop == "song":
        loop_text.append("🔁 Loop: song")
    elif guild_loop == "queue":
        loop_text.append("🔁 Loop: queue")
    if guild_autoshuffle:
        loop_text.append("🔀 Auto-shuffle: ON")

    embed = discord.Embed(
        title="🎶 Now playing:",
        description=f"[{info['title']}]({info['webpage_url']})",
        color=discord.Color.blurple(),
    )
    embed.set_thumbnail(url=info["thumbnail"])
    if loop_text:
        embed.add_field(name="Mode", value=" | ".join(loop_text), inline=False)

    if message:
        await message.edit(content=None, embed=embed)
    else:
        await channel.send(embed=embed)

# === KOMENDA PLAY ===
@bot.tree.command(name="play", description="Odtwórz utwór z YouTube (link lub tytuł)")
async def play(interaction: discord.Interaction, *, query: str):
    await interaction.response.defer(thinking=True)

    voice_state = interaction.user.voice
    if not voice_state or not voice_state.channel:
        await interaction.followup.send("❌ Musisz być na kanale głosowym.")
        return

    channel = voice_state.channel
    vc = interaction.guild.voice_client

    if not vc:
        vc = await channel.connect()

    if interaction.guild.id not in SONG_QUEUES:
        SONG_QUEUES[interaction.guild.id] = deque()

    SONG_QUEUES[interaction.guild.id].append(query)
    await interaction.followup.send(f"🎵 Dodano do kolejki: `{query}`")

    if not vc.is_playing():
        await play_next_song(vc, interaction.guild.id, interaction.channel)

# === KOMENDA PAUSE ===
@bot.tree.command(name="pause", description="Wstrzymaj odtwarzanie")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸️ Wstrzymano muzykę.")
    else:
        await interaction.response.send_message("❌ Nic nie jest odtwarzane.")

# === KOMENDA RESUME ===
@bot.tree.command(name="resume", description="Wznów odtwarzanie")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Wznowiono muzykę.")
    else:
        await interaction.response.send_message("❌ Nic nie jest wstrzymane.")

# === KOMENDA STOP ===
@bot.tree.command(name="stop", description="Zatrzymaj muzykę i opuść kanał")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        await vc.disconnect()
        SONG_QUEUES[interaction.guild.id] = deque()
        CURRENT_SONG[interaction.guild.id] = None
        await interaction.response.send_message("⏹️ Bot zatrzymany i odłączony.")
    else:
        await interaction.response.send_message("❌ Bot nie jest podłączony.")

# === KOMENDA QUEUE ===
@bot.tree.command(name="queue", description="Pokaż kolejkę utworów")
async def queue(interaction: discord.Interaction):
    queue = SONG_QUEUES.get(interaction.guild.id, deque())
    if not queue:
        await interaction.response.send_message("🎵 Kolejka jest pusta.")
        return

    desc = "\n".join([f"{i+1}. {song}" for i, song in enumerate(queue)])
    embed = discord.Embed(title="🎶 Kolejka utworów", description=desc, color=discord.Color.blurple())
    await interaction.response.send_message(embed=embed)

# === KOMENDA LOOP ===
@bot.tree.command(name="loop", description="Ustaw tryb zapętlania (off/song/queue)")
async def loop(interaction: discord.Interaction, mode: str):
    if mode not in ["off", "song", "queue"]:
        await interaction.response.send_message("⚙️ Dostępne tryby: `off`, `song`, `queue`.")
        return

    LOOP_MODE[interaction.guild.id] = mode
    await interaction.response.send_message(f"🔁 Tryb pętli ustawiony na: `{mode}`")

# === KOMENDA SHUFFLE ===
@bot.tree.command(name="shuffle", description="Włącz/wyłącz automatyczne tasowanie kolejki")
async def shuffle(interaction: discord.Interaction):
    current = AUTOSHUFFLE.get(interaction.guild.id, False)
    AUTOSHUFFLE[interaction.guild.id] = not current
    status = "ON" if not current else "OFF"
    await interaction.response.send_message(f"🔀 Auto-shuffle: **{status}**")

# === START BOTA ===
bot.run(TOKEN)
