import os
import re
import json
import logging
import asyncio
import base64
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
tokens_col = db["tokans"]       # Token verification collection
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

# --- 🔐 STRICT DECODER FUNCTION (New Encrypted Format Only) ---
def decode_payload(encoded_str):
    try:
        if not encoded_str:
            return None
        
        # Agar purana format hai (jaise sirf numbers aur underscores: 811_815_1_2), toh ise strictly reject kar do
        if all(c.isdigit() or c == '_' for c in encoded_str):
            return None

        # New format decoding: parts are separated by '_'
        parts = encoded_str.split('_')
        decoded_parts = []
        
        for part in parts:
            sub_chunks = part.split()
            char_str = ""
            for chunk in sub_chunks:
                # Base64 decode each chunk back to binary string
                b64_decoded = base64.b64decode(chunk + "==").decode('utf-8')
                # Binary to character conversion
                decimal_val = int(b64_decoded, 2)
                char_str += chr(decimal_val)
            decoded_parts.append(char_str)
            
        return "_".join(decoded_parts)
    except Exception as e:
        print(f"⚠️ Decoding Error: {e}")
        return None

# --- HANDLERS ---

async def start(update: Update, context):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    
    args = context.args
    if args:
        start_param = args[0]
        
        # Check token verification in MongoDB collection `tokans`
        token_doc = tokens_col.find_one({"tokan": start_param})
        if token_doc:
            if token_doc.get("status") == "unused":
                # Mark token as used
                tokens_col.update_one({"tokan": start_param}, {"$set": {"status": "used"}})
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

        # 🔓 Decode the new payload format
        decoded_arg = decode_payload(start_param)
        
        # Agar purana format diya gaya hoga toh decoded_arg `None` return karega
        if not decoded_arg:
            await update.message.reply_text("❌ **Invalid Link!**\n\nYeh link invalid ya purana format ka hai. Kripya naya valid link use karein.")
            return

        # Check if decoded format matches video range format: e.g., 757_758_1_2
        match = re.match(r"^(\d+)_(\d+)", decoded_arg)
        if match:
            start_id = int(match.group(1))
            end_id = int(match.group(2))
            
            target_chat_id = "-1003557690577"
            
            users_col.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "current_chat_id": target_chat_id,
                        "current_start_id": start_id,
                        "current_end_id": end_id,
                        "current_video_offset": start_id,
                        "is_verified": True 
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
        sent_msg = await context.bot.copy_message(
            chat_id=user_id,
            from_chat_id=int(source_chat_id),
            message_id=current_offset,
            protect_content=True
        )
        
        users_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "current_video_offset": current_offset + 1,
                    "is_verified": False  
                }
            }
        )
    except Exception as e:
        logging.error(f"Error copying video message: {e}")
        users_col.update_one({"user_id": user_id}, {"$set": {"current_video_offset": current_offset + 1}})
        await update.message.reply_text("⚠️ Yeh video nahi mili, agli try kar rahe hain... Phir se **▶ Next Video** dabayein.")

# --- ADMIN / SETUP HANDLERS ---

async def handle_admin_setup(update: Update, context):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    text = update.message.text.strip()
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
    return "Bot status: Running successfully on Vercel with Encrypted Payload Checking!", 200

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
