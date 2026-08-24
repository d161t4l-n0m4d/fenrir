import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import json
import os
import random
import asyncio
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from economy_v2 import setup_economy_v2

load_dotenv()

# ================== LOAD CONFIG ==================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set!")

CONFIG_PATH = "config.json"
if not os.path.exists(CONFIG_PATH):
    CONFIG_PATH = "config.example.json"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

CURRENCY = CONFIG.get("currency_name", "Honey")
EMOJI = CONFIG.get("currency_emoji", "🍯")
TRIVIA_CHANNEL_ID = CONFIG.get("trivia_channel_id")
TRIVIA_INTERVAL_MIN = CONFIG.get("trivia_interval_min_minutes", 20)
TRIVIA_INTERVAL_MAX = CONFIG.get("trivia_interval_max_minutes", 40)
TRIVIA_TIME = CONFIG.get("trivia_time_seconds", 90)  # longer for free-text
DAILY_AMOUNT = CONFIG.get("daily_amount", 100)
WORK_MIN = CONFIG.get("work_min", 15)
WORK_MAX = CONFIG.get("work_max", 40)
WORK_COOLDOWN = CONFIG.get("work_cooldown_seconds", 3600)
ROLE_REWARDS = sorted(CONFIG.get("role_rewards", []), key=lambda x: x["honey_required"])

# Load questions
with open("questions.json", "r", encoding="utf-8") as f:
    QUESTIONS = json.load(f)

# ================== BOT SETUP ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=CONFIG.get("prefix", "!"), intents=intents)

# ================== DATABASE ==================
DB_PATH = "hive.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                honey INTEGER DEFAULT 0,
                last_daily TEXT,
                last_work TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT honey, last_daily, last_work FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"honey": row[0], "last_daily": row[1], "last_work": row[2]}
            await db.execute("INSERT INTO users (user_id, honey) VALUES (?, 0)", (user_id,))
            await db.commit()
            return {"honey": 0, "last_daily": None, "last_work": None}

async def add_honey(user_id: int, amount: int):
    await get_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET honey = honey + ? WHERE user_id = ?", (amount, user_id)
        )
        await db.commit()
    return await get_user(user_id)

async def set_honey(user_id: int, amount: int):
    await get_user(user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET honey = ? WHERE user_id = ?", (amount, user_id)
        )
        await db.commit()
    return await get_user(user_id)

async def update_last_daily(user_id: int):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_daily = ? WHERE user_id = ?", (now, user_id)
        )
        await db.commit()

async def update_last_work(user_id: int):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_work = ? WHERE user_id = ?", (now, user_id)
        )
        await db.commit()

async def get_leaderboard(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, honey FROM users ORDER BY honey DESC LIMIT ?", (limit,)
        ) as cursor:
            return await cursor.fetchall()

# ================== ROLE MANAGEMENT ==================
async def check_and_assign_roles(member: discord.Member, honey: int):
    if not member.guild.me.guild_permissions.manage_roles:
        return

    roles_to_add = []
    for reward in ROLE_REWARDS:
        role = member.guild.get_role(reward["role_id"])
        if role is None:
            continue
        if honey >= reward["honey_required"] and role not in member.roles:
            if member.guild.me.top_role > role:
                roles_to_add.append(role)

    if roles_to_add:
        try:
            await member.add_roles(*roles_to_add, reason="Hive level reward")
            names = ", ".join(r.name for r in roles_to_add)
            try:
                await member.send(
                    f"🎉 **Level up in The Hive!** You earned: **{names}** "
                    f"for reaching {honey} {EMOJI} {CURRENCY}!"
                )
            except discord.Forbidden:
                pass
        except discord.Forbidden:
            print(f"Missing permissions to assign roles in {member.guild.name}")

# ================== MODERATION HELPERS ==================

def moderation_error(message: str) -> discord.Embed:
    return discord.Embed(
        title="❌ Moderation Action Failed",
        description=message,
        color=discord.Color.red(),
    )


def can_moderate_member(
    interaction: discord.Interaction,
    target: discord.Member,
) -> str | None:
    """Return an error string when target cannot be moderated, else None."""
    if interaction.guild is None:
        return "This command can only be used inside a server."

    if target.id == interaction.user.id:
        return "You cannot moderate yourself."

    if target.id == interaction.guild.owner_id:
        return "You cannot moderate the server owner."

    if interaction.guild.me is None:
        return "I could not determine my server permissions."

    if target.id == interaction.guild.me.id:
        return "I cannot moderate myself."

    if target.top_role >= interaction.guild.me.top_role:
        return "My highest role must be above the target's highest role."

    if (
        interaction.user.id != interaction.guild.owner_id
        and isinstance(interaction.user, discord.Member)
        and target.top_role >= interaction.user.top_role
    ):
        return "Your highest role must be above the target's highest role."

    return None


