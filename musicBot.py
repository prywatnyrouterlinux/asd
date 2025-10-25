import os
import discord
import random
discord.utils.setup_logging(level="WARNING")
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import yt_dlp
from collections import deque
import asyncio
import shutil

# === Ładowanie tokena i FFMPEG ===
load_dotenv()
TOKEN = os.getenv("token")
ffmpeg_exe = shutil.which("ffmpeg") or "./bin/ffmpeg.exe"

# === Kolejki i tryby ===
SONG_QUEUES = {}
CURRENT_SONG = {}
LOOP_MODE = {}
AUTOSHUFFLE = {}

# === Pobieranie informacji o utworze ===
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

# === Tworzenie bota ===
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# === Po uruchomieniu ===
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} is online and commands are synced!")
    activity = discord.Activity(
        type=discord.ActivityType.listening, 
        name="your next request..."
    )
    await bot.change_presence(status=discord.Status.online, activity=activity)

# === Odtwarzanie następnego utworu ===
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

# === Slash-komendy ===
@bot.tree.command(name="play", description="Play a song from YouTube")
@app_commands.describe(song_query="Search query or YouTube link")
async def play(interaction: discord.Interaction, song_query: str):
    await interaction.response.defer()
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.followup.send("❌ You must be in a voice channel to use this.")
        return

    voice_channel = interaction.user.voice.channel
    vc = interaction.guild.voice_client

    if vc is None:
        vc = await voice_channel.connect()
    elif vc.channel != voice_channel:
        await vc.move_to(voice_channel)

    guild_id = str(interaction.guild_id)
    if SONG_QUEUES.get(guild_id) is None:
        SONG_QUEUES[guild_id] = deque()

    loading_msg = await interaction.followup.send("⏳ Loading...")

    result = await get_audio_source(song_query)
    SONG_QUEUES[guild_id].append(song_query)

    if vc.is_playing() or vc.is_paused():
        await loading_msg.edit(content=f"✅ Added to queue: **{result['title']}**")
    else:
        await play_next_song(vc, guild_id, interaction.channel, message=loading_msg)

@bot.tree.command(name="skip", description="Skip the current song")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await interaction.response.send_message("⏭️ Skipping song...")
    else:
        await interaction.response.send_message("❌ Nothing is currently playing.")

@bot.tree.command(name="pause", description="Pause the current song")
async def pause(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await interaction.response.send_message("⏸️ Paused playback.")
    else:
        await interaction.response.send_message("❌ Nothing is currently playing.")

@bot.tree.command(name="resume", description="Resume paused playback")
async def resume(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await interaction.response.send_message("▶️ Resumed playback.")
    else:
        await interaction.response.send_message("❌ Nothing is paused.")

@bot.tree.command(name="stop", description="Stop playback and clear the queue")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    guild_id = str(interaction.guild_id)
    if vc:
        await vc.disconnect()
    SONG_QUEUES[guild_id] = deque()
    CURRENT_SONG[guild_id] = None
    LOOP_MODE[guild_id] = "off"
    AUTOSHUFFLE[guild_id] = False
    await interaction.response.send_message("🛑 Stopped playback and cleared the queue.")

@bot.tree.command(name="help", description="Show all commands and their descriptions")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 Bot Commands",
        color=discord.Color.blue()
    )
    embed.add_field(name="/play <song>", value="Play a song from YouTube", inline=False)
    embed.add_field(name="/skip", value="Skip the current song", inline=False)
    embed.add_field(name="/pause", value="Pause playback", inline=False)
    embed.add_field(name="/resume", value="Resume playback", inline=False)
    embed.add_field(name="/stop", value="Stop playback and clear the queue", inline=False)
    embed.add_field(name="/queue", value="Show the current queue", inline=False)
    embed.add_field(name="/loop <off|song|queue>", value="Set loop mode", inline=False)
    embed.add_field(name="/shuffle", value="Shuffle the queue manually", inline=False)
    embed.add_field(name="/autoshuffle <on|off>", value="Enable automatic shuffling", inline=False)
    embed.add_field(name="/volume <0-200>", value="Adjust volume", inline=False)
    embed.add_field(name="/clear <amount>", value="Delete messages (Admin only)", inline=False)
    embed.set_footer(text="Bot created by: opilog12")
    embed.set_image(url="attachment://baner.gif")
    with open("baner.gif", "rb") as f:
        await interaction.response.send_message(file=discord.File(f, filename="baner.gif"), embed=embed)

# === Klasyczna komenda tekstowa !echo ===
@bot.command(name="echo")
async def echo(ctx, *, message: str):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ You need administrator permissions to use this command.")
        return
    try:
        await ctx.message.delete()
    except:
        pass
    await ctx.send(message)

# === Start bota ===
bot.run(TOKEN)
