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

LINKHUB_URL = "https://link-hub.net/9492120/ZKeea2Ckcp73"
LINKHUB_PARAM = "verifyget30ywhahB"

# --- MONGO CONNECTION ---
mongo_client = MongoClient(
    MONGO_URI,
    maxPoolSize=10,
    connectTimeoutMS=5000,
    serverSelectionTimeoutMS=5000
)
db = mongo_client["telegram_bot_dbviral"]
users_col = db["usersviral"]
settings_col = db["settings"]
sources_col = db["sources"]  # Dynamic Channels & Topics collection

# Telegram Application Setup
telegram_app = Application.builder().token(BOT_TOKEN).build()

# Helper: Get/Initialize User Data with Daily Reset (7 FREE CREDITS)
def get_user_data(user_id: int):
    today_str = datetime.now().strftime("%Y-%m-%d")
    user = users_col.find_one({"user_id": user_id})
    
    if not user:
        user = {
            "user_id": user_id,
            "last_active_date": today_str,
            "credits": 7,
            "phase": "FREE_20",
            "current_source": None,
            "offsets": {},
            "sent_msg_ids": []
        }
        users_col.insert_one(user)
    elif user.get("last_active_date") != today_str:
        user["last_active_date"] = today_str
        user["credits"] = 7
        user["phase"] = "FREE_20"
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "last_active_date": today_str, 
                "credits": 7, 
                "phase": "FREE_20"
            }}
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

    # Fetch dynamic categories/topics/channels from Mongo
    sources = list(sources_col.find({}))
    
    if not sources:
        await update.message.reply_text("Abhi tak koi Category add nahi ki gayi hai. Admin se sampark karein.")
        return

    keyboard = []
    for src in sources:
        key = f"{src['type']}:{src['chat_id']}"
        if src['type'] == 'topic':
            key += f":{src['topic_id']}"
            
        display_name = f"📁 {src['name']}" if src['type'] == 'topic' else f"📢 {src['name']}"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"sel_src:{key}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Welcome! Aapke paas abhi **{user['credits']} videos** baki hain.\nKripya category select karein:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def source_selected(update: Update, context):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    src_key = query.data.replace("sel_src:", "")
    
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"current_source": src_key}}
    )
    
    parts = src_key.split(":")
    chat_id = parts[1]
    
    if parts[0] == "channel":
        src_doc = sources_col.find_one({"type": "channel", "chat_id": chat_id})
    else:
        src_doc = sources_col.find_one({"type": "topic", "chat_id": chat_id, "topic_id": int(parts[2])})

    src_name = src_doc["name"] if src_doc else "Selected Category"
    
    menu_keyboard = [[KeyboardButton("▶ Next Video")]]
    reply_markup = ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)
    
    await query.message.reply_text(
        f"Aapne **{src_name}** chun liya hai.\nNiche diye gaye **▶ Next Video** button par click karein.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def handle_next_video(update: Update, context):
    user_id = update.effective_user.id
    user = get_user_data(user_id)

    # 1. CHECK LIMITS
    if user.get("credits", 0) <= 0:
        settings = get_settings()
        current_phase = user.get("phase", "FREE_20")
        
        if current_phase in ["FREE_20", "NEED_VPLINK"]:
            vplink = settings.get("vplink_url", "https://vplink.in/M44")
            users_col.update_one({"user_id": user_id}, {"$set": {"phase": "NEED_VPLINK"}})
            
            keyboard = [[InlineKeyboardButton("🔗 Verify on VPLink", url=vplink)]]
            await update.message.reply_text(
                "❌ **Aapki 7 Free Videos ki limit khatam ho chuki hai!**\n\nAage 30 videos dekhne ke liye niche diye gaye VPLink se verification poora karein:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

        elif current_phase in ["VERIFIED_30", "NEED_LINKHUB"]:
            users_col.update_one({"user_id": user_id}, {"$set": {"phase": "NEED_LINKHUB"}})
            
            keyboard = [[InlineKeyboardButton("🔗 Verify on Link-Hub", url=LINKHUB_URL)]]
            await update.message.reply_text(
                "❌ **Aapki 30 Videos ki limit khatam ho gayi hai!**\n\nAage 10 extra videos unlock karne ke liye Link-Hub verification complete karein:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

        elif current_phase in ["EXTRA_10"]:
            keyboard = [[InlineKeyboardButton("🔗 Verify on Link-Hub", url=LINKHUB_URL)]]
            await update.message.reply_text(
                "❌ **Aapki 10 Extra Videos ki limit khatam ho gayi hai!**\n\n10 aur videos unlock karne ke liye dobara Link-Hub verify karein:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

    source_key = user.get("current_source")
    if not source_key:
        await update.message.reply_text("Kripya pehle /start dabakar koi category select karein.")
        return

    # 2. DELETE PREVIOUS MESSAGES
    old_ids = list(set(user.get("sent_msg_ids", [])))
    if user.get("last_sent_video_id") and user.get("last_sent_video_id") not in old_ids:
        old_ids.append(user.get("last_sent_video_id"))
    if user.get("last_msg_id") and user.get("last_msg_id") not in old_ids:
        old_ids.append(user.get("last_msg_id"))

    for msg_id in old_ids:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=int(msg_id))
            logging.info(f"Successfully deleted message ID: {msg_id}")
        except Exception as e:
            logging.warning(f"Could not delete message ID {msg_id}: {e}")

    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {"sent_msg_ids": []},
            "$unset": {"last_sent_video_id": "", "last_msg_id": ""}
        }
    )

    # 3. SEND NEW VIDEO WITH OFFSET
    parts = source_key.split(":")
    chat_id_str = parts[1]
    chat_id = int(chat_id_str)
    
    if parts[0] == "channel":
        default_start = 1
    else:
        topic_doc = sources_col.find_one({"type": "topic", "chat_id": chat_id_str, "topic_id": int(parts[2])})
        default_start = topic_doc.get("start_msg_id", 1) if topic_doc else 1

    offsets = user.get("offsets", {})
    current_offset = offsets.get(source_key, default_start)

    video_sent = False
    max_search = current_offset + 200

    while current_offset <= max_search:
        try:
            sent_msg = await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=chat_id,
                message_id=current_offset,
                protect_content=True
            )
            
            new_credits = user.get("credits", 7) - 1
            offsets[source_key] = current_offset + 1
            sent_video_msg_id = int(sent_msg.message_id)

            users_col.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "sent_msg_ids": [sent_video_msg_id],
                        "last_sent_video_id": sent_video_msg_id,
                        "credits": new_credits,
                        "offsets": offsets
                    }
                }
            )

            logging.info(f"Sent and recorded video ID: {sent_video_msg_id}")
            video_sent = True
            break
        except Exception as e:
            logging.warning(f"Failed copying offset {current_offset}: {e}")
            current_offset += 1

    if not video_sent:
        offsets[source_key] = default_start
        users_col.update_one({"user_id": user_id}, {"$set": {"offsets": offsets}})
        
        await update.message.reply_text(
            "🔄 **Is category ke saare videos khatam ho gaye hain!**\n\nDobara dekhte rehne ke liye phir se **▶ Next Video** par click karein (videos shuru se repeat honge)."
        )

