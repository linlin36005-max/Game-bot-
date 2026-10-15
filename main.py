import os
import re
import random
import sqlite3
import logging
from datetime import date, datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "0") or "0")
SPAWN_EVERY = int(os.getenv("SPAWN_EVERY", "100") or "100")
DB_PATH = os.getenv("DB_PATH", "characters.db")

RARITIES = {
    "mythical": "🔴 Mythical",
    "normal": "🟠 Normal",
    "legend": "🟡 Legend",
    "regular": "🔵 ပုံမှန်ကတ်",
    "supreme": "👑 အမြင့်ဆုံးကတ်",
}
RARITY_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔴 Mythical", callback_data="rarity:mythical"),
     InlineKeyboardButton("🟠 Normal", callback_data="rarity:normal")],
    [InlineKeyboardButton("🟡 Legend", callback_data="rarity:legend"),
     InlineKeyboardButton("🔵 ပုံမှန်ကတ်", callback_data="rarity:regular")],
    [InlineKeyboardButton("👑 အမြင့်ဆုံးကတ်", callback_data="rarity:supreme")],
])

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode=WAL")
conn.executescript("""
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    image_file_id TEXT,
    hint TEXT DEFAULT '',
    rarity TEXT DEFAULT '🔵 ပုံမှန်ကတ်'
);
CREATE TABLE IF NOT EXISTS collections (
    user_id INTEGER NOT NULL,
    username TEXT,
    character_id INTEGER NOT NULL,
    caught_at TEXT NOT NULL,
    UNIQUE(user_id, character_id),
    FOREIGN KEY(character_id) REFERENCES characters(id)
);
CREATE TABLE IF NOT EXISTS group_state (
    chat_id INTEGER PRIMARY KEY,
    message_count INTEGER NOT NULL DEFAULT 0,
    active_character_id INTEGER,
    spawned_at TEXT
);
CREATE TABLE IF NOT EXISTS daily_claims (
    user_id INTEGER PRIMARY KEY,
    claimed_on TEXT NOT NULL,
    coins INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS wallets (
    user_id INTEGER PRIMARY KEY,
    coins INTEGER NOT NULL DEFAULT 0
);
""")
# Migrate databases created by older versions.
cols = {row["name"] for row in conn.execute("PRAGMA table_info(characters)").fetchall()}
if "rarity" not in cols:
    conn.execute("ALTER TABLE characters ADD COLUMN rarity TEXT DEFAULT '🔵 ပုံမှန်ကတ်'")
conn.commit()

STARTERS = [
    ("Mika", "A cheerful adventurer"),
    ("Luna", "A mysterious moon-themed character"),
    ("Ren", "A quiet swordsman"),
    ("Aiko", "A kind-hearted heroine"),
    ("Kira", "A bold and energetic character"),
]
for name, hint in STARTERS:
    conn.execute(
        "INSERT OR IGNORE INTO characters(name, hint, rarity) VALUES (?, ?, ?)",
        (name, hint, "🔵 ပုံမှန်ကတ်")
    )
conn.commit()


