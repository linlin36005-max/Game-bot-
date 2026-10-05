import os, sqlite3, asyncio
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

TZ = ZoneInfo(os.getenv('BOT_TIMEZONE', 'Asia/Yangon'))
DB = os.getenv('DB_PATH', 'game.db')
TOKEN = os.getenv('BOT_TOKEN', '')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))
START_COINS = int(os.getenv('START_COINS', '1000'))
DAILY_REWARD = int(os.getenv('DAILY_REWARD', '100'))


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db(); cur = con.cursor()
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, coins INTEGER NOT NULL DEFAULT 1000,
      wins INTEGER NOT NULL DEFAULT 0, plays INTEGER NOT NULL DEFAULT 0,
      streak INTEGER NOT NULL DEFAULT 0, last_daily TEXT
    );
    CREATE TABLE IF NOT EXISTS rounds(
      id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT UNIQUE NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS results(
      id INTEGER PRIMARY KEY AUTOINCREMENT, round_time TEXT NOT NULL, game_date TEXT NOT NULL,
      result TEXT NOT NULL, created_at TEXT NOT NULL,
      UNIQUE(round_time, game_date)
    );
    CREATE TABLE IF NOT EXISTS plays(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, game TEXT NOT NULL,
      choice TEXT NOT NULL, points INTEGER NOT NULL, round_time TEXT NOT NULL, game_date TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'PENDING'
    );
    ''')
    # Default rounds use a 12-hour clock for users (12:00 PM and 1:00 PM).
    cur.execute("INSERT OR IGNORE INTO rounds(time) VALUES ('12:00')")
    cur.execute("INSERT OR IGNORE INTO rounds(time) VALUES ('13:00')")
    con.commit(); con.close()


def ensure_user(u):
    con=db(); cur=con.cursor()
    cur.execute('SELECT id FROM users WHERE id=?',(u.id,))
    if not cur.fetchone():
        cur.execute('INSERT INTO users(id,username,first_name,coins) VALUES(?,?,?,?)',(u.id,u.username,u.first_name or '',START_COINS))
    else:
        cur.execute('UPDATE users SET username=?,first_name=? WHERE id=?',(u.username,u.first_name or '',u.id))
    con.commit(); con.close()


def rank(coins):
    ranks=[(50000,'👑 Master'),(20000,'💎 Diamond'),(5000,'🥇 Gold'),(1000,'🥈 Silver'),(0,'🥉 Bronze')]
    return next(name for n,name in ranks if coins>=n)


def display_time(t):
    # Convert internal 24-hour time to easy 12-hour display.
    h, m = map(int, t.split(':'))
    suffix = 'AM' if h < 12 else 'PM'
    hh = h % 12 or 12
    return f'{hh}:{m:02d} {suffix}'

def normalize_round(value):
    # Accept 12-hour clock input only: 1 PM, 6 PM, 12 AM, 6:30 PM, etc.
    v=value.strip().lower().replace('.', '')
    if ' ' in v:
        parts=v.split()
        if len(parts)==2: v=parts[0]+parts[1]
    for suffix in ('am','pm'):
        if v.endswith(suffix):
            raw=v[:-2]
            try:
                if ':' in raw:
                    h,m=raw.split(':',1)
                else:
                    h,m=raw,'00'
                h=int(h); m=int(m)
                if not (1 <= h <= 12 and 0 <= m <= 59): return None
                if suffix=='am': h24=0 if h==12 else h
                else: h24=12 if h==12 else h+12
                return f'{h24:02d}:{m:02d}'
            except ValueError: return None
    return None


def menu():
    return InlineKeyboardMarkup([
      [InlineKeyboardButton('🎮 Play',callback_data='play'), InlineKeyboardButton('👤 Profile',callback_data='profile')],
      [InlineKeyboardButton('🎁 Daily Reward',callback_data='daily'), InlineKeyboardButton('🏆 Leaderboard',callback_data='leader')],
      [InlineKeyboardButton('⏰ Rounds',callback_data='rounds'), InlineKeyboardButton('📜 History',callback_data='history')],
    ])

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    await update.message.reply_text('🎮 Welcome to Virtual 2D/3D Game!\n\n🪙 Coins are virtual and have no cash value.', reply_markup=menu())

async def profile(update, context):
    u=update.effective_user; ensure_user(u)
    con=db(); r=con.execute('SELECT * FROM users WHERE id=?',(u.id,)).fetchone(); con.close()
    txt=(f'👤 <b>{r["first_name"] or r["username"] or "Player"}</b>\n\n'
         f'🪙 Coins: <b>{r["coins"]:,}</b>\n🏅 Rank: {rank(r["coins"])}\n'
         f'🎯 Plays: {r["plays"]}\n🏆 Wins: {r["wins"]}\n🔥 Streak: {r["streak"]}')
    return txt

async def daily(update, context):
    u=update.effective_user; ensure_user(u); today=date.today().isoformat()
    con=db(); r=con.execute('SELECT * FROM users WHERE id=?',(u.id,)).fetchone()
    if r['last_daily']==today:
        con.close(); return '🎁 Daily Reward already claimed today.'
    streak=r['streak']+1 if r['last_daily']==(date.today()-timedelta(days=1)).isoformat() else 1
    bonus=DAILY_REWARD + min(streak-1,7)*25
    con.execute('UPDATE users SET coins=coins+?,streak=?,last_daily=? WHERE id=?',(bonus,streak,today,u.id)); con.commit(); con.close()
    return f'🎁 Daily Reward claimed!\n🪙 +{bonus:,} coins\n🔥 Streak: {streak}'

async def rounds_text():
    con=db(); rows=con.execute('SELECT time FROM rounds WHERE enabled=1 ORDER BY time').fetchall(); con.close()
    if not rows: return '⏰ No rounds configured yet.'
    today=date.today().isoformat(); con=db(); res=con.execute('SELECT round_time,result FROM results WHERE game_date=?',(today,)).fetchall(); con.close()
    done={r['round_time']:r['result'] for r in res}
    return '⏰ <b>Today Rounds</b>\n\n'+'\n'.join(f'• {display_time(r["time"])} — {"✅ "+done[r["time"]] if r["time"] in done else "⏳ Open"}' for r in rows)

async def leaderboard():
    con=db(); rows=con.execute('SELECT first_name,username,coins FROM users ORDER BY coins DESC LIMIT 10').fetchall(); con.close()
    if not rows:return '🏆 Leaderboard is empty.'
    return '🏆 <b>Leaderboard</b>\n\n'+'\n'.join(f'{i}. {r["first_name"] or r["username"] or "Player"} — 🪙 {r["coins"]:,} — {rank(r["coins"])}' for i,r in enumerate(rows,1))

async def history(update, context):
    u=update.effective_user; ensure_user(u); con=db(); rows=con.execute('SELECT game,choice,points,round_time,status,game_date FROM plays WHERE user_id=? ORDER BY id DESC LIMIT 10',(u.id,)).fetchall(); con.close()
    if not rows:return '📜 No play history yet.'
    return '📜 <b>Your History</b>\n\n'+'\n'.join(f'{r["game"]} | {r["choice"]} | {r["points"]} pts | {r["round_time"]} | {r["status"]}' for r in rows)

async def button(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); u=q.from_user; ensure_user(u)
    if q.data=='profile': txt=await profile(update,context)
    elif q.data=='daily': txt=await daily(update,context)
    elif q.data=='leader': txt=await leaderboard()
    elif q.data=='rounds': txt=await rounds_text()
    elif q.data=='history': txt=await history(update,context)
    elif q.data=='play': txt=('🎮 <b>Virtual Game</b>\n\nUse /play2d <choice> <points> or /play3d <choice> <points>\nExample: /play2d 57 100\n\n⚠️ Virtual points only; no cash value.')
    else: txt='Use /start'
    await q.message.reply_text(txt,parse_mode='HTML',reply_markup=menu())


def is_owner(u): return OWNER_ID and u.id==OWNER_ID

async def play(update, context, game):
    u=update.effective_user; ensure_user(u)
    if len(context.args)!=2: await update.message.reply_text(f'Usage: /{game.lower()} <choice> <points>'); return
    choice=context.args[0].strip();
    try: pts=int(context.args[1])
    except: await update.message.reply_text('Points must be a number.'); return
    if pts<=0 or pts>100000: await update.message.reply_text('Points must be between 1 and 100,000.'); return
    con=db(); r=con.execute('SELECT coins FROM users WHERE id=?',(u.id,)).fetchone()
    if r['coins']<pts: con.close(); await update.message.reply_text('🪙 Not enough coins.'); return
    now=datetime.now(TZ); current=now.strftime('%H:%M')
    row=con.execute('SELECT time FROM rounds WHERE enabled=1 AND time>=? ORDER BY time LIMIT 1',(current,)).fetchone()
    if not row: row=con.execute('SELECT time FROM rounds WHERE enabled=1 ORDER BY time LIMIT 1').fetchone()
    if not row: con.close(); await update.message.reply_text('⏰ No game round configured.'); return
    rt=row['time']; gd=now.date().isoformat()
    con.execute('UPDATE users SET coins=coins-?,plays=plays+1 WHERE id=?',(pts,u.id))
    con.execute('INSERT INTO plays(user_id,game,choice,points,round_time,game_date) VALUES(?,?,?,?,?,?)',(u.id,game,choice,pts,rt,gd))
    con.commit(); con.close(); await update.message.reply_text(f'✅ {game} entry recorded!\n🎯 Choice: {choice}\n🪙 Points: {pts:,}\n⏰ Round: {rt}')

async def play2d(update,context): await play(update,context,'2D')
async def play3d(update,context): await play(update,context,'3D')

async def admin(update, context):
    if not is_owner(update.effective_user): return
    await update.message.reply_text(
        '👑 <b>Owner Commands</b>\n\n'
        '/result 6 PM VALUE — 6:00 PM result\n'
        '/addtime 8 PM — Add a round time\n'
        '/removetime 8 PM — Remove a round time\n'
        '/give USER_ID POINTS — Give virtual coins\n'
        '/announce TEXT — Announcement\n'
        '/admin — Show this list', parse_mode='HTML')

async def addtime(update,context):
    if not is_owner(update.effective_user): return
    if len(context.args)!=2:
        await update.message.reply_text('Usage: /addtime 6 PM')
        return
    rt=normalize_round(' '.join(context.args))
    if not rt:
        await update.message.reply_text('❌ Use 1–12 with AM/PM. Example: /addtime 6 PM')
        return
    con=db(); con.execute('INSERT OR IGNORE INTO rounds(time) VALUES(?)',(rt,)); con.commit(); con.close()
    await update.message.reply_text(f'✅ Round added: {display_time(rt)}')

async def removetime(update,context):
    if not is_owner(update.effective_user): return
    if len(context.args)!=2:
        await update.message.reply_text('Usage: /removetime 6 PM')
        return
    rt=normalize_round(' '.join(context.args))
    if not rt:
        await update.message.reply_text('❌ Use 1–12 with AM/PM. Example: /removetime 6 PM')
        return
    con=db(); con.execute('DELETE FROM rounds WHERE time=?',(rt,)); con.commit(); con.close()
    await update.message.reply_text(f'✅ Round removed: {display_time(rt)}')

async def result(update,context):
    if not is_owner(update.effective_user): return
    if len(context.args)!=3:
        await update.message.reply_text('Usage: /result 6 PM VALUE')
        return
    rt=normalize_round(' '.join(context.args[:-1]))
    if not rt:
        await update.message.reply_text('❌ Use a 12-hour time. Example: /result 6 PM 57')
        return
    val=context.args[1]
    now=datetime.now(TZ); gd=now.date().isoformat()
    con=db(); con.execute('INSERT OR REPLACE INTO results(round_time,game_date,result,created_at) VALUES(?,?,?,?)',(rt,gd,val,datetime.now(TZ).isoformat()))
    con.commit(); con.close(); await update.message.reply_text(f'✅ Result saved: {display_time(rt)} → {val}')

async def give(update,context):
    if not is_owner(update.effective_user): return
    if len(context.args)!=2:return
    try: uid=int(context.args[0]); pts=int(context.args[1])
    except:return
    con=db(); con.execute('UPDATE users SET coins=coins+? WHERE id=?',(pts,uid)); con.commit(); con.close(); await update.message.reply_text('✅ Coins updated.')

async def announce(update,context):
    if not is_owner(update.effective_user): return
    text=' '.join(context.args)
    if not text:return
    await update.message.reply_text('📢 '+text)

async def main():
    if not TOKEN: raise RuntimeError('BOT_TOKEN is missing in .env')
    init_db()
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler('start',start)); app.add_handler(CommandHandler('play2d',play2d)); app.add_handler(CommandHandler('play3d',play3d))
    app.add_handler(CommandHandler('profile',lambda u,c: u.message.reply_text('Loading...',reply_markup=menu())))
    app.add_handler(CommandHandler('daily',lambda u,c: daily(u,c)))
    app.add_handler(CommandHandler('leaderboard',lambda u,c: leaderboard()))
    app.add_handler(CommandHandler('rounds',lambda u,c: rounds_text()))
    app.add_handler(CommandHandler('history',lambda u,c: history(u,c)))
    app.add_handler(CommandHandler('admin',admin)); app.add_handler(CommandHandler('addtime',addtime)); app.add_handler(CommandHandler('removetime',removetime)); app.add_handler(CommandHandler('result',result)); app.add_handler(CommandHandler('give',give)); app.add_handler(CommandHandler('announce',announce))
    app.add_handler(CallbackQueryHandler(button))
    await app.initialize(); await app.start(); await app.updater.start_polling();
    await asyncio.Event().wait()

if __name__=='__main__': asyncio.run(main())
