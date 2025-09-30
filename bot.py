import os
import logging
import sqlite3
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Environment variables থেকে টোকেন ও আইডি নিন
BOT_TOKEN = os.environ['BOT_TOKEN']
ADMIN_ID = int(os.environ['ADMIN_ID'])

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

print("🚀 SID Bot Starting on Render...")

class SIDBot:
    def __init__(self):
        self.db = sqlite3.connect('/tmp/sid_bot.db', check_same_thread=False)
        self.init_db()
    
    def init_db(self):
        cursor = self.db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sid_text TEXT NOT NULL,
                price REAL NOT NULL,
                status TEXT DEFAULT 'available',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0.0,
                total_sids INTEGER DEFAULT 0,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deposit_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                method TEXT,
                transaction_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.db.commit()
        print("✅ Database tables created successfully!")
    
    def add_sid_to_stock(self, sid_text, price=10.0):
        cursor = self.db.cursor()
        cursor.execute("INSERT INTO stock (sid_text, price) VALUES (?, ?)", (sid_text, price))
        self.db.commit()
        return cursor.lastrowid
    
    def get_available_sids_count(self):
        cursor = self.db.cursor()
        cursor.execute("SELECT COUNT(*) FROM stock WHERE status='available'")
        return cursor.fetchone()[0]
    
    def get_user_balance(self, user_id):
        cursor = self.db.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
        else:
            cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 0.0))
            self.db.commit()
            return 0.0
    
    def create_deposit_request(self, user_id, amount, method, transaction_id):
        cursor = self.db.cursor()
        cursor.execute("INSERT INTO deposit_requests (user_id, amount, method, transaction_id) VALUES (?, ?, ?, ?)", 
                      (user_id, amount, method, transaction_id))
        self.db.commit()
        return cursor.lastrowid
    
    def get_pending_deposits(self):
        cursor = self.db.cursor()
        cursor.execute("SELECT * FROM deposit_requests WHERE status='pending' ORDER BY created_at DESC")
        return cursor.fetchall()
    
    def approve_deposit(self, deposit_id):
        cursor = self.db.cursor()
        cursor.execute("SELECT * FROM deposit_requests WHERE id=?", (deposit_id,))
        deposit = cursor.fetchone()
        if deposit:
            user_id, amount = deposit[1], deposit[2]
            current_balance = self.get_user_balance(user_id)
            new_balance = current_balance + amount
            cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
            cursor.execute("UPDATE deposit_requests SET status='approved' WHERE id=?", (deposit_id,))
            self.db.commit()
            return True, new_balance
        return False, 0
    
    def sell_sid_to_user(self, user_id):
        cursor = self.db.cursor()
        cursor.execute("SELECT * FROM stock WHERE status='available' LIMIT 1")
        sid = cursor.fetchone()
        if sid:
            sid_id, sid_text, price = sid[0], sid[1], sid[2]
            user_balance = self.get_user_balance(user_id)
            if user_balance >= price:
                cursor.execute("UPDATE stock SET status='sold' WHERE id=?", (sid_id,))
                new_balance = user_balance - price
                cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))
                cursor.execute("UPDATE users SET total_sids = total_sids + 1 WHERE user_id=?", (user_id,))
                self.db.commit()
                return True, sid_text, new_balance
            else:
                return False, "Insufficient balance", user_balance
        else:
            return False, "No SIDs available", 0