def is_owner(user_id: int) -> bool:
    return OWNER_ID != 0 and user_id == OWNER_ID


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def get_character(character_id):
    return conn.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    owner_line = (
        "\nOwner commands:\n/add character — add with photo + rarity + name\n"
        "/addcharacter Name — quick add by replying to a photo\n"
        "/characters — list characters\n/setspawn 100 — spawn interval"
    ) if is_owner(user.id) else ""
    await update.effective_message.reply_text(
        "✨ Welcome to Novel Character Catcher Bot!\n\n"
        "🎭 Catch characters by guessing their names when one appears in a group.\n"
        "Commands:\n"
        "/collection — your characters\n"
        "/rank — top collectors\n"
        "/daily — claim daily coins\n"
        "/gift @username Character Name — gift a character\n"
        "/trade @username Character Name — send a trade offer\n"
        "/help — show help"
        + owner_line
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    rows = conn.execute("""
        SELECT c.name, c.rarity, col.caught_at FROM collections col
        JOIN characters c ON c.id=col.character_id
        WHERE col.user_id=? ORDER BY col.caught_at DESC
    """, (user.id,)).fetchall()
    if not rows:
        await update.effective_message.reply_text("Your collection is empty. Catch a character in a group first!")
        return
    lines = [f"🎒 {user.first_name}'s Collection ({len(rows)})"]
    lines += [f"• {r['rarity']} — {r['name']}" for r in rows]
    await update.effective_message.reply_text("\n".join(lines))


async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = conn.execute("""
        SELECT col.user_id, col.username, COUNT(*) AS total
        FROM collections col GROUP BY col.user_id
        ORDER BY total DESC, col.user_id ASC LIMIT 10
    """).fetchall()
    if not rows:
        await update.effective_message.reply_text("No characters have been caught yet.")
        return
    lines = ["🏆 Novel Catcher Leaderboard"]
    for i, r in enumerate(rows, 1):
        label = ("@" + r["username"]) if r["username"] else str(r["user_id"])
        lines.append(f"{i}. {label} — {r['total']} character(s)")
    await update.effective_message.reply_text("\n".join(lines))


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    today = date.today().isoformat()
    row = conn.execute("SELECT claimed_on FROM daily_claims WHERE user_id=?", (user.id,)).fetchone()
    if row and row["claimed_on"] == today:
        await update.effective_message.reply_text("🌤️ You already claimed today's reward. Come back tomorrow!")
        return
    reward = random.randint(50, 150)
    conn.execute("INSERT OR IGNORE INTO wallets(user_id, coins) VALUES (?, 0)", (user.id,))
    conn.execute("UPDATE wallets SET coins=coins+? WHERE user_id=?", (reward, user.id))
    conn.execute("""
        INSERT INTO daily_claims(user_id, claimed_on, coins) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET claimed_on=excluded.claimed_on, coins=excluded.coins
    """, (user.id, today, reward))
    conn.commit()
    total = conn.execute("SELECT coins FROM wallets WHERE user_id=?", (user.id,)).fetchone()["coins"]
    await update.effective_message.reply_text(f"🎁 Daily reward: +{reward} coins!\n💰 Balance: {total} coins")


async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: /gift @username Character Name")
        return
    target_name = context.args[0].lstrip("@")
    char_name = " ".join(context.args[1:]).strip()
    target = conn.execute("SELECT user_id FROM collections WHERE lower(username)=lower(?) LIMIT 1", (target_name,)).fetchone()
    if not target:
        await update.effective_message.reply_text("I couldn't find that user in saved collections. Ask them to catch a character first.")
        return
    target_id = target["user_id"]
    if target_id == user.id:
        await update.effective_message.reply_text("You can't gift a character to yourself.")
        return
    char = conn.execute("SELECT id, name FROM characters WHERE name=? COLLATE NOCASE", (char_name,)).fetchone()
    if not char:
        await update.effective_message.reply_text("Character not found. Check the exact name.")
        return
    owned = conn.execute("SELECT 1 FROM collections WHERE user_id=? AND character_id=?", (user.id, char["id"])).fetchone()
    if not owned:
        await update.effective_message.reply_text("You don't own that character.")
        return
    already = conn.execute("SELECT 1 FROM collections WHERE user_id=? AND character_id=?", (target_id, char["id"])).fetchone()
    if already:
        await update.effective_message.reply_text("That user already owns this character; duplicates aren't enabled.")
        return
    conn.execute("DELETE FROM collections WHERE user_id=? AND character_id=?", (user.id, char["id"]))
    conn.execute("INSERT INTO collections(user_id, username, character_id, caught_at) VALUES (?, ?, ?, ?)",
                 (target_id, target_name, char["id"], datetime.now(timezone.utc).isoformat()))
    conn.commit()
    await update.effective_message.reply_text(f"🎁 {char['name']} was gifted to @{target_name}!")


async def trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.effective_message.reply_text("Usage: /trade @username Character Name\nThis version sends a trade offer request; it doesn't auto-transfer.")
        return
    target = context.args[0]
    char_name = " ".join(context.args[1:])
    await update.effective_message.reply_text(
        f"🤝 Trade offer prepared for {target}: {char_name}\n"
        "This starter build doesn't auto-transfer on trade offers. If both players agree, use /gift @username Character Name."
    )


async def addcharacter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    if not is_owner(user.id):
        await msg.reply_text("⛔ Owner only.")
        return

    # /add character starts the guided flow. /addcharacter Name keeps the quick legacy flow.
    args = list(context.args)
    if msg.text and msg.text.split()[0].split("@")[0].casefold() == "/add":
        if args and args[0].casefold() == "character":
            context.user_data["add_character"] = {"step": "photo"}
            await msg.reply_text("🖼️ အရင်ဆုံး Character ပုံကို ပို့ပေးပါ။ ပုံပို့ပြီးရင် Rarity ရွေးရပါမယ်။")
            return
        await msg.reply_text("အသုံးပြုပုံ: /add character")
        return

    if not args:
        await msg.reply_text("အသုံးပြုပုံ: ပုံကို Reply လုပ်ပြီး /addcharacter Sakura လို့ရေးပါ။\nRarity ကို 🔵 ပုံမှန်ကတ် အဖြစ်ထားပါမယ်။")
        return
    name = " ".join(args).strip()
    replied = msg.reply_to_message
    image_id = None
    if replied and replied.photo:
        image_id = replied.photo[-1].file_id
    elif replied and replied.document and (replied.document.mime_type or "").startswith("image/"):
        image_id = replied.document.file_id
    if not image_id:
        await msg.reply_text("ပုံကို Reply လုပ်ပြီး /addcharacter CharacterName လို့ ပို့ပါ။")
        return
    try:
        conn.execute("INSERT INTO characters(name, image_file_id, hint, rarity) VALUES (?, ?, '', ?)",
                     (name, image_id, RARITIES["regular"]))
        conn.commit()
        await msg.reply_text(f"✅ Character ထည့်ပြီးပါပြီ!\n🖼️ ပုံ: သိမ်းပြီး\n🏷️ Rank: {RARITIES['regular']}\n🎴 နာမည်: {name}")
    except sqlite3.IntegrityError:
        conn.execute("UPDATE characters SET image_file_id=?, rarity=? WHERE name=? COLLATE NOCASE",
                     (image_id, RARITIES["regular"], name))
        conn.commit()
        await msg.reply_text(f"✅ {name} ရဲ့ပုံကို Update လုပ်ပြီး Rank ကို {RARITIES['regular']} ထားလိုက်ပါပြီ။")


async def receive_character_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_owner(user.id):
        return
    flow = context.user_data.get("add_character")
    if not flow or flow.get("step") != "photo":
        return
    msg = update.effective_message
    if msg.photo:
        image_id = msg.photo[-1].file_id
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        image_id = msg.document.file_id
    else:
        return
    flow["image_file_id"] = image_id
    flow["step"] = "rarity"
    await msg.reply_text("🏷️ ဒီ Character ရဲ့ Rank ကို ရွေးပေးပါ။", reply_markup=RARITY_KEYBOARD)


async def rarity_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    if not is_owner(user.id):
        await query.edit_message_text("⛔ Owner only.")
        return
    flow = context.user_data.get("add_character")
    if not flow or flow.get("step") != "rarity":
        await query.edit_message_text("ဒီ Add Character လုပ်ငန်းစဉ် မရှိတော့ပါ။ /add character နဲ့ ပြန်စပါ။")
        return
    key = query.data.split(":", 1)[1]
    flow["rarity"] = RARITIES.get(key, RARITIES["regular"])
    flow["step"] = "name"
    await query.edit_message_text(
        f"ရွေးထားတဲ့ Rank: {flow['rarity']}\n\n🎴 အခု Character နာမည်ကို ပို့ပေးပါ။"
    )


async def add_character_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    flow = context.user_data.get("add_character")
    if not user or not is_owner(user.id) or not flow or flow.get("step") != "name":
        return False
    name = (update.effective_message.text or "").strip()
    if not name or name.startswith("/"):
        await update.effective_message.reply_text("Character နာမည်ကို စာသားနဲ့ ပို့ပေးပါ။")
        return True
    try:
        conn.execute(
            "INSERT INTO characters(name, image_file_id, hint, rarity) VALUES (?, ?, '', ?)",
            (name, flow["image_file_id"], flow["rarity"])
        )
        conn.commit()
        await update.effective_message.reply_text(
            f"✅ Character ကို Add လုပ်ပြီးပါပြီ!\n\n"
            f"🎴 နာမည်: {name}\n{flow['rarity']}\n🖼️ ပုံ: သိမ်းပြီး"
        )
    except sqlite3.IntegrityError:
        conn.execute(
            "UPDATE characters SET image_file_id=?, rarity=? WHERE name=? COLLATE NOCASE",
            (flow["image_file_id"], flow["rarity"], name)
        )
        conn.commit()
        await update.effective_message.reply_text(
            f"✅ {name} ရှိပြီးသားဖြစ်လို့ ပုံနဲ့ Rank ကို Update လုပ်ပြီးပါပြီ။\n{flow['rarity']}"
        )
    context.user_data.pop("add_character", None)
    return True




async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handled = await add_character_name(update, context)
    if not handled:
        await guess_message(update, context)


async def characters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.effective_message.reply_text("⛔ Owner only.")
        return
    rows = conn.execute("SELECT id, name, hint, image_file_id, rarity FROM characters ORDER BY name").fetchall()
    if not rows:
        await update.effective_message.reply_text("📚 Character စာရင်းမရှိသေးပါ။ /add character နဲ့ ထည့်နိုင်ပါတယ်။")
        return
    await update.effective_message.reply_text(
        f"📚 Character စီမံခန့်ခွဲမှု ({len(rows)} ခု)\n"
        "ကတ်တစ်ခုချင်းစီရဲ့ ခလုတ်ကိုနှိပ်ပြီး Rank ပြောင်းနိုင်သလို မကြိုက်တဲ့ကတ်ကို ဖျက်နိုင်ပါတယ်။"
    )
    for r in rows[:50]:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏷️ Rank ပြောင်း", callback_data=f"manage:rank:{r['id']}"),
             InlineKeyboardButton("🗑️ ကတ်ဖျက်", callback_data=f"manage:delete:{r['id']}")]
        ])
        text = f"🎴 {r['name']}\nလက်ရှိ Rank: {r['rarity']}"
        if r["hint"]:
            text += f"\n💡 {r['hint']}"
        if r["image_file_id"]:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=r["image_file_id"],
                caption=text,
                reply_markup=keyboard,
            )
        else:
            await update.effective_message.reply_text(text, reply_markup=keyboard)


