import os
import random
import asyncio
from collections import Counter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler
)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")

games = {}

ROLES = {
    "citizen": "👤 Citizen",
    "killer": "🔪 Killer",
    "police": "👮 Police",
    "thief": "🕵️ Thief",
}

class Game:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.players = {}  # user_id -> {"name": str, "role": str, "alive": bool}
        self.phase = "lobby"
        self.started = False
        self.night_actions = {}
        self.votes = {}
        self.task = None

    def alive_ids(self):
        return [uid for uid, p in self.players.items() if p["alive"]]

    def alive_role_count(self, role):
        return sum(
            1 for p in self.players.values()
            if p["alive"] and p["role"] == role
        )

    def winner(self):
        killers = self.alive_role_count("killer")
        non_killers = sum(
            1 for p in self.players.values()
            if p["alive"] and p["role"] != "killer"
        )
        if killers == 0 and self.started:
            return "👤 Citizens win!"
        if killers >= non_killers and killers > 0:
            return "🔪 Killer wins!"
        return None


def name_of(user):
    return user.full_name or user.username or str(user.id)


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    return member.status in ("administrator", "creator")


async def cmd_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in games and games[chat_id].started:
        await update.message.reply_text("🎮 Game is already running.")
        return

    games[chat_id] = Game(chat_id)
    await update.message.reply_text(
        "🎮 Novel Mafia Game created!\n\n"
        "ဝင်ချင်သူတွေ /join လုပ်ပါ။\n"
        "Admin က /startgame လုပ်ရင် Game စပါမယ်။\n\n"
        "Minimum players: 4"
    )


async def cmd_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or game.started:
        await update.message.reply_text("❌ Game lobby မရှိပါ သို့မဟုတ် Game စပြီးပါပြီ။ /game လုပ်ပါ။")
        return

    user = update.effective_user
    if user.id in game.players:
        await update.message.reply_text("✅ မင်းက Game ထဲဝင်ပြီးသားပါ။")
        return

    game.players[user.id] = {
        "name": name_of(user),
        "username": (user.username or "").lower(),
        "role": None,
        "alive": True,
    }
    await update.message.reply_text(
        f"✅ {name_of(user)} joined!\n"
        f"👥 Players: {len(game.players)}"
    )


async def cmd_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = games.get(update.effective_chat.id)
    if not game or game.started:
        return
    uid = update.effective_user.id
    if uid in game.players:
        del game.players[uid]
        await update.message.reply_text("🚪 Game ကနေ ထွက်ပြီးပါပြီ။")


