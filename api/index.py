import os
import logging
import asyncio
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient, ReturnDocument
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

# Channels List (-100... ID format)
CHANNELS = {
    "-1004469752383": "1",
    "-1004446913778": "2",
    "-1004426647894": "3"
}

LINKHUB_URL = "https://link-hub.net/9492120/ZKeea2Ckcp73"
LINKHUB_PARAM = "verifyget30ywhahB"

# --- SYNCHRONOUS DATABASE CONNECTION ---
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["telegram_bot_dbviral"]
users_col = db["usersviral"]
settings_col = db["settings"]

# Telegram Application Setup
telegram_app = Application.builder().token(BOT_TOKEN).build()

# Helper: Get/Initialize User Data
def get_user_data(user_id: int):
    today_str = datetime.now().strftime("%Y-%m-%d")
    user = users_col.find_one({"user_id": user_id})
    
    if not user:
        user = {
            "user_id": user_id,
            "last_active_date": today_str,
            "credits": 20,
            "phase": "FREE_20",
            "current_channel": None,
            "offsets": {},
            "last_msg_id": None
        }
        users_col.insert_one(user)
    elif user.get("last_active_date") != today_str:
        user["last_active_date"] = today_str
        user["credits"] = 20
        user["phase"] = "FREE_20"
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"last_active_date": today_str, "credits": 20, "phase": "FREE_20"}}
        )
    return user

# Helper: Get Config Settings
def get_settings():
    settings = settings_col.find_one({"type": "verification_config"})
    if not settings:
        settings = {
            "type": "verification_config",
            "vplink_url": "https://vplink.in/M44",
            "vplink_param": "verifyoeiueuebsna097ajn"
        }
        settings_col.insert_one(settings)
    return settings

# --- HANDLERS ---