async def manage_character_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(query.from_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return
    parts = query.data.split(":")
    if len(parts) != 3:
        return
    action, char_id_text = parts[1], parts[2]
    if not char_id_text.isdigit():
        return
    char_id = int(char_id_text)
    char = get_character(char_id)
    if not char:
        await query.edit_message_caption(caption="ဒီကတ်ကို မတွေ့တော့ပါ။") if query.message.photo else await query.edit_message_text("ဒီကတ်ကို မတွေ့တော့ပါ။")
        return

    if action == "rank":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Mythical", callback_data=f"setrank:{char_id}:mythical"),
             InlineKeyboardButton("🟠 Normal", callback_data=f"setrank:{char_id}:normal")],
            [InlineKeyboardButton("🟡 Legend", callback_data=f"setrank:{char_id}:legend"),
             InlineKeyboardButton("🔵 ပုံမှန်ကတ်", callback_data=f"setrank:{char_id}:regular")],
            [InlineKeyboardButton("👑 အမြင့်ဆုံးကတ်", callback_data=f"setrank:{char_id}:supreme")],
        ])
        text = f"🎴 {char['name']}\nလက်ရှိ Rank: {char['rarity']}\nRank အသစ်ကို ရွေးပါ။"
        if query.message.photo:
            await query.edit_message_caption(caption=text, reply_markup=keyboard)
        else:
            await query.edit_message_text(text, reply_markup=keyboard)
    elif action == "delete":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ ဖျက်မယ်", callback_data=f"confirmdelete:{char_id}"),
            InlineKeyboardButton("❌ မဖျက်တော့ဘူး", callback_data="canceldelete"),
        ]])
        text = f"⚠️ '{char['name']}' ကတ်ကို ဖျက်မှာ သေချာပါသလား?\nဒီကတ်ကို Collection တွေထဲကပါ ဖယ်ရှားပါမယ်။"
        if query.message.photo:
            await query.edit_message_caption(caption=text, reply_markup=keyboard)
        else:
            await query.edit_message_text(text, reply_markup=keyboard)


