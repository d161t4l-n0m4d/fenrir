import asyncio
import json
import os
import random
import re
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from economy_v2 import setup_economy_v2

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set!")

CONFIG_PATH = "config.json" if os.path.exists("config.json") else "config.example.json"
with open(CONFIG_PATH, "r", encoding="utf-8") as file:
    CONFIG = json.load(file)

CURRENCY = CONFIG.get("currency_name", "Honey")
EMOJI = CONFIG.get("currency_emoji", "🍯")
TRIVIA_CHANNEL_ID = CONFIG.get("trivia_channel_id")
TRIVIA_INTERVAL_MIN = CONFIG.get("trivia_interval_min_minutes", 20)
TRIVIA_INTERVAL_MAX = CONFIG.get("trivia_interval_max_minutes", 40)
TRIVIA_TIME = CONFIG.get("trivia_time_seconds", 90)
DAILY_AMOUNT = CONFIG.get("daily_amount", 100)
WORK_MIN = CONFIG.get("work_min", 15)
WORK_MAX = CONFIG.get("work_max", 40)
WORK_COOLDOWN = CONFIG.get("work_cooldown_seconds", 3600)
ROLE_REWARDS = sorted(CONFIG.get("role_rewards", []), key=lambda item: item["honey_required"])
DB_PATH = "hive.db"

with open("questions.json", "r", encoding="utf-8") as file:
    QUESTIONS = json.load(file)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
bot = commands.Bot(command_prefix=CONFIG.get("prefix", "!"), intents=intents)

current_trivia = {"active": False, "question": None, "message_id": None, "channel_id": None}
asked_questions: set[str] = set()


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            honey INTEGER NOT NULL DEFAULT 0,
            last_daily TEXT,
            last_work TEXT
        );
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        await db.commit()


