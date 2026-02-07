import os
import discord
from discord.ext import commands

TOKEN = os.environ["DISCORD_TOKEN"]
GUILD_ID = 1466960571004882967  # ← 自分のサーバーID

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    await bot.tree.sync(guild=guild)
    print(f"Bot起動: {bot.user} (guild synced)")

@bot.tree.command(
    name="ping",
    description="動作確認",
    guild=discord.Object(id=GUILD_ID)
)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong!")

bot.run(TOKEN)