async def setspawn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SPAWN_EVERY
    if not is_owner(update.effective_user.id):
        await update.effective_message.reply_text("⛔ Owner only.")
        return
    if not context.args or not context.args[0].isdigit() or int(context.args[0]) < 1:
        await update.effective_message.reply_text("Usage: /setspawn 100")
        return
    SPAWN_EVERY = int(context.args[0])
    await update.effective_message.reply_text(f"✅ Character spawn interval set to every {SPAWN_EVERY} group messages (until restart).")


async def set_character_rank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(query.from_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return
    parts = query.data.split(":")
    if len(parts) != 3 or not parts[1].isdigit():
        return
    char_id = int(parts[1])
    rarity_key = parts[2]
    rarity = RARITIES.get(rarity_key)
    char = get_character(char_id)
    if not rarity or not char:
        await query.answer("ကတ်ကို မတွေ့ပါ။", show_alert=True)
        return
    conn.execute("UPDATE characters SET rarity=? WHERE id=?", (rarity, char_id))
    conn.commit()
    text = f"✅ Rank ပြောင်းပြီးပါပြီ!\n🎴 {char['name']}\n🏷️ Rank အသစ်: {rarity}"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🏷️ Rank ထပ်ပြောင်း", callback_data=f"manage:rank:{char_id}"),
        InlineKeyboardButton("🗑️ ကတ်ဖျက်", callback_data=f"manage:delete:{char_id}")
    ]])
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=keyboard)
    else:
        await query.edit_message_text(text, reply_markup=keyboard)


