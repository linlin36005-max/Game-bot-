# Novel Character Catcher Bot

## Owner setup
Set these Railway Variables:
- `BOT_TOKEN`: Telegram bot token
- `OWNER_ID`: your numeric Telegram user ID
- `SPAWN_EVERY`: optional, default `100`
- `DB_PATH`: optional, default `characters.db`

## Add a character (guided flow)
1. Owner sends `/add character` in the bot private chat.
2. Send the character photo to the bot.
3. Tap a rarity button:
   - 🔴 Mythical
   - 🟠 Normal
   - 🟡 Legend
   - 🔵 ပုံမှန်ကတ်
   - 👑 အမြင့်ဆုံးကတ်
4. Send the character name as a text message.
5. Bot saves the photo, rarity, and name together. If the name already exists, its photo and rarity are updated.

The quick legacy method is also supported: reply to a photo with `/addcharacter Sakura`. This sets the rarity to 🔵 ပုံမှန်ကတ်.

## Commands
- `/start`, `/help`
- `/collection`
- `/rank`
- `/daily`
- `/gift @username Character Name`
- `/trade @username Character Name` (offer notice only; no automatic trade)
- Owner: `/add character`, `/addcharacter Name` (reply to photo), `/characters` (each card has Rank-change and Delete buttons), `/setspawn 100`

## Railway deployment
1. Upload this folder to a GitHub repository.
2. Create a Railway project from that repository.
3. Add the environment variables above.
4. The Procfile starts `python main.py`.
5. To keep character and collection data across redeploys, attach a Railway Volume and set `DB_PATH` to a file path on that volume, for example `/data/characters.db`.

Add the bot to your Telegram group and ensure it can send messages and photos. To count ordinary group messages, disable BotFather privacy mode or make the bot an administrator.
