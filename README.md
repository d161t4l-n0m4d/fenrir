# 🐝 The Hive Bot

Discord bot for **The Hive** — an ethical hacking & teaching community.

### Features
- **Honey Economy** 🍯  
  Daily rewards, work command, pay other members, leaderboard
- **Cybersecurity Trivia**  
  Automatic quiz every 20 minutes in a channel. Correct answers earn Honey.
- **Automatic Role Rewards**  
  Members receive roles when they reach Honey milestones (Worker Bee → Queen's Guard)
- **Admin tools**  
  Add / remove / set Honey for moderation

---

## 🚀 Quick Setup on Wispbyte

### 1. Create the Discord Bot
1. Go to https://discord.com/developers/applications
2. **New Application** → name it `The Hive` (or whatever you like)
3. Go to **Bot** → Add Bot → Reset Token → **copy the token**
4. Under **Privileged Gateway Intents** enable:
   - ✅ Message Content Intent
   - ✅ Server Members Intent
5. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions:
     - Manage Roles
     - Send Messages
     - Embed Links
     - Read Message History
     - Use Slash Commands
6. Copy the generated URL and invite the bot to your server.

> **Important**: The bot's highest role must be **above** the roles it will assign.

### 2. Create Roles in your Discord server
Create these roles (or edit the names/IDs later in config):

| Role Name       | Suggested Honey |
|-----------------|-----------------|
| Worker Bee      | 200             |
| Scout           | 500             |
| Guardian        | 1000            |
| Hive Elder      | 2500            |
| Queen's Guard   | 5000            |

Copy each role's ID (Developer Mode → right-click role → Copy ID).

### 3. Prepare the files
1. Download / clone this folder.
2. Copy `config.example.json` → rename to **`config.json`**
3. Edit `config.json`:

```json
{
  "prefix": "!",
  "currency_name": "Honey",
  "currency_emoji": "🍯",
  "trivia_channel_id": 123456789012345678,   ← your trivia channel ID
  "trivia_interval_minutes": 20,
  "trivia_reward": 50,
  "trivia_time_seconds": 45,
  "daily_amount": 100,
  "work_min": 15,
  "work_max": 40,
  "work_cooldown_seconds": 3600,
  "role_rewards": [
    {
      "honey_required": 200,
      "role_id": 1111111111111111111,
      "name": "Worker Bee"
    },
    {
      "honey_required": 500,
      "role_id": 2222222222222222222,
      "name": "Scout"
    },
    {
      "honey_required": 1000,
      "role_id": 3333333333333333333,
      "name": "Guardian"
    },
    {
      "honey_required": 2500,
      "role_id": 4444444444444444444,
      "name": "Hive Elder"
    },
    {
      "honey_required": 5000,
      "role_id": 5555555555555555555,
      "name": "Queen's Guard"
    }
  ]
}
```

### 4. Secure your token (important)

Never put your real bot token inside `bot.py` or `config.json`.

**Option A – Recommended on Wispbyte (Environment Variable)**  
In the Wispbyte panel → **Startup** / **Environment** add:

| Key         | Value                |
|-------------|----------------------|
| `BOT_TOKEN` | `your_real_bot_token`|

**Option B – Local / .env file**  
1. Copy `.env.example` → rename it to **`.env`**
2. Open `.env` and replace the placeholder:

```env
BOT_TOKEN=your_real_bot_token_here
```

The bot loads this file automatically via `python-dotenv`.  
`.env` is already in `.gitignore` so it will never be committed.

### 5. Deploy on Wispbyte

1. Go to https://wispbyte.com/client and sign up / log in.
2. **Create Server** → Free Plan → choose **Python** runtime.
3. Open the server → **Files**.
4. Upload these files:
   - `bot.py`
   - `requirements.txt`
   - `questions.json`
   - `config.json`  ← the one you edited
   - (optional) `.env` if you prefer the file method instead of panel env vars
5. Go to **Startup**:
   - **Startup Command**: `python bot.py`
   - **Packages** (if needed): `discord.py aiosqlite python-dotenv`
6. Add the `BOT_TOKEN` environment variable (see step 4).
7. Click **Start**.

The bot should come online and sync slash commands within a few seconds.

---

## 📋 Commands

| Command          | Description                              | Permission   |
|------------------|------------------------------------------|--------------|
| `/balance`       | Check Honey balance + next rank          | Everyone     |
| `/daily`         | Claim daily Honey                        | Everyone     |
| `/work`          | Earn Honey (1 hour cooldown)             | Everyone     |
| `/pay`           | Send Honey to another member             | Everyone     |
| `/leaderboard`   | Top 10 Honey holders                     | Everyone     |
| `/ranks`         | Show all role rewards                    | Everyone     |
| `/help`          | List all commands                        | Everyone     |
| `/addhoney`      | Add Honey to a user                      | Administrator|
| `/removehoney`   | Remove Honey from a user                 | Administrator|
| `/sethoney`      | Set exact Honey amount                   | Administrator|
| `/trivia`        | Force a new trivia round                 | Manage Messages |

---

## 🧠 Trivia

- Runs automatically every **20 minutes** (configurable).
- Posts in the channel you set as `trivia_channel_id`.
- Users answer by typing **A**, **B**, **C** or **D**.
- Correct answers within the time window earn Honey.
- Multiple people can win the same question.

You can add/edit questions in `questions.json`. Format:

```json
{
  "question": "What does MFA stand for?",
  "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
  "answer": "A",
  "explanation": "Optional explanation shown after the answer."
}
```

---

## 🔧 Tips

- Make sure the bot role is **higher** than the reward roles in Server Settings → Roles.
- The bot needs **Manage Roles** permission.
- Data is stored in `hive.db` (SQLite). It will be created automatically.
- To change trivia frequency, edit `trivia_interval_minutes` in `config.json` and restart the bot.


---

**The Hive** — Learn. Hack Ethically. Level Up. 🐝