async def confirm_delete_character_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(query.from_user.id):
        await query.answer("⛔ Owner only.", show_alert=True)
        return
    char_id_text = query.data.split(":", 1)[1]
    if not char_id_text.isdigit():
        return
    char_id = int(char_id_text)
    char = get_character(char_id)
    if not char:
        await query.answer("ကတ်ကို မတွေ့ပါ။", show_alert=True)
        return
    conn.execute("DELETE FROM collections WHERE character_id=?", (char_id,))
    conn.execute("UPDATE group_state SET active_character_id=NULL WHERE active_character_id=?", (char_id,))
    conn.execute("DELETE FROM characters WHERE id=?", (char_id,))
    conn.commit()
    text = f"🗑️ '{char['name']}' ကတ်ကို ဖျက်ပြီးပါပြီ။ Collection တွေထဲကပါ ဖယ်ရှားပြီးပါပြီ။"
    if query.message.photo:
        await query.edit_message_caption(caption=text, reply_markup=None)
    else:
        await query.edit_message_text(text, reply_markup=None)


async def cancel_delete_character_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("ဖျက်ခြင်းကို ပယ်ဖျက်လိုက်ပါပြီ။")
    if query.message.photo:
        await query.edit_message_caption(caption="❌ ကတ်ဖျက်ခြင်းကို ပယ်ဖျက်လိုက်ပါပြီ။", reply_markup=None)
    else:
        await query.edit_message_text("❌ ကတ်ဖျက်ခြင်းကို ပယ်ဖျက်လိုက်ပါပြီ။", reply_markup=None)