async def add_warning(
    guild_id: int,
    user_id: int,
    moderator_id: int,
    reason: str,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, user_id, moderator_id, reason, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_warnings(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT id, moderator_id, reason, created_at
            FROM warnings
            WHERE guild_id = ? AND user_id = ?
            ORDER BY id DESC
            """,
            (guild_id, user_id),
        ) as cursor:
            return await cursor.fetchall()


async def clear_member_warnings(guild_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await db.commit()
        return cursor.rowcount
# ================== TRIVIA STATE ==================
current_trivia = {
    "active": False,
    "question": None,
    "message_id": None,
    "channel_id": None,
    "start_time": None,
}
asked_indices = set()


def pick_question(force_difficulty=None):
    global asked_indices
    pool = QUESTIONS
    if force_difficulty:
        pool = [q for q in QUESTIONS if q.get("difficulty") == force_difficulty]
        if not pool:
            pool = QUESTIONS

    if len(asked_indices) >= len(QUESTIONS) * 0.9:
        asked_indices.clear()

    for _ in range(200):
        idx = random.randrange(len(pool))
        # Use id of question text to track across force filters
        key = pool[idx]["question"]
        if key not in asked_indices:
            asked_indices.add(key)
            return pool[idx]
    return random.choice(pool)


def difficulty_emoji(d):
    return {"easy": "🟢", "medium": "🟡", "hard": "🔴", "null": "💀"}.get(d, "⚪")


def clean_answer(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[.,!?;:()\[\]\"'`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def similarity(s1: str, s2: str) -> float:
    """Simple similarity; strict for pure numbers."""
    c1 = re.sub(r"[^a-z0-9]", "", s1.lower())
    c2 = re.sub(r"[^a-z0-9]", "", s2.lower())
    if c1 == c2:
        return 1.0
    # Strict numeric match
    if re.fullmatch(r"\d+", c2):
        return 0.0
    if not c1 or not c2:
        return 0.0
    if max(len(c1), len(c2)) <= 4:
        return 1.0 if c1 == c2 else 0.0

    # Levenshtein
    longer, shorter = (c1, c2) if len(c1) >= len(c2) else (c2, c1)
    costs = list(range(len(shorter) + 1))
    for i, ch1 in enumerate(longer):
        new_costs = [i + 1]
        for j, ch2 in enumerate(shorter):
            cost = 0 if ch1 == ch2 else 1
            new_costs.append(min(new_costs[j] + 1, costs[j + 1] + 1, costs[j] + cost))
        costs = new_costs
    distance = costs[-1]
    return (len(longer) - distance) / len(longer)


def is_correct_answer(user_text: str, question: dict) -> bool:
    clean_user = clean_answer(user_text)
    accepted = question.get("accepted") or [question.get("answer", "")]

    for acc in accepted:
        clean_acc = clean_answer(acc)
        if clean_user == clean_acc:
            return True
        # Substring for longer answers
        if len(clean_acc) > 6 and clean_acc in clean_user:
            return True
        if similarity(clean_user, clean_acc) >= 0.82:
            return True
    return False


# ================== EVENTS ==================
@bot.event
async def on_ready():
    await init_db()
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"🍯 Currency: {CURRENCY} {EMOJI}")
    print(f"📚 Loaded {len(QUESTIONS)} trivia questions")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    if not trivia_loop.is_running():
        trivia_loop.start()
        print(
            f"🧠 Trivia loop started (random every {TRIVIA_INTERVAL_MIN}-{TRIVIA_INTERVAL_MAX} min)"
        )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Free-text trivia answer check
    if (
        current_trivia["active"]
        and current_trivia["question"]
        and message.channel.id == current_trivia["channel_id"]
    ):
        content = message.content.strip()
        # Strip bot mention if present
        content = re.sub(rf"^<@!?{bot.user.id}>\s*", "", content).strip()

        if is_correct_answer(content, current_trivia["question"]):
            q = current_trivia["question"]
            reward = int(q.get("coins", 50))
            current_trivia["active"] = False
            current_trivia["question"] = None

            user = await add_honey(message.author.id, reward)
            if isinstance(message.author, discord.Member):
                await check_and_assign_roles(message.author, user["honey"])

            win = discord.Embed(
                title="✅ Correct Answer!",
                description=(
                    f"**Q:** {q['question']}\n\n"
                    f"🏆 **Winner:** {message.author.mention}\n"
                    f"💡 **Answer:** `{q['answer']}`\n"
                    f"💰 **Earned:** **{reward}** {EMOJI} {CURRENCY}\n"
                    f"New balance: **{user['honey']}** {EMOJI}"
                ),
                color=discord.Color.green(),
            )
            if q.get("explanation"):
                win.add_field(name="📚 Explanation", value=q["explanation"], inline=False)
            win.set_footer(text="The Hive • Next question coming soon")
            win.timestamp = datetime.utcnow()
            await message.channel.send(embed=win)

            # Grey out original question message
            try:
                orig = await message.channel.fetch_message(current_trivia["message_id"])
                if orig.embeds:
                    grey = orig.embeds[0].copy()
                    grey.color = discord.Color.dark_grey()
                    grey.title = "✅ [ANSWERED] Hive Trivia"
                    grey.set_footer(text=f"Answered by {message.author.display_name}")
                    await orig.edit(embed=grey)
            except Exception:
                pass

            try:
                await message.author.send(
                    embed=discord.Embed(
                        title="🎉 You answered correctly in The Hive!",
                        description=(
                            f"You won **{reward}** {EMOJI} {CURRENCY}!\n\n"
                            f"❓ {q['question']}\n\n"
                            f"✅ **Answer:** `{q['answer']}`\n"
                            f"📚 {q.get('explanation', '')}"
                        ),
                        color=discord.Color.gold(),
                    )
                )
            except discord.Forbidden:
                pass

    await bot.process_commands(message)


# ================== TRIVIA LOOP ==================
@tasks.loop(minutes=1)
async def trivia_loop():
    """Tick every minute; schedule actual posts with random delay logic."""
    await bot.wait_until_ready()
    # Actual posting is driven by schedule_next via a one-shot task
    pass


_next_trivia_task = None


async def post_trivia(force_difficulty=None):
    global current_trivia

    if not TRIVIA_CHANNEL_ID:
        print("⚠️ trivia_channel_id not set — skipping trivia")
        return

    if current_trivia["active"]:
        return

    channel = bot.get_channel(TRIVIA_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(TRIVIA_CHANNEL_ID)
        except Exception:
            print(f"⚠️ Could not find trivia channel {TRIVIA_CHANNEL_ID}")
            return

    q = pick_question(force_difficulty)
    reward = int(q.get("coins", 50))
    diff = q.get("difficulty", "easy")

    color = {
        "easy": discord.Color.green(),
        "medium": discord.Color.gold(),
        "hard": discord.Color.red(),
        "null": discord.Color.from_rgb(0, 255, 0),
    }.get(diff, discord.Color.purple())

    embed = discord.Embed(
        title="🧠 Hive Trivia — First Correct Answer Wins!",
        description=f"**{q['question']}**",
        color=color,
    )
    embed.add_field(
        name="Difficulty",
        value=f"{difficulty_emoji(diff)} {diff.capitalize()}",
        inline=True,
    )
    embed.add_field(
        name="Reward",
        value=f"**{reward}** {EMOJI} {CURRENCY}",
        inline=True,
    )
    if q.get("hint"):
        embed.add_field(name="Hint", value=q["hint"], inline=False)
    embed.set_footer(text="Type your answer in chat! First correct answer wins.")
    embed.timestamp = datetime.utcnow()

    msg = await channel.send(embed=embed)

    current_trivia = {
        "active": True,
        "question": q,
        "message_id": msg.id,
        "channel_id": channel.id,
        "start_time": datetime.utcnow(),
    }
    print(f"[TRIVIA] Posted ({diff}, {reward} {CURRENCY}): {q['question'][:60]}")

    # Auto-expire after TRIVIA_TIME seconds
    await asyncio.sleep(TRIVIA_TIME)

    if current_trivia["active"] and current_trivia["message_id"] == msg.id:
        current_trivia["active"] = False
        current_trivia["question"] = None
        end = discord.Embed(
            title="⏰ Trivia Ended",
            description=(
                f"Time's up!\n"
                f"**Answer was:** `{q['answer']}`\n"
                f"Nobody got it this round. Study up, bees! 🐝"
            ),
            color=discord.Color.orange(),
        )
        if q.get("explanation"):
            end.add_field(name="Explanation", value=q["explanation"], inline=False)
        await channel.send(embed=end)
        try:
            grey = embed.copy()
            grey.color = discord.Color.dark_grey()
            grey.title = "⏰ [EXPIRED] Hive Trivia"
            await msg.edit(embed=grey)
        except Exception:
            pass


async def schedule_trivia_loop():
    await bot.wait_until_ready()
    await asyncio.sleep(15)  # small startup delay
    while not bot.is_closed():
        await post_trivia()
        delay_min = random.uniform(TRIVIA_INTERVAL_MIN, TRIVIA_INTERVAL_MAX)
        print(f"[TRIVIA] Next question in ~{delay_min:.1f} min")
        await asyncio.sleep(delay_min * 60)


@bot.event
async def setup_hook():
    await setup_economy_v2(
        bot,
        DB_PATH,
        CURRENCY,
        EMOJI,
    )

    bot.loop.create_task(schedule_trivia_loop())


# ================== SLASH COMMANDS ==================

@bot.tree.command(name="balance", description=f"Check your {CURRENCY} balance")
@app_commands.describe(member="User to check (optional)")
async def balance(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    user = await get_user(target.id)

    embed = discord.Embed(title=f"{EMOJI} {CURRENCY} Balance", color=discord.Color.gold())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="User", value=target.mention, inline=True)
    embed.add_field(name="Balance", value=f"**{user['honey']}** {EMOJI}", inline=True)

    next_role = None
    for reward in ROLE_REWARDS:
        if user["honey"] < reward["honey_required"]:
            next_role = reward
            break

    if next_role:
        needed = next_role["honey_required"] - user["honey"]
        embed.add_field(
            name="Next Rank",
            value=f"**{next_role['name']}** — {needed} more {EMOJI}",
            inline=False,
        )
    else:
        if ROLE_REWARDS:
            embed.add_field(name="Rank", value="Highest rank unlocked! 👑", inline=False)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="daily", description=f"Claim your daily {CURRENCY}")
async def daily(interaction: discord.Interaction):
    user = await get_user(interaction.user.id)

    if user["last_daily"]:
        last = datetime.fromisoformat(user["last_daily"])
        if datetime.utcnow() - last < timedelta(hours=20):
            remaining = timedelta(hours=20) - (datetime.utcnow() - last)
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes = remainder // 60
            await interaction.response.send_message(
                f"⏳ Already claimed! Come back in **{hours}h {minutes}m**.",
                ephemeral=True,
            )
            return

    new_user = await add_honey(interaction.user.id, DAILY_AMOUNT)
    await update_last_daily(interaction.user.id)
    if isinstance(interaction.user, discord.Member):
        await check_and_assign_roles(interaction.user, new_user["honey"])

    embed = discord.Embed(
        title="📅 Daily Reward Claimed!",
        description=(
            f"You received **{DAILY_AMOUNT}** {EMOJI} {CURRENCY}!\n"
            f"New balance: **{new_user['honey']}** {EMOJI}"
        ),
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="work", description=f"Do some work in the Hive to earn {CURRENCY}")
async def work(interaction: discord.Interaction):
    user = await get_user(interaction.user.id)

    if user["last_work"]:
        last = datetime.fromisoformat(user["last_work"])
        if datetime.utcnow() - last < timedelta(seconds=WORK_COOLDOWN):
            remaining = timedelta(seconds=WORK_COOLDOWN) - (datetime.utcnow() - last)
            minutes = int(remaining.total_seconds() // 60)
            await interaction.response.send_message(
                f"⏳ Rest for **{minutes} more minutes** before working again.",
                ephemeral=True,
            )
            return

    earned = random.randint(WORK_MIN, WORK_MAX)
    new_user = await add_honey(interaction.user.id, earned)
    await update_last_work(interaction.user.id)
    if isinstance(interaction.user, discord.Member):
        await check_and_assign_roles(interaction.user, new_user["honey"])

    jobs = [
        "scanned the network perimeter",
        "reviewed firewall rules",
        "analyzed suspicious logs",
        "updated the threat intelligence feed",
        "practiced privilege escalation in the lab",
        "wrote a phishing awareness post",
        "hardened a web server",
        "triaged security alerts",
        "documented an incident response playbook",
        "tested password policies",
    ]
    job = random.choice(jobs)

    embed = discord.Embed(
        title="🛠️ Work Complete",
        description=(
            f"You {job} and earned **{earned}** {EMOJI} {CURRENCY}!\n"
            f"New balance: **{new_user['honey']}** {EMOJI}"
        ),
        color=discord.Color.blue(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="pay", description=f"Send {CURRENCY} to another member")
@app_commands.describe(member="Who to pay", amount=f"Amount of {CURRENCY} to send")
async def pay(interaction: discord.Interaction, member: discord.Member, amount: int):
    if member.bot:
        await interaction.response.send_message("You can't pay bots.", ephemeral=True)
        return
    if member.id == interaction.user.id:
        await interaction.response.send_message("You can't pay yourself.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("Amount must be positive.", ephemeral=True)
        return

    sender = await get_user(interaction.user.id)
    if sender["honey"] < amount:
        await interaction.response.send_message(
            f"You only have **{sender['honey']}** {EMOJI}.", ephemeral=True
        )
        return

    await add_honey(interaction.user.id, -amount)
    receiver = await add_honey(member.id, amount)
    await check_and_assign_roles(member, receiver["honey"])

    embed = discord.Embed(
        title="💸 Payment Sent",
        description=(
            f"{interaction.user.mention} sent **{amount}** {EMOJI} {CURRENCY} "
            f"to {member.mention}!\n"
            f"Their new balance: **{receiver['honey']}** {EMOJI}"
        ),
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="leaderboard", description=f"Top {CURRENCY} holders in the Hive")
async def leaderboard(interaction: discord.Interaction):
    rows = await get_leaderboard(10)
    if not rows:
        await interaction.response.send_message("No one has any Honey yet!", ephemeral=True)
        return

    description = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, honey) in enumerate(rows):
        medal = medals[i] if i < 3 else f"**{i+1}.**"
        description.append(f"{medal} <@{user_id}> — **{honey}** {EMOJI}")

    embed = discord.Embed(
        title=f"🏆 Hive Leaderboard — Top {CURRENCY}",
        description="\n".join(description),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="The Hive • Keep grinding, bees!")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ranks", description="Show Honey ranks and role rewards")
async def ranks(interaction: discord.Interaction):
    if not ROLE_REWARDS:
        await interaction.response.send_message(
            "No role rewards configured yet.", ephemeral=True
        )
        return

    lines = [
        f"**{r['honey_required']}** {EMOJI} → <@&{r['role_id']}> ({r['name']})"
        for r in ROLE_REWARDS
    ]
    embed = discord.Embed(
        title="🐝 Hive Ranks",
        description="\n".join(lines),
        color=discord.Color.purple(),
    )
    embed.set_footer(text="Earn Honey to unlock roles automatically!")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="trivia", description="Force a trivia question (mods)")
@app_commands.describe(difficulty="Optional: easy, medium, hard, or null")
@app_commands.default_permissions(manage_messages=True)
async def force_trivia(interaction: discord.Interaction, difficulty: str = None):
    if current_trivia["active"]:
        await interaction.response.send_message(
            "A trivia is already running!", ephemeral=True
        )
        return

    valid = {"easy", "medium", "hard", "null"}
    if difficulty and difficulty.lower() not in valid:
        await interaction.response.send_message(
            f"Difficulty must be one of: {', '.join(valid)}", ephemeral=True
        )
        return

    await interaction.response.send_message("Posting trivia now...", ephemeral=True)
    await post_trivia(difficulty.lower() if difficulty else None)

# ================== MODERATION ==================

@bot.tree.command(name="ban", description="Ban a member from the server")
@app_commands.default_permissions(ban_members=True)
@app_commands.describe(member="Member to ban", reason="Reason for the ban")
async def ban_member(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided",
):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message(
            embed=moderation_error("You need the **Ban Members** permission."),
            ephemeral=True,
        )
        return

    if not interaction.guild.me.guild_permissions.ban_members:
        await interaction.response.send_message(
            embed=moderation_error("I need the **Ban Members** permission."),
            ephemeral=True,
        )
        return

    error = can_moderate_member(interaction, member)
    if error:
        await interaction.response.send_message(
            embed=moderation_error(error),
            ephemeral=True,
        )
        return

    try:
        try:
            await member.send(
                f"You were banned from **{interaction.guild.name}**.\n"
                f"**Reason:** {reason}"
            )
        except discord.Forbidden:
            pass

        await member.ban(reason=f"{interaction.user} ({interaction.user.id}): {reason}")

        embed = discord.Embed(
            title="🔨 Member Banned",
            color=discord.Color.red(),
        )
        embed.add_field(name="Member", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)

        await interaction.response.send_message(embed=embed)

    except discord.Forbidden:
        await interaction.response.send_message(
            embed=moderation_error("Discord refused the ban. Check my role position and permissions."),
            ephemeral=True,
        )


@bot.tree.command(name="kick", description="Kick a member from the server")
@app_commands.default_permissions(kick_members=True)
@app_commands.describe(member="Member to kick", reason="Reason for the kick")
async def kick_member(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided",
):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message(
            embed=moderation_error("You need the **Kick Members** permission."),
            ephemeral=True,
        )
        return

    if not interaction.guild.me.guild_permissions.kick_members:
        await interaction.response.send_message(
            embed=moderation_error("I need the **Kick Members** permission."),
            ephemeral=True,
        )
        return

    error = can_moderate_member(interaction, member)
    if error:
        await interaction.response.send_message(
            embed=moderation_error(error),
            ephemeral=True,
        )
        return

    try:
        try:
            await member.send(
                f"You were kicked from **{interaction.guild.name}**.\n"
                f"**Reason:** {reason}"
            )
        except discord.Forbidden:
            pass

        await member.kick(reason=f"{interaction.user} ({interaction.user.id}): {reason}")

        embed = discord.Embed(
            title="👢 Member Kicked",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Member", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)

        await interaction.response.send_message(embed=embed)

    except discord.Forbidden:
        await interaction.response.send_message(
            embed=moderation_error("Discord refused the kick. Check my role position and permissions."),
            ephemeral=True,
        )


@bot.tree.command(name="timeout", description="Temporarily timeout a member")
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(
    member="Member to timeout",
    minutes="Timeout duration in minutes (1 to 40320)",
    reason="Reason for the timeout",
)
async def timeout_member(
    interaction: discord.Interaction,
    member: discord.Member,
    minutes: int,
    reason: str = "No reason provided",
):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message(
            embed=moderation_error("You need the **Moderate Members** permission."),
            ephemeral=True,
        )
        return

    if not interaction.guild.me.guild_permissions.moderate_members:
        await interaction.response.send_message(
            embed=moderation_error("I need the **Moderate Members** permission."),
            ephemeral=True,
        )
        return

    if not 1 <= minutes <= 40320:
        await interaction.response.send_message(
            embed=moderation_error("Duration must be between **1 minute** and **28 days**."),
            ephemeral=True,
        )
        return

    error = can_moderate_member(interaction, member)
    if error:
        await interaction.response.send_message(
            embed=moderation_error(error),
            ephemeral=True,
        )
        return

    until = datetime.utcnow() + timedelta(minutes=minutes)

    try:
        try:
            await member.send(
                f"You were timed out in **{interaction.guild.name}** for **{minutes} minute(s)**.\n"
                f"**Reason:** {reason}"
            )
        except discord.Forbidden:
            pass

        await member.timeout(
            until,
            reason=f"{interaction.user} ({interaction.user.id}): {reason}",
        )

        embed = discord.Embed(
            title="⏳ Member Timed Out",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Member", value=f"{member.mention}\n`{member.id}`", inline=True)
        embed.add_field(name="Duration", value=f"{minutes} minute(s)", inline=True)
        embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(
            name="Ends",
            value=f"<t:{int(until.timestamp())}:F>",
            inline=False,
        )

        await interaction.response.send_message(embed=embed)

    except discord.Forbidden:
        await interaction.response.send_message(
            embed=moderation_error("Discord refused the timeout. Check my role position and permissions."),
            ephemeral=True,
        )


@bot.tree.command(name="untimeout", description="Remove a member's timeout")
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(member="Member whose timeout should be removed", reason="Reason")
async def untimeout_member(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "Timeout removed by moderator",
):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message(
            embed=moderation_error("You need the **Moderate Members** permission."),
            ephemeral=True,
        )
        return

    if not interaction.guild.me.guild_permissions.moderate_members:
        await interaction.response.send_message(
            embed=moderation_error("I need the **Moderate Members** permission."),
            ephemeral=True,
        )
        return

    error = can_moderate_member(interaction, member)
    if error:
        await interaction.response.send_message(
            embed=moderation_error(error),
            ephemeral=True,
        )
        return

    if not member.is_timed_out():
        await interaction.response.send_message(
            embed=moderation_error(f"{member.mention} is not currently timed out."),
            ephemeral=True,
        )
        return

    await member.timeout(
        None,
        reason=f"{interaction.user} ({interaction.user.id}): {reason}",
    )

    embed = discord.Embed(
        title="✅ Timeout Removed",
        description=f"{member.mention}'s timeout was removed by {interaction.user.mention}.",
        color=discord.Color.green(),
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="purge", description="Delete recent messages in this channel")
@app_commands.default_permissions(manage_messages=True)
@app_commands.describe(
    amount="How many messages to delete (1 to 100)",
    member="Only delete messages from this member (optional)",
)
async def purge_messages(
    interaction: discord.Interaction,
    amount: int,
    member: discord.Member = None,
):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message(
            embed=moderation_error("You need the **Manage Messages** permission."),
            ephemeral=True,
        )
        return

    if not interaction.guild.me.guild_permissions.manage_messages:
        await interaction.response.send_message(
            embed=moderation_error("I need the **Manage Messages** permission."),
            ephemeral=True,
        )
        return

    if not 1 <= amount <= 100:
        await interaction.response.send_message(
            embed=moderation_error("Amount must be between **1** and **100**."),
            ephemeral=True,
        )
        return

    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(
            embed=moderation_error("This command only works in standard text channels."),
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    def check(message: discord.Message) -> bool:
        return member is None or message.author.id == member.id

    deleted = await interaction.channel.purge(
        limit=amount,
        check=check,
        reason=f"{interaction.user} ({interaction.user.id}) used /purge",
    )

    target_text = f" from {member.mention}" if member else ""
    await interaction.followup.send(
        f"🧹 Deleted **{len(deleted)}** message(s){target_text}.",
        ephemeral=True,
    )


@bot.tree.command(name="warn", description="Warn a member and save the warning")
@app_commands.default_permissions(manage_messages=True)
@app_commands.describe(member="Member to warn", reason="Reason for the warning")
async def warn_member(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str,
):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message(
            embed=moderation_error("You need the **Manage Messages** permission."),
            ephemeral=True,
        )
        return

    error = can_moderate_member(interaction, member)
    if error:
        await interaction.response.send_message(
            embed=moderation_error(error),
            ephemeral=True,
        )
        return

    warning_id = await add_warning(
        interaction.guild.id,
        member.id,
        interaction.user.id,
        reason,
    )

    warnings = await get_warnings(interaction.guild.id, member.id)

    try:
        await member.send(
            f"You received a warning in **{interaction.guild.name}**.\n"
            f"**Reason:** {reason}\n"
            f"**Total warnings:** {len(warnings)}"
        )
    except discord.Forbidden:
        pass

    embed = discord.Embed(
        title="⚠️ Member Warned",
        color=discord.Color.gold(),
    )
    embed.add_field(name="Member", value=f"{member.mention}\n`{member.id}`", inline=True)
    embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
    embed.add_field(name="Warning ID", value=f"`{warning_id}`", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text=f"Total warnings for this member: {len(warnings)}")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="warnings", description="View a member's warning history")
@app_commands.default_permissions(manage_messages=True)
@app_commands.describe(member="Member whose warnings you want to view")
async def warnings_member(
    interaction: discord.Interaction,
    member: discord.Member,
):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message(
            embed=moderation_error("You need the **Manage Messages** permission."),
            ephemeral=True,
        )
        return

    warnings = await get_warnings(interaction.guild.id, member.id)

    if not warnings:
        await interaction.response.send_message(
            f"✅ {member.mention} has no saved warnings.",
            ephemeral=True,
        )
        return

    lines = []
    for warning_id, moderator_id, reason, created_at in warnings[:10]:
        try:
            timestamp = int(datetime.fromisoformat(created_at).timestamp())
            date_text = f"<t:{timestamp}:d>"
        except ValueError:
            date_text = created_at

        lines.append(
            f"**#{warning_id}** — {date_text}\n"
            f"Moderator: <@{moderator_id}>\n"
            f"Reason: {reason}"
        )

    embed = discord.Embed(
        title=f"⚠️ Warnings — {member.display_name}",
        description="\n\n".join(lines),
        color=discord.Color.gold(),
    )
    embed.set_footer(
        text=f"Showing {min(len(warnings), 10)} of {len(warnings)} warning(s)"
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="clearwarnings", description="Remove all saved warnings for a member")
@app_commands.default_permissions(manage_messages=True)
@app_commands.describe(member="Member whose warnings should be cleared")
async def clear_warnings(
    interaction: discord.Interaction,
    member: discord.Member,
):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message(
            embed=moderation_error("You need the **Manage Messages** permission."),
            ephemeral=True,
        )
        return

    error = can_moderate_member(interaction, member)
    if error:
        await interaction.response.send_message(
            embed=moderation_error(error),
            ephemeral=True,
        )
        return

    cleared = await clear_member_warnings(interaction.guild.id, member.id)

    if cleared == 0:
        await interaction.response.send_message(
            f"✅ {member.mention} had no warnings to clear.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="🧽 Warnings Cleared",
        description=(
            f"{interaction.user.mention} cleared **{cleared}** warning(s) "
            f"for {member.mention}."
        ),
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed)

# ================== ADMIN ==================

@bot.tree.command(name="addhoney", description=f"[Admin] Add {CURRENCY} to a user")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="User", amount="Amount to add")
async def addhoney(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount == 0:
        await interaction.response.send_message("Amount cannot be zero.", ephemeral=True)
        return
    user = await add_honey(member.id, amount)
    await check_and_assign_roles(member, user["honey"])
    embed = discord.Embed(
        title="🛠️ Admin Action",
        description=(
            f"{interaction.user.mention} added **{amount}** {EMOJI} to {member.mention}.\n"
            f"New balance: **{user['honey']}** {EMOJI}"
        ),
        color=discord.Color.dark_gold(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="removehoney", description=f"[Admin] Remove {CURRENCY} from a user")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="User", amount="Amount to remove")
async def removehoney(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("Amount must be positive.", ephemeral=True)
        return
    user = await get_user(member.id)
    remove_amt = min(amount, user["honey"])
    new_user = await add_honey(member.id, -remove_amt)
    embed = discord.Embed(
        title="🛠️ Admin Action",
        description=(
            f"{interaction.user.mention} removed **{remove_amt}** {EMOJI} from {member.mention}.\n"
            f"New balance: **{new_user['honey']}** {EMOJI}"
        ),
        color=discord.Color.dark_red(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="sethoney", description=f"[Admin] Set a user's {CURRENCY}")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(member="User", amount="New balance")
async def sethoney(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount < 0:
        await interaction.response.send_message("Amount cannot be negative.", ephemeral=True)
        return
    user = await set_honey(member.id, amount)
    await check_and_assign_roles(member, user["honey"])
    embed = discord.Embed(
        title="🛠️ Admin Action",
        description=(
            f"{interaction.user.mention} set {member.mention}'s balance to **{amount}** {EMOJI}.\n"
            f"Current balance: **{user['honey']}** {EMOJI}"
        ),
        color=discord.Color.dark_gold(),
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="help", description="Show Hive bot commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🐝 The Hive Bot — Commands",
        description="Ethical hacking & teaching community bot",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="💰 Economy",
        value=(
            "`/balance` — Check Honey + next rank\n"
            "`/daily` — Claim daily reward\n"
            "`/work` — Earn Honey (cooldown)\n"
            "`/pay` — Send Honey\n"
            "`/leaderboard` — Top holders\n"
            "`/ranks` — Role rewards"
        ),
        inline=False,
    )
    embed.add_field(
        name="🧠 Trivia",
        value=(
            f"**{len(QUESTIONS)}** cyber / programming questions\n"
            f"Posts randomly every **{TRIVIA_INTERVAL_MIN}–{TRIVIA_INTERVAL_MAX} min**\n"
            "Type the answer in chat — first correct wins!\n"
            "Difficulties: 🟢 easy · 🟡 medium · 🔴 hard · 💀 null\n"
            "`/trivia [difficulty]` — force a question (mods)"
        ),
        inline=False,
    )
    embed.add_field(
        name="🛡️ Admin",
        value="`/addhoney` `/removehoney` `/sethoney`",
        inline=False,
    )
    embed.set_footer(text="The Hive • Learn • Hack Ethically • Level Up")
    await interaction.response.send_message(embed=embed)


# ================== RUN ==================
if __name__ == "__main__":
    bot.run(TOKEN)