async def get_user(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT honey, last_daily, last_work FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row:
            return {"honey": row[0], "last_daily": row[1], "last_work": row[2]}
        await db.execute("INSERT INTO users (user_id, honey) VALUES (?, 0)", (user_id,))
        await db.commit()
    return {"honey": 0, "last_daily": None, "last_work": None}


async def add_honey(user_id: int, amount: int) -> dict:
    await get_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET honey = MAX(0, honey + ?) WHERE user_id = ?", (amount, user_id))
        await db.commit()
    return await get_user(user_id)


async def set_honey(user_id: int, amount: int) -> dict:
    await get_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET honey = ? WHERE user_id = ?", (max(0, amount), user_id))
        await db.commit()
    return await get_user(user_id)


async def update_timestamp(user_id: int, column: str) -> None:
    if column not in {"last_daily", "last_work"}:
        raise ValueError("Invalid timestamp column")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {column} = ? WHERE user_id = ?", (datetime.utcnow().isoformat(), user_id))
        await db.commit()


async def get_leaderboard(limit: int = 10) -> list[tuple[int, int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, honey FROM users ORDER BY honey DESC LIMIT ?", (limit,)) as cursor:
            return await cursor.fetchall()


async def add_warning(guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_warnings(guild_id: int, user_id: int) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, moderator_id, reason, created_at FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY id DESC",
            (guild_id, user_id),
        ) as cursor:
            return await cursor.fetchall()


async def clear_member_warnings(guild_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        await db.commit()
        return cursor.rowcount


async def check_and_assign_roles(member: discord.Member, honey: int) -> None:
    me = member.guild.me
    if not me or not me.guild_permissions.manage_roles:
        return
    roles = []
    for reward in ROLE_REWARDS:
        role = member.guild.get_role(reward["role_id"])
        if role and honey >= reward["honey_required"] and role not in member.roles and me.top_role > role:
            roles.append(role)
    if not roles:
        return
    try:
        await member.add_roles(*roles, reason="Hive economy role reward")
    except discord.Forbidden:
        return


def moderation_error(message: str) -> discord.Embed:
    return discord.Embed(title="❌ Moderation Action Failed", description=message, color=discord.Color.red())


def can_moderate_member(interaction: discord.Interaction, target: discord.Member) -> Optional[str]:
    guild = interaction.guild
    if not guild:
        return "This command can only be used in a server."
    if target.id == interaction.user.id:
        return "You cannot moderate yourself."
    if target.id == guild.owner_id:
        return "You cannot moderate the server owner."
    me = guild.me
    if not me or target.id == me.id or target.top_role >= me.top_role:
        return "My highest role must be above the target's highest role."
    if isinstance(interaction.user, discord.Member) and interaction.user.id != guild.owner_id and target.top_role >= interaction.user.top_role:
        return "Your highest role must be above the target's highest role."
    return None


def clean_answer(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text.lower())).strip()


def is_correct_answer(answer: str, question: dict) -> bool:
    answer = clean_answer(answer)
    accepted = question.get("accepted") or [question.get("answer", "")]
    return any(answer == clean_answer(item) for item in accepted)


def pick_question(difficulty: Optional[str] = None) -> dict:
    global asked_questions
    pool = [q for q in QUESTIONS if not difficulty or q.get("difficulty") == difficulty] or QUESTIONS
    if len(asked_questions) >= len(QUESTIONS) * 0.9:
        asked_questions.clear()
    candidates = [q for q in pool if q["question"] not in asked_questions] or pool
    question = random.choice(candidates)
    asked_questions.add(question["question"])
    return question


async def post_trivia(difficulty: Optional[str] = None) -> None:
    global current_trivia
    if not TRIVIA_CHANNEL_ID or current_trivia["active"]:
        return
    channel = bot.get_channel(TRIVIA_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(TRIVIA_CHANNEL_ID)
        except discord.DiscordException:
            return
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return
    question = pick_question(difficulty)
    reward = int(question.get("coins", 50))
    embed = discord.Embed(title="🧠 Hive Trivia — First Correct Answer Wins!", description=f"**{question['question']}**", color=discord.Color.gold())
    embed.add_field(name="Reward", value=f"**{reward}** {EMOJI} {CURRENCY}")
    if question.get("hint"):
        embed.add_field(name="Hint", value=question["hint"], inline=False)
    message = await channel.send(embed=embed)
    current_trivia = {"active": True, "question": question, "message_id": message.id, "channel_id": channel.id}
    await asyncio.sleep(TRIVIA_TIME)
    if current_trivia["active"] and current_trivia["message_id"] == message.id:
        current_trivia = {"active": False, "question": None, "message_id": None, "channel_id": None}
        await channel.send(f"⏰ Trivia ended. Answer: `{question['answer']}`")


@tasks.loop(minutes=1)
async def trivia_loop() -> None:
    await bot.wait_until_ready()


async def schedule_trivia_loop() -> None:
    await bot.wait_until_ready()
    await asyncio.sleep(15)
    while not bot.is_closed():
        await post_trivia()
        await asyncio.sleep(random.uniform(TRIVIA_INTERVAL_MIN, TRIVIA_INTERVAL_MAX) * 60)


@bot.event
async def setup_hook() -> None:
    await init_db()
    await setup_economy_v2(bot, DB_PATH, CURRENCY, EMOJI)
    bot.loop.create_task(schedule_trivia_loop())


@bot.event
async def on_ready() -> None:
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Synced {len(synced)} slash commands")
    except discord.DiscordException as exc:
        print(f"Slash-command sync failed: {exc}")
    if not trivia_loop.is_running():
        trivia_loop.start()


@bot.event
async def on_message(message: discord.Message) -> None:
    global current_trivia
    if message.author.bot:
        return
    if current_trivia["active"] and message.channel.id == current_trivia["channel_id"]:
        question = current_trivia["question"]
        if question and is_correct_answer(message.content, question):
            reward = int(question.get("coins", 50))
            current_trivia = {"active": False, "question": None, "message_id": None, "channel_id": None}
            user = await add_honey(message.author.id, reward)
            if isinstance(message.author, discord.Member):
                await check_and_assign_roles(message.author, user["honey"])
            await message.channel.send(f"✅ {message.author.mention} answered correctly and earned **{reward}** {EMOJI}!")
    await bot.process_commands(message)


@bot.tree.command(name="balance", description="Check your legacy Honey balance")
@app_commands.describe(member="Member to check (optional)")
async def balance(interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
    target = member or interaction.user
    user = await get_user(target.id)
    await interaction.response.send_message(f"{target.mention} has **{user['honey']:,}** {EMOJI} {CURRENCY}.")


@bot.tree.command(name="daily", description="Claim your legacy daily reward")
async def daily(interaction: discord.Interaction) -> None:
    user = await get_user(interaction.user.id)
    if user["last_daily"]:
        last = datetime.fromisoformat(user["last_daily"])
        remaining = timedelta(hours=20) - (datetime.utcnow() - last)
        if remaining.total_seconds() > 0:
            await interaction.response.send_message(f"⏳ Come back in **{int(remaining.total_seconds() // 3600)}h**.", ephemeral=True)
            return
    user = await add_honey(interaction.user.id, DAILY_AMOUNT)
    await update_timestamp(interaction.user.id, "last_daily")
    if isinstance(interaction.user, discord.Member):
        await check_and_assign_roles(interaction.user, user["honey"])
    await interaction.response.send_message(f"📅 Claimed **{DAILY_AMOUNT}** {EMOJI}. Balance: **{user['honey']:,}**.")


@bot.tree.command(name="work", description="Work to earn legacy Honey")
async def work(interaction: discord.Interaction) -> None:
    user = await get_user(interaction.user.id)
    if user["last_work"]:
        last = datetime.fromisoformat(user["last_work"])
        remaining = timedelta(seconds=WORK_COOLDOWN) - (datetime.utcnow() - last)
        if remaining.total_seconds() > 0:
            await interaction.response.send_message(f"⏳ Try again <t:{int((datetime.utcnow() + remaining).timestamp())}:R>.", ephemeral=True)
            return
    earned = random.randint(WORK_MIN, WORK_MAX)
    user = await add_honey(interaction.user.id, earned)
    await update_timestamp(interaction.user.id, "last_work")
    if isinstance(interaction.user, discord.Member):
        await check_and_assign_roles(interaction.user, user["honey"])
    await interaction.response.send_message(f"🛠️ You earned **{earned}** {EMOJI}. Balance: **{user['honey']:,}**.")


@bot.tree.command(name="pay", description="Send legacy Honey to another member")
async def pay(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1]) -> None:
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("Choose another human member.", ephemeral=True)
        return
    sender = await get_user(interaction.user.id)
    if sender["honey"] < amount:
        await interaction.response.send_message("❌ Insufficient balance.", ephemeral=True)
        return
    await add_honey(interaction.user.id, -amount)
    receiver = await add_honey(member.id, amount)
    await check_and_assign_roles(member, receiver["honey"])
    await interaction.response.send_message(f"💸 Sent **{amount:,}** {EMOJI} to {member.mention}.")


@bot.tree.command(name="leaderboard", description="View legacy Honey leaderboard")
async def leaderboard(interaction: discord.Interaction) -> None:
    rows = await get_leaderboard()
    lines = [f"**{index}.** <@{user_id}> — **{honey:,}** {EMOJI}" for index, (user_id, honey) in enumerate(rows, 1)]
    await interaction.response.send_message(embed=discord.Embed(title="🏆 Honey Leaderboard", description="\n".join(lines) or "No entries yet.", color=discord.Color.gold()))


@bot.tree.command(name="trivia", description="Post a trivia question")
@app_commands.default_permissions(manage_messages=True)
async def force_trivia(interaction: discord.Interaction, difficulty: Optional[str] = None) -> None:
    valid = {"easy", "medium", "hard", "null"}
    if difficulty and difficulty.lower() not in valid:
        await interaction.response.send_message("Difficulty must be easy, medium, hard, or null.", ephemeral=True)
        return
    if current_trivia["active"]:
        await interaction.response.send_message("A trivia question is already active.", ephemeral=True)
        return
    await interaction.response.send_message("Posting trivia…", ephemeral=True)
    await post_trivia(difficulty.lower() if difficulty else None)


@bot.tree.command(name="ban", description="Ban a member")
@app_commands.default_permissions(ban_members=True)
async def ban_member(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
    if not interaction.user.guild_permissions.ban_members or not interaction.guild.me.guild_permissions.ban_members:
        await interaction.response.send_message(embed=moderation_error("Missing Ban Members permission."), ephemeral=True); return
    error = can_moderate_member(interaction, member)
    if error: await interaction.response.send_message(embed=moderation_error(error), ephemeral=True); return
    await member.ban(reason=f"{interaction.user}: {reason}")
    await interaction.response.send_message(f"🔨 Banned {member.mention}. Reason: {reason}")


@bot.tree.command(name="kick", description="Kick a member")
@app_commands.default_permissions(kick_members=True)
async def kick_member(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided") -> None:
    if not interaction.user.guild_permissions.kick_members or not interaction.guild.me.guild_permissions.kick_members:
        await interaction.response.send_message(embed=moderation_error("Missing Kick Members permission."), ephemeral=True); return
    error = can_moderate_member(interaction, member)
    if error: await interaction.response.send_message(embed=moderation_error(error), ephemeral=True); return
    await member.kick(reason=f"{interaction.user}: {reason}")
    await interaction.response.send_message(f"👢 Kicked {member.mention}. Reason: {reason}")


@bot.tree.command(name="timeout", description="Timeout a member")
@app_commands.default_permissions(moderate_members=True)
async def timeout_member(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason provided") -> None:
    if not interaction.user.guild_permissions.moderate_members or not interaction.guild.me.guild_permissions.moderate_members:
        await interaction.response.send_message(embed=moderation_error("Missing Moderate Members permission."), ephemeral=True); return
    error = can_moderate_member(interaction, member)
    if error: await interaction.response.send_message(embed=moderation_error(error), ephemeral=True); return
    until = datetime.utcnow() + timedelta(minutes=minutes)
    await member.timeout(until, reason=f"{interaction.user}: {reason}")
    await interaction.response.send_message(f"⏳ Timed out {member.mention} for **{minutes}** minute(s). Reason: {reason}")


@bot.tree.command(name="untimeout", description="Remove a member timeout")
@app_commands.default_permissions(moderate_members=True)
async def untimeout_member(interaction: discord.Interaction, member: discord.Member, reason: str = "Timeout removed") -> None:
    if not interaction.user.guild_permissions.moderate_members or not interaction.guild.me.guild_permissions.moderate_members:
        await interaction.response.send_message(embed=moderation_error("Missing Moderate Members permission."), ephemeral=True); return
    error = can_moderate_member(interaction, member)
    if error: await interaction.response.send_message(embed=moderation_error(error), ephemeral=True); return
    await member.timeout(None, reason=f"{interaction.user}: {reason}")
    await interaction.response.send_message(f"✅ Removed timeout for {member.mention}.")


@bot.tree.command(name="purge", description="Delete up to 100 messages")
@app_commands.default_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100], member: Optional[discord.Member] = None) -> None:
    if not interaction.user.guild_permissions.manage_messages or not interaction.guild.me.guild_permissions.manage_messages:
        await interaction.response.send_message(embed=moderation_error("Missing Manage Messages permission."), ephemeral=True); return
    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("This command only works in text channels.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount, check=lambda msg: member is None or msg.author.id == member.id, reason=f"Purged by {interaction.user}")
    await interaction.followup.send(f"🧹 Deleted **{len(deleted)}** message(s).", ephemeral=True)


@bot.tree.command(name="warn", description="Warn a member")
@app_commands.default_permissions(manage_messages=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message(embed=moderation_error("Missing Manage Messages permission."), ephemeral=True); return
    error = can_moderate_member(interaction, member)
    if error: await interaction.response.send_message(embed=moderation_error(error), ephemeral=True); return
    warning_id = await add_warning(interaction.guild.id, member.id, interaction.user.id, reason)
    await interaction.response.send_message(f"⚠️ Warned {member.mention}. Warning ID: `{warning_id}`. Reason: {reason}")


@bot.tree.command(name="warnings", description="View a member's warnings")
@app_commands.default_permissions(manage_messages=True)
async def warnings(interaction: discord.Interaction, member: discord.Member) -> None:
    rows = await get_warnings(interaction.guild.id, member.id)
    if not rows:
        await interaction.response.send_message(f"✅ {member.mention} has no warnings.", ephemeral=True); return
    lines = [f"**#{warning_id}** — <@{moderator_id}> — {reason}" for warning_id, moderator_id, reason, _ in rows[:10]]
    await interaction.response.send_message(embed=discord.Embed(title=f"⚠️ Warnings — {member.display_name}", description="\n".join(lines), color=discord.Color.gold()), ephemeral=True)


@bot.tree.command(name="clearwarnings", description="Clear a member's warnings")
@app_commands.default_permissions(manage_messages=True)
async def clearwarnings(interaction: discord.Interaction, member: discord.Member) -> None:
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message(embed=moderation_error("Missing Manage Messages permission."), ephemeral=True); return
    count = await clear_member_warnings(interaction.guild.id, member.id)
    await interaction.response.send_message(f"🧽 Cleared **{count}** warning(s) for {member.mention}.")


if __name__ == "__main__":
    bot.run(TOKEN)