async def start(update: Update, context):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    
    args = context.args
    if args:
        start_param = args[0]
        settings = get_settings()
        
        if start_param == settings.get("vplink_param"):
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"credits": 30, "phase": "VERIFIED_30"}}
            )
            await update.message.reply_text("✅ **VPLink Verification Successful!**\nAapko **30 videos** ka access mil gaya hai.")
            return

        if start_param == LINKHUB_PARAM:
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"credits": 10, "phase": "EXTRA_10"}}
            )
            await update.message.reply_text("✅ **Link-Hub Verification Successful!**\nAapko **10 extra videos** ka access mil gaya hai.")
            return

    keyboard = []
    for channel_id, channel_name in CHANNELS.items():
        keyboard.append([InlineKeyboardButton(channel_name, callback_data=f"select_chan:{channel_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Welcome! Aapke paas abhi **{user['credits']} videos** baki hain.\nKripya channel select karein:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def channel_selected(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    channel_id = query.data.split(":")[1]
    
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"current_channel": channel_id}}
    )
    
    channel_name = CHANNELS.get(channel_id, "Channel")
    menu_keyboard = [[KeyboardButton("▶️ Next Video")]]
    reply_markup = ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)
    
    await query.message.reply_text(
        f"Aapne **{channel_name}** chun liya hai.\nNiche diye gaye **▶️ Next Video** button par click karein.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def handle_next_video(update: Update, context):
    user_id = update.effective_user.id
    
    # 1. Direct Fresh Read from MongoDB
    user = users_col.find_one({"user_id": user_id})
    if not user:
        user = get_user_data(user_id)
    
    if user.get("credits", 0) <= 0:
        settings = get_settings()
        
        if user.get("phase") in ["FREE_20", "NEED_VPLINK"]:
            vplink = settings.get("vplink_url", "https://vplink.in/M44")
            users_col.update_one({"user_id": user_id}, {"$set": {"phase": "NEED_VPLINK"}})
            
            keyboard = [[InlineKeyboardButton("🔗 Verify on VPLink", url=vplink)]]
            await update.message.reply_text(
                "❌ **Aapki 20 Free Videos ki limit khatam ho chuki hai!**\n\nAage 30 videos dekhne ke liye niche diye gaye link se verification poora karein:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

        elif user.get("phase") in ["VERIFIED_30", "NEED_LINKHUB", "EXTRA_10"]:
            users_col.update_one({"user_id": user_id}, {"$set": {"phase": "NEED_LINKHUB"}})
            
            keyboard = [[InlineKeyboardButton("🔗 Verify on Link-Hub", url=LINKHUB_URL)]]
            await update.message.reply_text(
                "❌ **Aapki video limit khatam ho gayi hai!**\n\nAage 10 aur videos unlock karne ke liye verification complete karein:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

    channel_id_str = user.get("current_channel")
    if not channel_id_str:
        await update.message.reply_text("Kripya pehle /start dabakar koi channel select karein.")
        return

    # 2. PURANI VIDEO MESSAGE DELETION (Strictly Video Message ID)
    last_sent_msg_id = user.get("last_msg_id")

    if last_sent_msg_id:
        try:
            msg_id_del = int(last_sent_msg_id)
            await context.bot.delete_message(chat_id=user_id, message_id=msg_id_del)
            logging.info(f"Successfully deleted video message {msg_id_del} for user {user_id}")
        except Exception as e:
            logging.warning(f"Could not delete video message {last_sent_msg_id}: {e}")

    # 3. NEXT VIDEO SEND & DB WRITE
    channel_id = int(channel_id_str)
    offsets = user.get("offsets", {})
    current_offset = offsets.get(channel_id_str, 1)

    video_sent = False
    max_search = current_offset + 50

    while current_offset <= max_search:
        try:
            # Video message sent by bot
            sent_msg = await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=channel_id,
                message_id=current_offset
            )
            
            new_credits = user.get("credits", 20) - 1
            offsets[channel_id_str] = current_offset + 1
            
            # Real Sent Video Message ID
            sent_video_msg_id = int(sent_msg.message_id)

            # Save strictly the SENT VIDEO MESSAGE ID in Mongo DB
            users_col.find_one_and_update(
                {"user_id": user_id},
                {
                    "$set": {
                        "last_msg_id": sent_video_msg_id,
                        "credits": new_credits,
                        "offsets": offsets
                    }
                },
                return_document=ReturnDocument.AFTER
            )

            logging.info(f"Saved video message_id {sent_video_msg_id} to DB")
            video_sent = True
            break
        except Exception:
            current_offset += 1

    if not video_sent:
        offsets[channel_id_str] = current_offset
        users_col.update_one({"user_id": user_id}, {"$set": {"offsets": offsets}})
        await update.message.reply_text("Is channel me filhal aur koi naya video nahi mila.")

async def set_today_link(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /todaylink https://vplink.in/M44")
        return
    
    url = context.args[0]
    settings_col.update_one(
        {"type": "verification_config"},
        {"$set": {"vplink_url": url}},
        upsert=True
    )
    await update.message.reply_text(f"✅ VPLink update ho gaya: {url}")

async def set_today_check(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /todaycheck https://t.me/bot?start=verifyoeiueuebsna097ajn")
        return
    
    full_url = context.args[0]
    param = full_url.split("start=")[-1] if "start=" in full_url else full_url
    
    settings_col.update_one(
        {"type": "verification_config"},
        {"$set": {"vplink_param": param}},
        upsert=True
    )
    await update.message.reply_text(f"✅ VPLink Check Param update ho gaya: `{param}`", parse_mode="Markdown")

# Handlers Setup
def setup_handlers():
    if not telegram_app.handlers:
        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CommandHandler("todaylink", set_today_link))
        telegram_app.add_handler(CommandHandler("todaycheck", set_today_check))
        telegram_app.add_handler(CallbackQueryHandler(channel_selected, pattern="^select_chan:"))
        telegram_app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^▶️ Next Video$"), handle_next_video))

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
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            update = Update.de_json(update_data, telegram_app.bot)

            async def process():
                if not telegram_app._initialized:
                    await telegram_app.initialize()
                await telegram_app.process_update(update)

            loop.run_until_complete(process())
            loop.close()
            return "OK", 200
        except Exception as e:
            logging.error(f"Error processing webhook update: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    return "Method Not Allowed", 405