def make_roles(n):
    # Balanced simple setup.
    killers = max(1, n // 5)
    police = 1 if n >= 5 else 0
    thief = 1 if n >= 6 else 0
    citizens = n - killers - police - thief
    roles = (
        ["killer"] * killers
        + ["police"] * police
        + ["thief"] * thief
        + ["citizen"] * citizens
    )
    random.shuffle(roles)
    return roles


async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game:
        await update.message.reply_text("❌ အရင် /game လုပ်ပါ။")
        return

    if not await is_admin(update, context):
        await update.message.reply_text("⛔ Admin only.")
        return

    if len(game.players) < 4:
        await update.message.reply_text("❌ အနည်းဆုံး 4 ယောက်လိုပါတယ်။")
        return

    roles = make_roles(len(game.players))
    for uid, role in zip(game.players.keys(), roles):
        game.players[uid]["role"] = role

    game.started = True
    game.phase = "night"

    # Send roles privately.
    failed = []
    for uid, p in game.players.items():
        try:
            await context.bot.send_message(
                uid,
                f"🎭 Your Role: {ROLES[p['role']]}\n\n"
                "Group ထဲမှာ Role ကို မပြောပါနဲ့။"
            )
        except Exception:
            failed.append(p["name"])

    await update.message.reply_text(
        "🌙 NIGHT 1 စပါပြီ!\n\n"
        "🔪 Killer: /kill USER_ID\n"
        "👮 Police: /check USER_ID\n"
        "🕵️ Thief: /steal USER_ID\n\n"
        "Action command တွေကို Bot Private Chat ထဲကနေ ပို့ပါ။\n"
        "နောက်တစ်ဆင့်မှာ /day ကို Admin က ခေါ်နိုင်ပါတယ်။"
    )
    if failed:
        await update.message.reply_text(
            "⚠️ Role DM မပို့နိုင်သူရှိပါတယ်။ Bot ကို အရင် /start လုပ်ထားရပါမယ်။"
        )


def target_ok(game, actor_id, target_id):
    return (
        target_id in game.players
        and game.players[target_id]["alive"]
        and target_id != actor_id
    )


async def private_only(update):
    return update.effective_chat.type == "private"


async def cmd_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await private_only(update):
        await update.message.reply_text("🔒 ဒီ command ကို Bot Private Chat ထဲမှာ သုံးပါ။")
        return

    # Find game containing this player.
    game = next((g for g in games.values() if uid in g.players and g.started), None)
    if not game or game.phase != "night":
        await update.message.reply_text("❌ အခု Killer action လုပ်လို့မရသေးပါ။")
        return
    if game.players[uid]["role"] != "killer" or not game.players[uid]["alive"]:
        await update.message.reply_text("⛔ မင်းမှာ ဒီ Ability မရှိပါ။")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("အသုံးပြုပုံ: /kill USER_ID")
        return
    target = int(context.args[0])
    if not target_ok(game, uid, target):
        await update.message.reply_text("❌ Target မမှန်ပါ။")
        return
    game.night_actions["kill"] = target
    await update.message.reply_text("✅ Kill target သတ်မှတ်ပြီးပါပြီ။")


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await private_only(update):
        await update.message.reply_text("🔒 Private Chat ထဲမှာ သုံးပါ။")
        return
    game = next((g for g in games.values() if uid in g.players and g.started), None)
    if not game or game.phase != "night":
        await update.message.reply_text("❌ အခု Check လုပ်လို့မရသေးပါ။")
        return
    if game.players[uid]["role"] != "police" or not game.players[uid]["alive"]:
        await update.message.reply_text("⛔ မင်းမှာ Police Ability မရှိပါ။")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("အသုံးပြုပုံ: /check USER_ID")
        return
    target = int(context.args[0])
    if not target_ok(game, uid, target):
        await update.message.reply_text("❌ Target မမှန်ပါ။")
        return
    role = game.players[target]["role"]
    game.night_actions["check"] = target
    await update.message.reply_text(
        f"🔎 {game.players[target]['name']} ရဲ့ Role = {ROLES[role]}"
    )


async def cmd_steal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await private_only(update):
        await update.message.reply_text("🔒 Private Chat ထဲမှာ သုံးပါ။")
        return
    game = next((g for g in games.values() if uid in g.players and g.started), None)
    if not game or game.phase != "night":
        await update.message.reply_text("❌ အခု Steal လုပ်လို့မရသေးပါ။")
        return
    if game.players[uid]["role"] != "thief" or not game.players[uid]["alive"]:
        await update.message.reply_text("⛔ မင်းမှာ Thief Ability မရှိပါ။")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("အသုံးပြုပုံ: /steal USER_ID")
        return
    target = int(context.args[0])
    if not target_ok(game, uid, target):
        await update.message.reply_text("❌ Target မမှန်ပါ။")
        return

    target_role = game.players[target]["role"]
    # Thief learns the target's role; no role swapping in this simple version.
    game.night_actions["steal"] = target
    await update.message.reply_text(
        f"🕵️ You stole information from {game.players[target]['name']}.\n"
        f"🎭 Their Role: {ROLES[target_role]}"
    )


async def cmd_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or not game.started:
        await update.message.reply_text("❌ Game မစသေးပါ။")
        return
    if not await is_admin(update, context):
        await update.message.reply_text("⛔ Admin only.")
        return
    if game.phase != "night":
        await update.message.reply_text("❌ အခု Day phase မဟုတ်ပါ။")
        return

    kill_target = game.night_actions.get("kill")
    if kill_target in game.players and game.players[kill_target]["alive"]:
        game.players[kill_target]["alive"] = False
        victim = game.players[kill_target]["name"]
        msg = f"☀️ DAY!\n\n🔪 ဒီညမှာ {victim} သေဆုံးသွားပါတယ်။"
    else:
        msg = "☀️ DAY!\n\nဒီညမှာ ဘယ်သူမှ မသေပါဘူး။"

    game.phase = "day"
    game.votes = {}
    game.night_actions = {}
    await update.message.reply_text(msg)

    winner = game.winner()
    if winner:
        await end_game(update, game, winner)
        return

    await update.message.reply_text(
        "🗳️ Vote လုပ်ပါ။\n"
        "အသုံးပြုပုံ: /vote USER_ID\n\n"
        "ပြီးရင် Admin က /endvote လုပ်ပါ။"
    )


def resolve_vote_target(game, update):
    # 1) /vote @username
    if update.message and update.message.text:
        parts = update.message.text.split()
        if len(parts) >= 2:
            value = parts[1].strip()
            if value.startswith("@"):
                username = value[1:].lower()
                for uid, player in game.players.items():
                    if player.get("username") == username:
                        return uid

    # 2) Reply to a player's message, then send /vote
    reply = update.message.reply_to_message if update.message else None
    if reply and reply.from_user:
        uid = reply.from_user.id
        if uid in game.players:
            return uid

    return None


async def cmd_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or not game.started or game.phase != "day":
        await update.message.reply_text("❌ အခု Vote phase မဟုတ်ပါ။")
        return
    voter = update.effective_user.id
    if voter not in game.players or not game.players[voter]["alive"]:
        await update.message.reply_text("❌ အသက်ရှင်နေတဲ့ Player ပဲ Vote လုပ်နိုင်ပါတယ်။")
        return

    alive = [(uid, p) for uid, p in game.players.items() if p["alive"] and uid != voter]
    if not alive:
        await update.message.reply_text("❌ Vote လုပ်ဖို့ Target မရှိပါ။")
        return

    keyboard = []
    row = []
    for i, (uid, player) in enumerate(alive, 1):
        row.append(InlineKeyboardButton(player["name"], callback_data=f"vote:{chat_id}:{uid}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await update.message.reply_text(
        "🗳️ ဘယ်သူကို Vote မလဲ?\n\nခလုတ်ကိုနှိပ်ပြီး Vote ပေးပါ။",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def vote_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, chat_id_s, target_s = query.data.split(":")
        chat_id, target = int(chat_id_s), int(target_s)
    except Exception:
        await query.edit_message_text("❌ Vote button မမှန်ပါ။")
        return

    game = games.get(chat_id)
    voter = query.from_user.id
    if not game or not game.started or game.phase != "day":
        await query.answer("Vote phase မရှိတော့ပါ။", show_alert=True)
        return
    if voter not in game.players or not game.players[voter]["alive"]:
        await query.answer("အသက်ရှင်နေတဲ့ Player ပဲ Vote လုပ်နိုင်ပါတယ်။", show_alert=True)
        return
    if target not in game.players or not game.players[target]["alive"] or target == voter:
        await query.answer("ဒီ Player ကို Vote မလုပ်နိုင်ပါ။", show_alert=True)
        return

    game.votes[voter] = target
    await query.answer(f"✅ {game.players[target]['name']} ကို Vote ပေးပြီးပါပြီ။")
    await query.message.reply_text(
        f"🗳️ {game.players[voter]['name']} → {game.players[target]['name']} ကို Vote ပေးလိုက်ပါပြီ။"
    )


async def cmd_endvote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game or not game.started or game.phase != "day":
        await update.message.reply_text("❌ Vote phase မဟုတ်ပါ။")
        return
    if not await is_admin(update, context):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not game.votes:
        await update.message.reply_text("❌ Vote မရှိသေးပါ။")
        return

    counts = Counter(game.votes.values())
    result_lines = ["🗳️ VOTE RESULT", ""]
    ordered = sorted(counts.items(), key=lambda x: (-x[1], game.players[x[0]]["name"].lower()))
    for uid, count in ordered:
        result_lines.append(f"👤 {game.players[uid]['name']} — {count} vote{'s' if count != 1 else ''}")

    highest = max(counts.values())
    winners = [uid for uid, c in counts.items() if c == highest]
    if len(winners) > 1:
        result_lines += ["", "🤝 VOTE TIE!", "", "❌ ဘယ်သူမှ မထွက်ပါ။"]
    else:
        target = winners[0]
        game.players[target]["alive"] = False
        result_lines += [
            "",
            f"🔴 {game.players[target]['name']} has been eliminated!",
            "",
            f"🎭 Role: {ROLES[game.players[target]['role']]}"
        ]

    await update.message.reply_text("\n".join(result_lines))

    winner = game.winner()
    if winner:
        await end_game(update, game, winner)
        return

    game.phase = "night"
    game.night_actions = {}
    game.votes = {}
    await update.message.reply_text(
        "🌙 NIGHT ပြန်စပါပြီ!\n\n"
        "🔪 Killer: /kill USER_ID\n"
        "👮 Police: /check USER_ID\n"
        "🕵️ Thief: /steal USER_ID\n\n"
        "ပြီးရင် Admin က /day လုပ်ပါ။"
    )


async def end_game(update, game, result):
    lines = ["🏆 NOVEL MAFIA GAME OVER!", "", result, "", "🎭 ALL ROLES REVEALED", ""]
    for p in game.players.values():
        status = "🟢 Alive" if p["alive"] else "💀 Dead"
        lines.append(f"{status} — {p['name']} — {ROLES[p['role']]}")
    await update.effective_chat.send_message("\n".join(lines))
    game.started = False
    game.phase = "finished"


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = games.get(update.effective_chat.id)
    if not game:
        await update.message.reply_text("❌ Game မရှိပါ။")
        return
    lines = [f"🎮 Phase: {game.phase}", f"👥 Players: {len(game.players)}"]
    for uid, p in game.players.items():
        status = "🟢" if p["alive"] else "💀"
        lines.append(f"{status} {p['name']} — ID: {uid}")
    await update.message.reply_text("\n".join(lines))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not await is_admin(update, context):
        await update.message.reply_text("⛔ Admin only.")
        return
    games.pop(chat_id, None)
    await update.message.reply_text("🛑 Game cancelled.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 NOVEL MAFIA GAME COMMANDS\n\n"
        "/game - Game lobby ဖန်တီး\n"
        "/join - Game ဝင်\n"
        "/leave - Lobby ကနေထွက်\n"
        "/startgame - Admin: Game စ\n"
        "/status - Player/phase ကြည့်\n"
        "/day - Admin: Night ပြီး Day စ\n"
        "/vote - Reply လုပ်ထားတဲ့ Player ကို Vote\n/vote @username - Username နဲ့ Vote\n"
        "/endvote - Admin: Vote ပိတ်\n"
        "/cancel - Admin: Game ဖျက်\n\n"
        "🔒 Private commands:\n"
        "/kill USER_ID\n"
        "/check USER_ID\n"
        "/steal USER_ID"
    )


def main():
    app = Application.builder().token(TOKEN).build()

    handlers = [
        CommandHandler("game", cmd_game),
        CommandHandler("join", cmd_join),
        CommandHandler("leave", cmd_leave),
        CommandHandler("startgame", cmd_startgame),
        CommandHandler("kill", cmd_kill),
        CommandHandler("check", cmd_check),
        CommandHandler("steal", cmd_steal),
        CommandHandler("day", cmd_day),
        CommandHandler("vote", cmd_vote),
        CommandHandler("endvote", cmd_endvote),
        CommandHandler("status", cmd_status),
        CommandHandler("cancel", cmd_cancel),
        CommandHandler("help", cmd_help),
    ]
    for h in handlers:
        app.add_handler(h)
    app.add_handler(CallbackQueryHandler(vote_button))

    print("Novel Mafia Game Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