bot_manager = SIDBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        keyboard = [["💰 Balance", "📦 Stock"], ["🛒 Buy SID", "💳 Deposit"], ["👑 Admin Panel", "ℹ️ Help"]]
    else:
        keyboard = [["💰 Balance", "📦 Stock"], ["🛒 Buy SID", "💳 Deposit"], ["📊 Price", "🔄 Replacement"], ["ℹ️ Help"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🤖 Welcome to the SID Bot! 😊\n\nPlease choose an option from the menu below to get started.", reply_markup=reply_markup)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    keyboard = [[InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
                [InlineKeyboardButton("💳 Pending Deposits", callback_data="admin_deposits")],
                [InlineKeyboardButton("➕ Add SIDs", callback_data="admin_add_sids")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👑 Admin Panel\n\nChoose an option:", reply_markup=reply_markup)

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id != ADMIN_ID:
        await query.edit_message_text("❌ Access Denied!")
        return
    data = query.data
    if data == "admin_stats":
        total_sids = bot_manager.get_available_sids_count()
        pending_deposits = len(bot_manager.get_pending_deposits())
        await query.edit_message_text(f"📊 Statistics:\n📦 SIDs: {total_sids}\n💳 Pending: {pending_deposits}")
    elif data == "admin_deposits":
        pending_deposits = bot_manager.get_pending_deposits()
        if not pending_deposits:
            await query.edit_message_text("✅ No pending deposits!")
            return
        text, keyboard = "💳 Pending Deposits:\n\n", []
        for deposit in pending_deposits:
            deposit_id, user_id, amount, method, transaction_id = deposit[0], deposit[1], deposit[2], deposit[3], deposit[4]
            text += f"ID: {deposit_id}\nAmount: {amount} BDT\nMethod: {method}\nTrxID: {transaction_id}\n────\n"
            keyboard.append([InlineKeyboardButton(f"✅ Approve #{deposit_id}", callback_data=f"approve_{deposit_id}")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("approve_"):
        deposit_id = int(data.split("_")[1])
        success, new_balance = bot_manager.approve_deposit(deposit_id)
        await query.edit_message_text(f"✅ Deposit #{deposit_id} approved!" if success else "❌ Failed!")

async def add_sids_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ Access Denied!")
        return
    if not context.args:
        await update.message.reply_text("Usage: /addsids price\nExample: /addsids 10")
        return
    try:
        price = float(context.args[0])
        context.user_data['adding_sids_price'] = price
        context.user_data['adding_sids'] = True
        await update.message.reply_text(f"💰 Price: {price} BDT\nNow send SIDs. Send /done when finished.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def handle_sid_addition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    if context.user_data.get('adding_sids'):
        text = update.message.text
        if text == '/done':
            context.user_data['adding_sids'] = False
            await update.message.reply_text("✅ SID addition completed!")
            return
        sids, added_count = text.split('\n'), 0
        for sid_text in sids:
            if sid_text.strip() and sid_text.strip() != '/done':
                bot_manager.add_sid_to_stock(sid_text.strip(), context.user_data['adding_sids_price'])
                added_count += 1
        await update.message.reply_text(f"✅ {added_count} SIDs added!")

async def deposit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) != 3:
        await update.message.reply_text("Usage: /deposit amount method transaction_id\nExample: /deposit 500 bKash TXN123")
        return
    try:
        amount, method, transaction_id = float(context.args[0]), context.args[1], context.args[2]
        deposit_id = bot_manager.create_deposit_request(user_id, amount, method, transaction_id)
        await update.message.reply_text(f"✅ Deposit submitted!\n💰 Amount: {amount} BDT\n📱 Method: {method}\n🆔 TrxID: {transaction_id}\n📋 ID: {deposit_id}")
    except ValueError:
        await update.message.reply_text("❌ Invalid amount!")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = bot_manager.get_user_balance(user_id)
    await update.message.reply_text(f"💵 Balance: {balance:.2f} BDT")

async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    available_sids = bot_manager.get_available_sids_count()
    await update.message.reply_text(f"📦 Available SIDs: {available_sids}")

async def buy_sid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    success, result, new_balance = bot_manager.sell_sid_to_user(user_id)
    if success:
        await update.message.reply_text(f"✅ Purchased!\n🔑 SID: {result}\n💵 Balance: {new_balance:.2f} BDT")
    else:
        await update.message.reply_text("❌ No SIDs available or insufficient balance!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, user_id = update.message.text, update.effective_user.id
    if context.user_data.get('adding_sids') and user_id == ADMIN_ID:
        await handle_sid_addition(update, context)
        return
    if text == "💰 Balance": await balance(update, context)
    elif text == "📦 Stock": await stock(update, context)
    elif text == "🛒 Buy SID": await buy_sid(update, context)
    elif text == "💳 Deposit": await update.message.reply_text("Use: /deposit amount method transaction_id")
    elif text == "👑 Admin Panel" and user_id == ADMIN_ID: await admin_panel(update, context)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("deposit", deposit_command))
    application.add_handler(CommandHandler("addsids", add_sids_command))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("done", handle_sid_addition))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^approve_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot is running on Render - 24/7 Online!")
    application.run_polling()

if __name__ == "__main__":
    main()