async def guess_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not user or user.is_bot or chat.type not in ("group", "supergroup"):
        return
    if not msg.text or msg.text.startswith("/"):
        return

    state = conn.execute("SELECT * FROM group_state WHERE chat_id=?", (chat.id,)).fetchone()
    if not state:
        conn.execute("INSERT INTO group_state(chat_id, message_count) VALUES (?, 0)", (chat.id,))
        conn.commit()
        state = conn.execute("SELECT * FROM group_state WHERE chat_id=?", (chat.id,)).fetchone()

    active_id = state["active_character_id"]
    if active_id:
        char = get_character(active_id)
        if char and norm(msg.text) == norm(char["name"]):
            owned = conn.execute("SELECT 1 FROM collections WHERE user_id=? AND character_id=?", (user.id, active_id)).fetchone()
            if owned:
                await msg.reply_text(f"🎯 Correct, {user.first_name}! But you already own {char['name']}.")
            else:
                conn.execute("INSERT INTO collections(user_id, username, character_id, caught_at) VALUES (?, ?, ?, ?)",
                             (user.id, user.username, active_id, datetime.now(timezone.utc).isoformat()))
                conn.execute("INSERT OR IGNORE INTO wallets(user_id, coins) VALUES (?, 0)", (user.id,))
                conn.execute("UPDATE wallets SET coins=coins+10 WHERE user_id=?", (user.id,))
                conn.execute("UPDATE group_state SET active_character_id=NULL, spawned_at=NULL WHERE chat_id=?", (chat.id,))
                conn.commit()
                await msg.reply_text(
                    f"🎉 Correct! {user.first_name} caught {char['name']}!\n"
                    f"{char['rarity']}\n+10 coins"
                )
            return

    count = state["message_count"] + 1
    conn.execute("UPDATE group_state SET message_count=? WHERE chat_id=?", (count, chat.id))
    conn.commit()
    if count % SPAWN_EVERY != 0:
        return

    pool = conn.execute("SELECT * FROM characters").fetchall()
    if not pool:
        return
    char = random.choice(pool)
    conn.execute("UPDATE group_state SET active_character_id=?, spawned_at=? WHERE chat_id=?",
                 (char["id"], datetime.now(timezone.utc).isoformat(), chat.id))
    conn.commit()
    caption = (
        "✨ A wild character appeared!\n"
        "Guess the character's name by sending it in the chat.\n"
        f"🏷️ Rank: {char['rarity']}"
    )
    if char["hint"]:
        caption += f"\n💡 Hint: {char['hint']}"
    if char["image_file_id"]:
        await context.bot.send_photo(chat_id=chat.id, photo=char["image_file_id"], caption=caption)
    else:
        await context.bot.send_message(chat_id=chat.id, text=caption + "\n\n⚠️ ဒီ Character မှာ ပုံမရှိသေးပါ။ Owner က ပုံထည့်ပေးပါ။")


async def post_init(app: Application):
    if not BOT_TOKEN:
        log.warning("BOT_TOKEN environment variable is missing.")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is required. Add it in Railway Variables.")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("collection", collection))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("gift", gift))
    app.add_handler(CommandHandler("trade", trade))
    app.add_handler(CommandHandler("addcharacter", addcharacter))
    app.add_handler(CommandHandler("add", addcharacter))
    app.add_handler(CommandHandler("characters", characters_command))
    app.add_handler(CommandHandler("setspawn", setspawn))
    app.add_handler(CallbackQueryHandler(rarity_selected, pattern=r"^rarity:"))
    app.add_handler(CallbackQueryHandler(manage_character_callback, pattern=r"^manage:"))
    app.add_handler(CallbackQueryHandler(set_character_rank_callback, pattern=r"^setrank:"))
    app.add_handler(CallbackQueryHandler(confirm_delete_character_callback, pattern=r"^confirmdelete:"))
    app.add_handler(CallbackQueryHandler(cancel_delete_character_callback, pattern=r"^canceldelete$"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, receive_character_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    log.info("Novel Character Catcher Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
