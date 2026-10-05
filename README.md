# Novel Game Bot

Features:
- Virtual Coin/Point system (no cash value)
- 2D / 3D play commands
- Daily Reward + streak bonus
- Rank and leaderboard
- User profile and history
- Custom round times (Myanmar time)
- Owner result management
- SQLite database

## Install

```bash
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `BOT_TOKEN` and `OWNER_ID`, then load the env variables and run:

```bash
python bot.py
```

## Commands

User:
- `/start`
- `/play2d 57 100`
- `/play3d 123 100`
- `/profile`
- `/daily`
- `/leaderboard`
- `/rounds`
- `/history`

Owner:
- `/addtime 18:45`
- `/removetime 18:45`
- `/result 18:45 57`
- `/give USER_ID 500`
- `/announce message`

All points are virtual and are not redeemable for cash.