# --- BULK CHANNEL / TOPIC AUTO-ADD HANDLER ---

async def handle_direct_add(update: Update, context):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return

    text = update.message.text.strip()

    # 1. JSON Dictionary Format (Multiple Channels)
    # Example:
    # {
    #   "-1004469752383": "1",
    #   "-1004446913778": "teeny"
    # }
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            added_count = 0
            for chat_id, name in data.items():
                chat_id_str = str(chat_id).strip()
                name_str = str(name).strip()

                sources_col.update_one(
                    {"type": "channel", "chat_id": chat_id_str},
                    {"$set": {"type": "channel", "chat_id": chat_id_str, "name": name_str}},
                    upsert=True
                )
                added_count += 1

            await update.message.reply_text(
                f"✅ **{added_count} Channels successfully added/updated!**",
                parse_mode="Markdown"
            )
            return
    except json.JSONDecodeError:
        pass  # Not JSON, move to Topic regex check

    # 2. Topic Link Format
    # Example: https://t.me/c/4412223111/9/10 Category Name
    pattern = r"https://t\.me/c/(\d+)/(\d+)/(\d+)\s+(.+)"
    match = re.match(pattern, text)

    if match:
        raw_group_id = match.group(1)
        topic_id = int(match.group(2))
        start_msg_id = int(match.group(3))
        category_name = match.group(4).strip()

        group_id = f"-100{raw_group_id}"

        sources_col.update_one(
            {"type": "topic", "chat_id": group_id, "topic_id": topic_id},
            {"$set": {
                "type": "topic", 
                "chat_id": group_id, 
                "topic_id": topic_id, 
                "start_msg_id": start_msg_id, 
                "name": category_name
            }},
            upsert=True
        )

        await update.message.reply_text(
            f"✅ **Topic/Category Successfully Added!**\n\n"
            f"📌 **Name:** {category_name}\n"
            f"🆔 **Group ID:** `{group_id}`\n"
            f"🧵 **Topic ID:** `{topic_id}`\n"
            f"🎬 **Start Video ID:** `{start_msg_id}`",
            parse_mode="Markdown"
        )

async def list_sources(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    
    sources = list(sources_col.find({}))
    if not sources:
        await update.message.reply_text("Koi bhi Category added nahi hai.")
        return

    text = "📋 **Added Channels & Topics:**\n\n"
    for s in sources:
        if s["type"] == "channel":
            text += f"📢 **Channel:** {s['name']}\n`ID: {s['chat_id']}`\n\n"
        else:
            text += f"📁 **Topic:** {s['name']}\n`Group ID: {s['chat_id']}` | `Topic ID: {s['topic_id']}` | `Start ID: {s.get('start_msg_id', 1)}`\n\n"

    await update.message.reply_text(text, parse_mode="Markdown")

async def del_source(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: `/delsource <chat_id>`", parse_mode="Markdown")
        return

    chat_id = context.args[0]
    res = sources_col.delete_many({"chat_id": chat_id})
    await update.message.reply_text(f"🗑 {res.deleted_count} source(s) deleted for Chat ID: `{chat_id}`", parse_mode="Markdown")

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
        telegram_app.add_handler(CommandHandler("listall", list_sources))
        telegram_app.add_handler(CommandHandler("delsource", del_source))
        telegram_app.add_handler(CommandHandler("todaylink", set_today_link))
        telegram_app.add_handler(CommandHandler("todaycheck", set_today_check))
        telegram_app.add_handler(CallbackQueryHandler(source_selected, pattern="^sel_src:"))
        telegram_app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r".*Next Video.*"), handle_next_video))
        
        # Combined Bulk Channel JSON & Direct Topic Link Auto-Detection
        telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_add))

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
                async with telegram_app:
                    await telegram_app.start()
                    update = Update.de_json(update_data, telegram_app.bot)
                    await telegram_app.process_update(update)
                    await telegram_app.stop()

            asyncio.run(process_update_async())
            return "OK", 200
        except Exception as e:
            logging.error(f"Error processing webhook update: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500

    return "Method Not Allowed", 405
