# Novel Mafia Game Bot

## Features
- Citizen / Killer / Police / Thief roles
- Group lobby with `/game`, `/join`
- Admin starts game with `/startgame`
- Roles are sent privately
- Night actions: `/kill`, `/check`, `/steal`
- Day and voting system
- Win detection

## Setup

1. Create a Telegram bot with @BotFather and get the token.
2. Install Python 3.10+.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Set your bot token.

Linux/Termux:
```bash
export BOT_TOKEN="YOUR_BOT_TOKEN"
python bot.py
```

Windows PowerShell:
```powershell
$env:BOT_TOKEN="YOUR_BOT_TOKEN"
python bot.py
```

## Group play

1. Add the bot to your group.
2. Make it admin if you want admin commands to work reliably.
3. In the group:
   - `/game`
   - everyone: `/join`
   - admin: `/startgame`
4. Players should open the bot in private and press `/start` once so role DMs can be delivered.
5. During night, use private commands:
   - Killer: `/kill USER_ID`
   - Police: `/check USER_ID`
   - Thief: `/steal USER_ID`
6. Admin: `/day`
7. Day players vote with `/vote USER_ID`
8. Admin: `/endvote`
9. Repeat until a team wins.

## Important
This is a simple starter version. The Thief currently learns the target's role rather than swapping roles.
