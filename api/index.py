import os
import re
import json
import logging
import asyncio
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

# Logging Setup
logging.basicConfig(level=logging.INFO)

# Flask Server Initialize
app = Flask(__name__)

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# --- MONGO CONNECTION ---
mongo_client = MongoClient(
    MONGO_URI,
    maxPoolSize=10,
    connectTimeoutMS=5000,
    serverSelectionTimeoutMS=5000
)
db = mongo_client["telegram_bot_dbviral"]
users_col = db["usersviral"]
tokens_col = db["tokens"]       # Token verification collection
sources_col = db["sources"]      # Channel/Videos configuration collection

# Telegram Application Setup
telegram_app = Application.builder().token(BOT_TOKEN).build()

# Helper: Get/Initialize User Data
def get_user_data(user_id: int):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        user = {
            "user_id": user_id,
            "current_chat_id": None,
            "current_start_id": 1,
            "current_end_id": 1,
            "current_video_offset": 1,
            "is_verified": False
        }
        users_col.insert_one(user)
    return user

# --- HANDLERS ---

async def start(update: Update, context):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    
    args = context.args
    if args:
        start_param = args[0]
        
        # Check if param is a token verification (e.g., cXPMkiDCmU)
        # Tokens can be checked in MongoDB collection `tokens` or `tokens_col`
        token_doc = tokens_col.find_one({"token": start_param})
        if token_doc:
            if token_doc.get("status") == "unused":
                # Mark token as used
                tokens_col.update_one({"token": start_param}, {"$set": {"status": "used"}})
                users_col.update_one({"user_id": user_id}, {"$set": {"is_verified": True}})
                
                await update.message.reply_text("✅ **Verification Successful!**\nAapko video ka access mil gaya hai. Niche **▶ Next Video** button par click karein.")
                
                # Show Next Video button
                menu_keyboard = [[KeyboardButton("▶ Next Video")]]
                reply_markup = ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)
                await update.message.reply_text("Ab aap videos dekh sakte hain:", reply_markup=reply_markup)
                return
            else:
                await update.message.reply_text("❌ **Yeh token pehle hi use ho chuka hai!** Kripya naya verification karein.")
                return

        # Check if param is video range format: 757_758_1_2 (or similar from deep link)
        # Format example: start=757_758 (Start ID and End ID from channel)
        match = re.match(r"^(\d+)_(\d+)", start_param)
        if match:
            start_id = int(match.group(1))
            end_id = int(match.group(2))
            
            # Since bot is admin in the channel, we can fetch from the channel chat or store it.
            # Here we assume the deep link comes with chat info or user sets it.
            # Let's save the range for the user.
            users_col.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "current_start_id": start_id,
                        "current_end_id": end_id,
                        "current_video_offset": start_id,
                        "is_verified": True # First time entry via deep link can give direct access or require verification based on flow
                    }
                }
            )
            
            menu_keyboard = [[KeyboardButton("▶ Next Video")]]
            reply_markup = ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"🎉 **Videos Set Successfully!**\nRange: `{start_id}` se `{end_id}` tak.\nNiche diye gaye **▶ Next Video** button par click karein.",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
            return

    # Default Start Message if no args
    menu_keyboard = [[KeyboardButton("▶ Next Video")]]
    reply_markup = ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 **Welcome!**\nKripya apne course link se join karein ya **▶ Next Video** dabayein.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_next_video(update: Update, context):
    user_id = update.effective_user.id
    user = get_user_data(user_id)

    # Check if user is verified for the next video
    if not user.get("is_verified", False):
        website_url = "https://ad3-mu.vercel.cpp/" # or your website link
        keyboard = [[InlineKeyboardButton("🌐 Verify on Website", url="https://ad3-mu.vercel.app/")]]
        await update.message.reply_text(
            "🔒 **Verification Required!**\n\nAgli video dekhne ke liye niche diye gaye link par click karke verify karein aur apna verification code bot ko bhejein:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    current_offset = user.get("current_video_offset", 1)
    end_id = user.get("current_end_id", current_offset + 10)
    source_chat_id = user.get("current_chat_id")

    if not source_chat_id:
        # Fallback to default admin/source channel if stored in sources collection
        src = sources_col.find_one({})
        if src:
            source_chat_id = src.get("chat_id")
        else:
            await update.message.reply_text("❌ Koi source channel set nahi hai. Kripya valid link use karein.")
            return

    if current_offset > end_id:
        await update.message.reply_text("🔄 **Saari videos khatam ho chuki hain!**")
        return

    try:
        # Send video from channel
        sent_msg = await context.bot.copy_message(
            chat_id=user_id,
            from_chat_id=int(source_chat_id),
            message_id=current_offset,
            protect_content=True
        )
        
        # Update offset and reset verification status so next video requires re-verification via website
        users_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "current_video_offset": current_offset + 1,
                    "is_verified": False  # Next video ke liye dubara verification chahiye hoga
                }
            }
        )
    except Exception as e:
        logging.error(f"Error copying video message: {e}")
        # Try next ID if current message doesn't exist
        users_col.update_one({"user_id": user_id}, {"$set": {"current_video_offset": current_offset + 1}})
        await update.message.reply_text("⚠️ Yeh video nahi mili, agli try kar rahe hain... Phir se **▶ Next Video** dabayein.")

# --- ADMIN / SETUP HANDLERS ---

async def handle_admin_setup(update: Update, context):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    text = update.message.text.strip()
    # Format for saving channel chat_id: e.g., "-100xxxxxxxxxx"
    if text.startswith("-100") or text.isdigit():
        sources_col.update_one(
            {"chat_id": text},
            {"$set": {"chat_id": text, "updated_at": datetime.now()}},
            upsert=True
        )
        await update.message.reply_text(f"✅ Channel ID `{text}` successfully saved as source!", parse_mode="Markdown")

# Handlers Setup
def setup_handlers():
    if not telegram_app.handlers:
        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r".*Next Video.*"), handle_next_video))
        telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_setup))

setup_handlers()

# --- VERCEL FLASK WEBHOOK ROUTES ---

@app.route("/", methods=["GET"])
def index():
    return "Bot status: Running successfully on Vercel!", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    if request.method == "POST":
        try:
            update_data = request.get_json(force=True)
            
            async def process_update_async():
                await telegram_app.initialize()
                update = Update.de_json(update_data, telegram_app.bot)
                await telegram_app.process_update(update)
                await telegram_app.shutdown()

            asyncio.run(process_update_async())
            return "OK", 200
        except Exception as e:
            logging.error(f"Error processing webhook update: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    return "Method Not Allowed", 405
