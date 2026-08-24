"""Economy V2 foundation for the Fenrir/Hive discord bot.

By Ꮆ卄ㄖ丂ㄒ
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands


RARITY_ORDER = ("common", "uncommon", "rare", "epic", "legendary", "mythic", "null")
RARITY_COLORS = {
    "common": 0x95A5A6,
    "uncommon": 0x2ECC71,
    "rare": 0x3498DB,
    "epic": 0x9B59B6,
    "legendary": 0xF1C40F,
    "mythic": 0xE74C3C,
    "null": 0x111111,
}
RARITY_EMOJIS = {
    "common": "⚪",
    "uncommon": "🟢",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🟠",
    "mythic": "🔴",
    "null": "⚫",
}

BANK_TIERS = (
    {"tier": 1, "name": "Starter Vault", "cost": 0, "capacity": 5_000, "interest": 0.001},
    {"tier": 2, "name": "Copper Vault", "cost": 2_500, "capacity": 25_000, "interest": 0.0025},
    {"tier": 3, "name": "Silver Vault", "cost": 12_500, "capacity": 100_000, "interest": 0.005},
    {"tier": 4, "name": "Gold Vault", "cost": 60_000, "capacity": 500_000, "interest": 0.008},
    {"tier": 5, "name": "Quantum Vault", "cost": 300_000, "capacity": 2_500_000, "interest": 0.011},
    {"tier": 6, "name": "Null Vault", "cost": 1_500_000, "capacity": None, "interest": 0.015},
)
BANK_BY_TIER = {row["tier"]: row for row in BANK_TIERS}

SKILLS = ("hacking", "programming", "networking", "crypto", "social_engineering", "luck")
SKILL_LABELS = {
    "hacking": "Hacking",
    "programming": "Programming",
    "networking": "Networking",
    "crypto": "Cryptography",
    "social_engineering": "Social Engineering",
    "luck": "Luck",
}

ACHIEVEMENTS = (
    {"key": "first_deposit", "name": "Vault Initiate", "description": "Deposit coins into your bank.", "target": 1, "reward": 100},
    {"key": "wealth_10k", "name": "Five Digits", "description": "Reach 10,000 net worth.", "target": 10_000, "reward": 500},
    {"key": "level_10", "name": "Operator", "description": "Reach level 10.", "target": 10, "reward": 300},
    {"key": "bank_tier_3", "name": "Secure Storage", "description": "Upgrade to bank tier 3.", "target": 3, "reward": 750},
    {"key": "collector_10", "name": "Collector", "description": "Own 10 inventory items.", "target": 10, "reward": 350},
    {"key": "prestige_1", "name": "Rebooted", "description": "Prestige once.", "target": 1, "reward": 2_000},
)
ACHIEVEMENT_BY_KEY = {item["key"]: item for item in ACHIEVEMENTS}

ITEM_CATALOG = (
    ("energy_drink", "Energy Drink", "common", "consumable", 120, "xp_boost", 0.10, 3_600),
    ("focus_pills", "Focus Pills", "uncommon", "consumable", 450, "skill_boost", 0.10, 7_200),
    ("lucky_charm", "Lucky Charm", "rare", "consumable", 1_200, "luck_boost", 0.20, 14_400),
    ("crypto_stimulant", "Crypto Stimulant", "epic", "consumable", 4_000, "bank_interest_boost", 0.25, 86_400),
    ("null_fragment", "Null Fragment", "null", "collectible", 100_000, None, 0, 0),
    ("usb_drive", "Encrypted USB Drive", "common", "material", 80, None, 0, 0),
    ("thermal_paste", "Thermal Paste", "common", "material", 110, None, 0, 0),
    ("cable_bundle", "Cable Bundle", "common", "material", 100, None, 0, 0),
    ("code_snippet", "Code Snippet", "common", "material", 150, None, 0, 0),
    ("packet_capture", "Packet Capture", "uncommon", "material", 400, None, 0, 0),
    ("proxy_chain", "Proxy Chain", "uncommon", "tool", 600, None, 0, 0),
    ("vulnerability_report", "Vulnerability Report", "uncommon", "material", 750, None, 0, 0),
    ("debugger", "Portable Debugger", "uncommon", "tool", 850, None, 0, 0),
    ("network_map", "Network Map", "rare", "tool", 1_500, None, 0, 0),
    ("cipher_key", "Cipher Key", "rare", "material", 1_800, None, 0, 0),
    ("exploit_notes", "Exploit Notes", "rare", "material", 2_200, None, 0, 0),
    ("zero_day_token", "Zero-Day Token", "epic", "collectible", 5_000, None, 0, 0),
    ("quantum_chip", "Quantum Chip", "epic", "material", 7_500, None, 0, 0),
    ("red_team_kit", "Red Team Kit", "epic", "tool", 8_500, None, 0, 0),
    ("root_certificate", "Root Certificate", "legendary", "collectible", 18_000, None, 0, 0),
    ("ai_core", "AI Core", "legendary", "material", 22_000, None, 0, 0),
    ("darknet_relay", "Darknet Relay", "legendary", "tool", 30_000, None, 0, 0),
    ("mythic_terminal", "Mythic Terminal", "mythic", "tool", 70_000, None, 0, 0),
    ("singularity_key", "Singularity Key", "mythic", "collectible", 95_000, None, 0, 0),
    ("void_compiler", "Void Compiler", "null", "tool", 250_000, None, 0, 0),
    ("null_cipher", "Null Cipher", "null", "collectible", 500_000, None, 0, 0),
    ("honeycomb_chip", "Honeycomb Chip", "common", "material", 125, None, 0, 0),
    ("firewall_rule", "Firewall Rulebook", "uncommon", "tool", 550, None, 0, 0),
    ("sandbox_token", "Sandbox Token", "uncommon", "collectible", 650, None, 0, 0),
    ("linux_iso", "Hardened Linux ISO", "rare", "tool", 1_300, None, 0, 0),
    ("rfid_cloner", "RFID Lab Cloner", "rare", "tool", 2_400, None, 0, 0),
    ("forensics_kit", "Forensics Kit", "epic", "tool", 6_500, None, 0, 0),
    ("incident_playbook", "Incident Playbook", "epic", "material", 5_500, None, 0, 0),
    ("blue_team_badge", "Blue Team Badge", "legendary", "badge", 20_000, None, 0, 0),
    ("red_team_badge", "Red Team Badge", "legendary", "badge", 20_000, None, 0, 0),
    ("hive_crown", "Hive Crown", "mythic", "badge", 90_000, None, 0, 0),
    ("null_badge", "Null Sector Badge", "null", "badge", 500_000, None, 0, 0),
    ("packet_sniffer", "Packet Sniffer", "common", "tool", 250, None, 0, 0),
    ("password_salt", "Password Salt", "common", "material", 90, None, 0, 0),
    ("secure_enclave", "Secure Enclave", "rare", "tool", 2_800, None, 0, 0),
    ("hsm_module", "HSM Module", "legendary", "tool", 25_000, None, 0, 0),
    ("void_shard", "Void Shard", "null", "collectible", 300_000, None, 0, 0),
)
ITEMS = {
    item[0]: {
        "key": item[0], "name": item[1], "rarity": item[2], "type": item[3],
        "value": item[4], "effect_type": item[5], "effect_value": item[6], "duration": item[7],
    }
    for item in ITEM_CATALOG
}

PETS = (
    ("packet_pup", "Packet Pup", "common", "A curious helper that boosts XP gains by 2%.", "xp", 0.02),
    ("script_kitten", "Script Kitten", "uncommon", "A nimble companion that boosts programming rewards by 3%.", "programming", 0.03),
    ("cipher_owl", "Cipher Owl", "rare", "A watchful familiar that boosts cryptography rewards by 5%.", "crypto", 0.05),
    ("null_fox", "Null Fox", "mythic", "A rare companion that boosts all earning rewards by 8%.", "all", 0.08),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat()


def level_xp_required(level: int) -> int:
    return 100 + (level - 1) * 75


def total_level_xp(level: int) -> int:
    return sum(level_xp_required(i) for i in range(1, level))


def fmt(value: int | float) -> str:
    return f"{int(value):,}"


class EconomyV2:
    def __init__(self, db_path: str, currency_name: str = "Hive coin", currency_emoji: str = "🍯"):
        self.db_path = db_path
        self.currency_name = currency_name
        self.currency_emoji = currency_emoji

    async def init_db(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS economy_v2_users (
                user_id INTEGER PRIMARY KEY,
                wallet INTEGER NOT NULL DEFAULT 500,
                bank INTEGER NOT NULL DEFAULT 0,
                bank_tier INTEGER NOT NULL DEFAULT 1,
                level INTEGER NOT NULL DEFAULT 1,
                xp INTEGER NOT NULL DEFAULT 0,
                prestige INTEGER NOT NULL DEFAULT 0,
                prestige_points INTEGER NOT NULL DEFAULT 0,
                last_interest_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS economy_v2_skills (
                user_id INTEGER NOT NULL,
                skill TEXT NOT NULL,
                level INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, skill)
            );
            CREATE TABLE IF NOT EXISTS economy_v2_inventory (
                user_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
                PRIMARY KEY (user_id, item_key)
            );
            CREATE TABLE IF NOT EXISTS economy_v2_effects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                effect_key TEXT NOT NULL,
                multiplier REAL NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS economy_v2_achievements (
                user_id INTEGER NOT NULL,
                achievement_key TEXT NOT NULL,
                unlocked_at TEXT NOT NULL,
                PRIMARY KEY (user_id, achievement_key)
            );
            CREATE TABLE IF NOT EXISTS economy_v2_badges (
                user_id INTEGER NOT NULL,
                badge_key TEXT NOT NULL,
                earned_at TEXT NOT NULL,
                PRIMARY KEY (user_id, badge_key)
            );
            CREATE TABLE IF NOT EXISTS economy_v2_pets (
                user_id INTEGER NOT NULL,
                pet_key TEXT NOT NULL,
                equipped INTEGER NOT NULL DEFAULT 0,
                acquired_at TEXT NOT NULL,
                PRIMARY KEY (user_id, pet_key)
            );
            CREATE TABLE IF NOT EXISTS economy_v2_cooldowns (
                user_id INTEGER NOT NULL,
                action_key TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (user_id, action_key)
            );
            CREATE TABLE IF NOT EXISTS economy_v2_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                amount INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_econ_v2_transaction_user ON economy_v2_transactions(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_econ_v2_effect_user ON economy_v2_effects(user_id, expires_at);
            """)
            await db.commit()

    async def ensure_user(self, user_id: int) -> dict[str, Any]:
        now = iso_now()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR IGNORE INTO economy_v2_users
                   (user_id, created_at, updated_at, last_interest_at)
                   VALUES (?, ?, ?, ?)""",
                (user_id, now, now, now),
            )
            for skill in SKILLS:
                await db.execute(
                    "INSERT OR IGNORE INTO economy_v2_skills (user_id, skill) VALUES (?, ?)",
                    (user_id, skill),
                )
            await db.commit()
        return await self.get_user(user_id)

    async def get_user(self, user_id: int) -> dict[str, Any]:
        await self.ensure_user_if_missing(user_id)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM economy_v2_users WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
                return dict(row)

    async def ensure_user_if_missing(self, user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT 1 FROM economy_v2_users WHERE user_id = ?", (user_id,)) as cur:
                exists = await cur.fetchone()
        if not exists:
            await self.ensure_user(user_id)

    async def get_skills(self, user_id: int) -> dict[str, int]:
        await self.ensure_user(user_id)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT skill, level FROM economy_v2_skills WHERE user_id = ?", (user_id,)) as cur:
                return {skill: level for skill, level in await cur.fetchall()}

    async def get_inventory(self, user_id: int, rarity: Optional[str] = None) -> list[tuple[str, int]]:
        await self.ensure_user(user_id)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT item_key, quantity FROM economy_v2_inventory WHERE user_id = ? AND quantity > 0 ORDER BY item_key",
                (user_id,),
            ) as cur:
                rows = await cur.fetchall()
        if rarity:
            return [(key, qty) for key, qty in rows if ITEMS.get(key, {}).get("rarity") == rarity]
        return rows

    async def inventory_count(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COALESCE(SUM(quantity), 0) FROM economy_v2_inventory WHERE user_id = ?", (user_id,)) as cur:
                return int((await cur.fetchone())[0])

    async def add_item(self, user_id: int, item_key: str, quantity: int = 1) -> None:
        if item_key not in ITEMS or quantity <= 0:
            raise ValueError("Invalid item or quantity")
        await self.ensure_user(user_id)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO economy_v2_inventory (user_id, item_key, quantity) VALUES (?, ?, ?)
                   ON CONFLICT(user_id, item_key) DO UPDATE SET quantity = quantity + excluded.quantity""",
                (user_id, item_key, quantity),
            )
            await db.commit()

    async def add_transaction(self, user_id: int, kind: str, amount: int, balance_after: int, metadata: str = "") -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO economy_v2_transactions
                   (user_id, kind, amount, balance_after, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, kind, amount, balance_after, metadata, iso_now()),
            )
            await db.commit()

    async def apply_interest(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        last = datetime.fromisoformat(user["last_interest_at"])
        now = utcnow()
        full_days = max(0, (now - last).days)
        if full_days <= 0 or user["bank"] <= 0:
            return 0
        tier = BANK_BY_TIER[user["bank_tier"]]
        bonus = await self.active_effect_multiplier(user_id, "bank_interest_boost")
        rate = tier["interest"] * bonus
        interest = max(0, math.floor(user["bank"] * ((1 + rate) ** full_days - 1)))
        if interest:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE economy_v2_users SET bank = bank + ?, last_interest_at = ?, updated_at = ? WHERE user_id = ?",
                    (interest, now.isoformat(), now.isoformat(), user_id),
                )
                await db.commit()
            latest = await self.get_user(user_id)
            await self.add_transaction(user_id, "bank_interest", interest, latest["wallet"], f"{full_days} day(s)")
        else:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("UPDATE economy_v2_users SET last_interest_at = ? WHERE user_id = ?", (now.isoformat(), user_id))
                await db.commit()
        return interest

    async def active_effect_multiplier(self, user_id: int, effect_key: str) -> float:
        now = iso_now()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM economy_v2_effects WHERE user_id = ? AND expires_at <= ?", (user_id, now))
            async with db.execute(
                "SELECT COALESCE(MAX(multiplier), 1) FROM economy_v2_effects WHERE user_id = ? AND effect_key = ? AND expires_at > ?",
                (user_id, effect_key, now),
            ) as cur:
                row = await cur.fetchone()
            await db.commit()
        return float(row[0])

    async def deposit(self, user_id: int, amount: int) -> tuple[dict[str, Any], int]:
        if amount <= 0:
            raise ValueError("Amount must be positive")
        interest = await self.apply_interest(user_id)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute("SELECT * FROM economy_v2_users WHERE user_id = ?", (user_id,)) as cur:
                user = dict(await cur.fetchone())
            if user["wallet"] < amount:
                raise ValueError("Insufficient wallet balance")
            tier = BANK_BY_TIER[user["bank_tier"]]
            capacity = tier["capacity"]
            if capacity is not None and user["bank"] + amount > capacity:
                available = max(0, capacity - user["bank"])
                raise ValueError(f"Bank capacity exceeded. Available space: {fmt(available)}")
            await db.execute(
                "UPDATE economy_v2_users SET wallet = wallet - ?, bank = bank + ?, updated_at = ? WHERE user_id = ?",
                (amount, amount, iso_now(), user_id),
            )
            await db.commit()
        user = await self.get_user(user_id)
        await self.add_transaction(user_id, "deposit", -amount, user["wallet"], "wallet -> bank")
        await self.evaluate_achievements(user_id)
        return user, interest

    async def withdraw(self, user_id: int, amount: int) -> tuple[dict[str, Any], int]:
        if amount <= 0:
            raise ValueError("Amount must be positive")
        interest = await self.apply_interest(user_id)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute("SELECT * FROM economy_v2_users WHERE user_id = ?", (user_id,)) as cur:
                user = dict(await cur.fetchone())
            if user["bank"] < amount:
                raise ValueError("Insufficient bank balance")
            await db.execute(
                "UPDATE economy_v2_users SET wallet = wallet + ?, bank = bank - ?, updated_at = ? WHERE user_id = ?",
                (amount, amount, iso_now(), user_id),
            )
            await db.commit()
        user = await self.get_user(user_id)
        await self.add_transaction(user_id, "withdraw", amount, user["wallet"], "bank -> wallet")
        return user, interest

    async def upgrade_bank(self, user_id: int) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
        user = await self.get_user(user_id)
        if user["bank_tier"] >= 6:
            return user, None
        next_tier = BANK_BY_TIER[user["bank_tier"] + 1]
        if user["wallet"] < next_tier["cost"]:
            raise ValueError(f"You need {fmt(next_tier['cost'])} {self.currency_emoji} in your wallet.")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE economy_v2_users SET wallet = wallet - ?, bank_tier = ?, updated_at = ? WHERE user_id = ?",
                (next_tier["cost"], next_tier["tier"], iso_now(), user_id),
            )
            await db.commit()
        user = await self.get_user(user_id)
        await self.add_transaction(user_id, "bank_upgrade", -next_tier["cost"], user["wallet"], next_tier["name"])
        await self.evaluate_achievements(user_id)
        return user, next_tier

    async def use_item(self, user_id: int, item_key: str) -> tuple[dict[str, Any], datetime]:
        item = ITEMS.get(item_key)
        if not item or item["type"] != "consumable" or not item["effect_type"]:
            raise ValueError("That item is not a usable consumable")
        await self.ensure_user(user_id)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT quantity FROM economy_v2_inventory WHERE user_id = ? AND item_key = ?",
                (user_id, item_key),
            ) as cur:
                row = await cur.fetchone()
            if not row or row[0] < 1:
                raise ValueError("You do not own that item")
            await db.execute(
                "UPDATE economy_v2_inventory SET quantity = quantity - 1 WHERE user_id = ? AND item_key = ?",
                (user_id, item_key),
            )
            expiry = utcnow() + timedelta(seconds=item["duration"])
            await db.execute(
                "INSERT INTO economy_v2_effects (user_id, effect_key, multiplier, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, item["effect_type"], 1 + item["effect_value"], expiry.isoformat(), iso_now()),
            )
            await db.commit()
        user = await self.get_user(user_id)
        await self.add_transaction(user_id, "use_item", 0, user["wallet"], item_key)
        return item, expiry

    async def add_xp(self, user_id: int, amount: int) -> tuple[dict[str, Any], int]:
        if amount <= 0:
            return await self.get_user(user_id), 0
        multiplier = await self.active_effect_multiplier(user_id, "xp_boost")
        amount = math.floor(amount * multiplier)
        user = await self.get_user(user_id)
        level = user["level"]
        xp = user["xp"] + amount
        gained = 0
        while xp >= level_xp_required(level):
            xp -= level_xp_required(level)
            level += 1
            gained += 1
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE economy_v2_users SET level = ?, xp = ?, updated_at = ? WHERE user_id = ?",
                (level, xp, iso_now(), user_id),
            )
            await db.commit()
        user = await self.get_user(user_id)
        await self.evaluate_achievements(user_id)
        return user, gained

    async def evaluate_achievements(self, user_id: int) -> list[dict[str, Any]]:
        user = await self.get_user(user_id)
        inv_count = await self.inventory_count(user_id)
        values = {
            "first_deposit": 1 if user["bank"] > 0 else 0,
            "wealth_10k": await self.net_worth(user_id),
            "level_10": user["level"],
            "bank_tier_3": user["bank_tier"],
            "collector_10": inv_count,
            "prestige_1": user["prestige"],
        }
        unlocked: list[dict[str, Any]] = []
        async with aiosqlite.connect(self.db_path) as db:
            for achievement in ACHIEVEMENTS:
                if values[achievement["key"]] < achievement["target"]:
                    continue
                async with db.execute(
                    "SELECT 1 FROM economy_v2_achievements WHERE user_id = ? AND achievement_key = ?",
                    (user_id, achievement["key"]),
                ) as cur:
                    if await cur.fetchone():
                        continue
                await db.execute(
                    "INSERT INTO economy_v2_achievements (user_id, achievement_key, unlocked_at) VALUES (?, ?, ?)",
                    (user_id, achievement["key"], iso_now()),
                )
                await db.execute(
                    "UPDATE economy_v2_users SET wallet = wallet + ?, updated_at = ? WHERE user_id = ?",
                    (achievement["reward"], iso_now(), user_id),
                )
                unlocked.append(achievement)
            await db.commit()
        if unlocked:
            user = await self.get_user(user_id)
            for achievement in unlocked:
                await self.add_transaction(user_id, "achievement_reward", achievement["reward"], user["wallet"], achievement["key"])
        return unlocked

    async def achievements(self, user_id: int) -> set[str]:
        await self.ensure_user(user_id)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT achievement_key FROM economy_v2_achievements WHERE user_id = ?", (user_id,)) as cur:
                return {row[0] for row in await cur.fetchall()}

    async def net_worth(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        inventory = await self.get_inventory(user_id)
        item_value = sum(ITEMS.get(key, {}).get("value", 0) * quantity for key, quantity in inventory)
        return int(user["wallet"] + user["bank"] + item_value)

    async def prestige(self, user_id: int) -> tuple[dict[str, Any], int]:
        user = await self.get_user(user_id)
        if user["level"] < 50:
            raise ValueError("You must reach level 50 before prestiging.")
        awarded = max(1, user["level"] // 10)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE economy_v2_users
                   SET level = 1, xp = 0, prestige = prestige + 1,
                       prestige_points = prestige_points + ?, updated_at = ?
                   WHERE user_id = ?""",
                (awarded, iso_now(), user_id),
            )
            await db.commit()
        user = await self.get_user(user_id)
        await self.add_transaction(user_id, "prestige", 0, user["wallet"], f"+{awarded} prestige points")
        await self.evaluate_achievements(user_id)
        return user, awarded

    async def leaderboard(self, category: str, limit: int = 10) -> list[tuple[int, int]]:
        if category == "level":
            query = "SELECT user_id, level FROM economy_v2_users ORDER BY prestige DESC, level DESC, xp DESC LIMIT ?"
        elif category == "prestige":
            query = "SELECT user_id, prestige FROM economy_v2_users ORDER BY prestige DESC, level DESC LIMIT ?"
        elif category == "total":
            query = "SELECT user_id, wallet + bank AS score FROM economy_v2_users ORDER BY score DESC LIMIT ?"
        else:
            raise ValueError("Invalid leaderboard category")
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(query, (limit,)) as cur:
                return [(int(row[0]), int(row[1])) for row in await cur.fetchall()]


class WithdrawConfirmView(discord.ui.View):
    def __init__(self, economy: EconomyV2, owner_id: int, amount: int):
        super().__init__(timeout=45)
        self.economy = economy
        self.owner_id = owner_id
        self.amount = amount

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the command user can confirm this withdrawal.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm withdrawal", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        try:
            user, interest = await self.economy.withdraw(self.owner_id, self.amount)
        except ValueError as exc:
            await interaction.response.edit_message(content=f"❌ {exc}", embed=None, view=None)
            return
        suffix = f" Interest credited first: {fmt(interest)} {self.economy.currency_emoji}." if interest else ""
        await interaction.response.edit_message(
            content=(f"✅ Withdrew **{fmt(self.amount)}** {self.economy.currency_emoji}. "
                     f"Wallet: **{fmt(user['wallet'])}** {self.economy.currency_emoji}.{suffix}"),
            embed=None,
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Withdrawal cancelled.", embed=None, view=None)
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


class EconomyV2Cog(commands.Cog):
    def __init__(self, bot: commands.Bot, economy: EconomyV2):
        self.bot = bot
        self.economy = economy

    def embed(self, title: str, description: str = "", color: int = 0xF1C40F) -> discord.Embed:
        return discord.Embed(title=title, description=description, color=color, timestamp=utcnow())

    @app_commands.command(name="profilev2", description="View a complete Economy V2 profile")
    @app_commands.describe(member="Member to view (optional)")
    async def profilev2(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        target = member or interaction.user
        await self.economy.apply_interest(target.id)
        user = await self.economy.get_user(target.id)
        skills = await self.economy.get_skills(target.id)
        achievements = await self.economy.achievements(target.id)
        net_worth = await self.economy.net_worth(target.id)
        tier = BANK_BY_TIER[user["bank_tier"]]
        xp_needed = level_xp_required(user["level"])
        e = self.embed(f"🧬 Economy V2 Profile — {target.display_name}", color=0x9B59B6)
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="Wealth", value=f"Wallet: **{fmt(user['wallet'])}** {self.economy.currency_emoji}\nBank: **{fmt(user['bank'])}** {self.economy.currency_emoji}\nNet worth: **{fmt(net_worth)}** {self.economy.currency_emoji}", inline=True)
        e.add_field(name="Progression", value=f"Level: **{user['level']}**\nXP: **{fmt(user['xp'])}/{fmt(xp_needed)}**\nPrestige: **{user['prestige']}** ({user['prestige_points']} PP)", inline=True)
        e.add_field(name="Bank", value=f"Tier {tier['tier']} — **{tier['name']}**\nDaily interest: **{tier['interest'] * 100:.2f}%**\nCapacity: **{'∞' if tier['capacity'] is None else fmt(tier['capacity'])}**", inline=False)
        skill_text = " · ".join(f"{SKILL_LABELS[key]} {skills.get(key, 0)}" for key in SKILLS)
        e.add_field(name="Skills", value=skill_text, inline=False)
        e.add_field(name="Achievements", value=f"**{len(achievements)}/{len(ACHIEVEMENTS)}** unlocked", inline=True)
        e.add_field(name="Inventory", value=f"**{await self.economy.inventory_count(target.id)}** item(s)", inline=True)
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="balance2", description="View wallet, bank tier, and pending interest")
    @app_commands.describe(member="Member to view (optional)")
    async def balance2(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        target = member or interaction.user
        interest = await self.economy.apply_interest(target.id)
        user = await self.economy.get_user(target.id)
        tier = BANK_BY_TIER[user["bank_tier"]]
        cap = "∞" if tier["capacity"] is None else fmt(tier["capacity"])
        e = self.embed(f"🏦 Balance V2 — {target.display_name}", color=0x3498DB)
        e.add_field(name="Wallet", value=f"**{fmt(user['wallet'])}** {self.economy.currency_emoji}", inline=True)
        e.add_field(name="Bank", value=f"**{fmt(user['bank'])}/{cap}** {self.economy.currency_emoji}", inline=True)
        e.add_field(name="Net Worth", value=f"**{fmt(await self.economy.net_worth(target.id))}** {self.economy.currency_emoji}", inline=True)
        e.add_field(name="Vault", value=f"Tier {tier['tier']} — **{tier['name']}**\nDaily interest: **{tier['interest'] * 100:.2f}%**", inline=False)
        if interest:
            e.set_footer(text=f"Credited {fmt(interest)} {self.economy.currency_emoji} in bank interest.")
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="deposit2", description="Deposit wallet coins into your Economy V2 bank")
    @app_commands.describe(amount="Amount to deposit")
    async def deposit2(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1]) -> None:
        try:
            user, interest = await self.economy.deposit(interaction.user.id, amount)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        text = f"✅ Deposited **{fmt(amount)}** {self.economy.currency_emoji}. Bank: **{fmt(user['bank'])}** {self.economy.currency_emoji}."
        if interest:
            text += f" Credited **{fmt(interest)}** interest first."
        await interaction.response.send_message(text)

    @app_commands.command(name="withdraw2", description="Withdraw Economy V2 bank coins with confirmation")
    @app_commands.describe(amount="Amount to withdraw")
    async def withdraw2(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1]) -> None:
        user = await self.economy.get_user(interaction.user.id)
        if user["bank"] < amount:
            await interaction.response.send_message("❌ Insufficient bank balance.", ephemeral=True)
            return
        view = WithdrawConfirmView(self.economy, interaction.user.id, amount)
        await interaction.response.send_message(
            f"Withdraw **{fmt(amount)}** {self.economy.currency_emoji} from your bank? This request expires in 45 seconds.",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(name="use", description="Use an Economy V2 consumable item")
    @app_commands.describe(item="Catalog item key, e.g. energy_drink")
    async def use(self, interaction: discord.Interaction, item: str) -> None:
        key = item.lower().strip().replace(" ", "_")
        try:
            used, expiry = await self.economy.use_item(interaction.user.id, key)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✅ Used **{used['name']}**. Effect: **{used['effect_type']}** until <t:{int(expiry.timestamp())}:R>."
        )

    @app_commands.command(name="inventory2", description="View Economy V2 inventory")
    @app_commands.describe(rarity="Optional rarity filter")
    @app_commands.choices(rarity=[app_commands.Choice(name=r.title(), value=r) for r in RARITY_ORDER])
    async def inventory2(self, interaction: discord.Interaction, rarity: Optional[app_commands.Choice[str]] = None) -> None:
        inventory = await self.economy.get_inventory(interaction.user.id, rarity.value if rarity else None)
        if not inventory:
            await interaction.response.send_message("Your filtered inventory is empty.", ephemeral=True)
            return
        inventory.sort(key=lambda row: (RARITY_ORDER.index(ITEMS[row[0]]["rarity"]), ITEMS[row[0]]["name"]), reverse=True)
        lines = []
        for key, quantity in inventory[:25]:
            item = ITEMS.get(key)
            if item:
                lines.append(f"{RARITY_EMOJIS[item['rarity']]} **{item['name']}** ×{quantity} — `{item['rarity']}`")
        e = self.embed("🎒 Economy V2 Inventory", "\n".join(lines), 0x2ECC71)
        e.set_footer(text=f"{await self.economy.inventory_count(interaction.user.id)} item(s) total • Showing up to 25")
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="achievements", description="View Economy V2 achievement progress")
    @app_commands.describe(member="Member to view (optional)")
    async def achievements_command(self, interaction: discord.Interaction, member: Optional[discord.Member] = None) -> None:
        target = member or interaction.user
        unlocked = await self.economy.achievements(target.id)
        user = await self.economy.get_user(target.id)
        net_worth = await self.economy.net_worth(target.id)
        inv_count = await self.economy.inventory_count(target.id)
        values = {"first_deposit": 1 if user["bank"] else 0, "wealth_10k": net_worth, "level_10": user["level"], "bank_tier_3": user["bank_tier"], "collector_10": inv_count, "prestige_1": user["prestige"]}
        lines = []
        for achievement in ACHIEVEMENTS:
            status = "✅" if achievement["key"] in unlocked else "🔒"
            lines.append(f"{status} **{achievement['name']}** — {achievement['description']} ({fmt(min(values[achievement['key']], achievement['target']))}/{fmt(achievement['target'])})")
        e = self.embed(f"🏆 Achievements — {target.display_name}", "\n".join(lines), 0xF1C40F)
        e.set_footer(text=f"{len(unlocked)}/{len(ACHIEVEMENTS)} unlocked")
        await interaction.response.send_message(embed=e, ephemeral=target.id != interaction.user.id)

    @app_commands.command(name="leaderboard2", description="View Economy V2 leaderboards")
    @app_commands.describe(category="Leaderboard category")
    @app_commands.choices(category=[
        app_commands.Choice(name="Total wallet + bank", value="total"),
        app_commands.Choice(name="Level", value="level"),
        app_commands.Choice(name="Prestige", value="prestige"),
    ])
    async def leaderboard2(self, interaction: discord.Interaction, category: app_commands.Choice[str]) -> None:
        rows = await self.economy.leaderboard(category.value)
        if not rows:
            await interaction.response.send_message("No Economy V2 profiles exist yet.", ephemeral=True)
            return
        medals = ("🥇", "🥈", "🥉")
        lines = []
        for index, (user_id, score) in enumerate(rows, start=1):
            marker = medals[index - 1] if index <= 3 else f"**{index}.**"
            suffix = self.economy.currency_emoji if category.value == "total" else ("prestige" if category.value == "prestige" else "level")
            lines.append(f"{marker} <@{user_id}> — **{fmt(score)}** {suffix}")
        await interaction.response.send_message(embed=self.embed(f"🏅 Economy V2 Leaderboard — {category.name}", "\n".join(lines), 0xF1C40F))

    @app_commands.command(name="prestige", description="Reset level 50+ for prestige points")
    async def prestige(self, interaction: discord.Interaction) -> None:
        try:
            user, points = await self.economy.prestige(interaction.user.id)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"✨ **Prestige complete!** You are now Prestige **{user['prestige']}** and earned **{points}** prestige point(s). Your level reset to 1."
        )

    @app_commands.command(name="bankupgrade", description="Upgrade your Economy V2 bank tier")
    async def bankupgrade(self, interaction: discord.Interaction) -> None:
        try:
            user, upgraded = await self.economy.upgrade_bank(interaction.user.id)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        if upgraded is None:
            await interaction.response.send_message("✅ Your bank is already at the maximum tier: **Null Vault**.", ephemeral=True)
            return
        cap = "∞" if upgraded["capacity"] is None else fmt(upgraded["capacity"])
        await interaction.response.send_message(
            f"🏦 Upgraded to **Tier {upgraded['tier']} — {upgraded['name']}**. "
            f"Capacity: **{cap}** {self.economy.currency_emoji}; daily interest: **{upgraded['interest'] * 100:.2f}%**."
        )


async def setup_economy_v2(bot: commands.Bot, db_path: str, currency_name: str, currency_emoji: str) -> EconomyV2:
    economy = EconomyV2(db_path, currency_name, currency_emoji)
    await economy.init_db()
    await bot.add_cog(EconomyV2Cog(bot, economy))
    return economy
