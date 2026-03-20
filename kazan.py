import asyncio
import os
import tempfile
import yt_dlp
import json
from telegram import ReplyKeyboardMarkup, Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# ===== CONFIGURATION =====
import os
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [5475530776]
CHANNEL_USERNAME = "YTubeVideoDownloader"
VIDEO_LIMIT = 5
DB_FILE = "user_database.json"
BTC_ADDRESS = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f: return json.load(f)
        except: return {}
    return {}

user_db = load_db()

def save_db():
    with open(DB_FILE, "w") as f: json.dump(user_db, f)

async def is_subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in ADMIN_IDS: return True
    try:
        member = await context.bot.get_chat_member(chat_id=f"@{CHANNEL_USERNAME}", user_id=uid)
        if member.status in ["member", "administrator", "creator"]:
            return True
    except Exception:
        pass

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_USERNAME}")]])
    await update.message.reply_text(
        f"⚠️ **Access Denied!**\n\nYou must join our channel to use this bot.",
        reply_markup=keyboard
    )
    return False

YDL_BASE_ARGS = ['--quiet', '--no-warnings', '--js-runtimes', 'node', '--extractor-args', 'youtube:player_client=android', '--no-check-certificate']

def main_keyboard():
    return ReplyKeyboardMarkup([
        ["🎬 Download Video", "✂️ Clip Video"],
        ["📸 Screenshot", "🖼 Cover"],
        ["💎 Premium", "🔗 Referral"],
        ["ℹ️ Info", "✅ Finish"]
    ], resize_keyboard=True)

def admin_keyboard():
    return ReplyKeyboardMarkup([
        ["👥 Total Users", "🌟 Prem Users"],
        ["➕ Add Premium", "📢 Broadcast"],
        ["🔙 Back to Main Menu"]
    ], resize_keyboard=True)

async def get_resolutions(url):
    opts = {'quiet': True, 'js_runtimes': {'node': {}}}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=False)
            res_list = {f"{f['height']}p" for f in info.get('formats', []) if f.get('height') and f.get('vcodec') != 'none'}
            return sorted(list(res_list), key=lambda x: int(x[:-1]), reverse=True)
    except: return ["720p", "480p", "360p"]

async def background_worker(update: Update, context: ContextTypes.DEFAULT_TYPE, mode, url, res=None, extra=None):
    uid = str(update.effective_user.id)
    status = await update.message.reply_text("⚡ Processing... Please wait.")

    # FORMAT SELECTION LOGIC IMPROVED
    q = res.replace("p","") if res else "720"
    # Burası kilit nokta: İstediğin kalite yoksa sırasıyla altındakini veya en iyisini dener.
    format_selector = f"bestvideo[height<={q}]+bestaudio/best[height<={q}]/best"

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "output.mp4")

            if mode == "video":
                cmd = f'yt-dlp {" ".join(YDL_BASE_ARGS)} -f "{format_selector}" --merge-output-format mp4 -o "{out_path}" "{url}"'
                await (await asyncio.create_subprocess_shell(cmd)).communicate()
                if os.path.exists(out_path):
                    await context.bot.send_video(uid, video=open(out_path, "rb"), caption=f"✅ Done!")

            elif mode == "clip":
                start, end = extra
                cmd = f'yt-dlp {" ".join(YDL_BASE_ARGS)} -f "{format_selector}" --download-sections "*{start}-{end}" --downloader-args "ffmpeg:-c:v libx264 -c:a aac" --merge-output-format mp4 -o "{out_path}" "{url}"'
                await (await asyncio.create_subprocess_shell(cmd)).communicate()
                if os.path.exists(out_path):
                    await context.bot.send_video(uid, video=open(out_path, "rb"), caption=f"✂️ Clip ({start}-{end})")

            elif mode == "ss":
                with yt_dlp.YoutubeDL({'quiet':True, 'noplaylist':True}) as ydl:
                    info = await asyncio.to_thread(ydl.extract_info, url, download=False)
                    stream = info.get('url') or info.get('formats')[-1].get('url')
                ss_img = os.path.join(tmpdir, "ss.jpg")
                cmd = f'ffmpeg -loglevel error -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {extra} -i "{stream}" -frames:v 1 -q:v 2 "{ss_img}" -y'
                await (await asyncio.create_subprocess_shell(cmd)).communicate()
                if os.path.exists(ss_img):
                    await context.bot.send_photo(uid, photo=open(ss_img, "rb"), caption=f"📸 Screenshot at {extra}")

            elif mode == "cover":
                cmd = f'yt-dlp --skip-download --write-thumbnail -o "{tmpdir}/thumb" "{url}"'
                await (await asyncio.create_subprocess_shell(cmd)).communicate()
                actual_img = next((os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.startswith('thumb')), None)
                if actual_img:
                    await context.bot.send_photo(uid, photo=open(actual_img, "rb"), caption="🖼 Cover")

            if int(uid) not in ADMIN_IDS and not user_db[uid].get("premium"):
                user_db[uid]["count"] += 1; save_db()

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    finally:
        user_db[uid].update({"mode": None, "url": None, "res": None})
        try: await status.delete()
        except: pass
        await update.message.reply_text("Action completed.", reply_markup=main_keyboard())

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update, context): return
    user = update.effective_user
    uid = str(user.id)
    caption = f"📩 **New Payment Proof!**\n\nFrom: {user.first_name} (@{user.username})\nID: `{uid}`"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.forward_message(chat_id=admin_id, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
            await context.bot.send_message(chat_id=admin_id, text=caption, parse_mode="Markdown")
        except: pass
    await update.message.reply_text("✅ Your proof has been sent to admins. We will process it soon.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    args = context.args
    if not await is_subscribed(update, context):
        if uid not in user_db:
            user_db[uid] = {"mode": None, "url": None, "count": 0, "premium": False, "res": None, "refs": 0}
            save_db()
        return
    if uid not in user_db:
        user_db[uid] = {"mode": None, "url": None, "count": 0, "premium": False, "res": None, "refs": 0}
        if args and args[0].isdigit():
            ref_id = args[0]
            if ref_id in user_db and ref_id != uid:
                user_db[ref_id]["refs"] = user_db[ref_id].get("refs", 0) + 1
                try: await context.bot.send_message(chat_id=ref_id, text=f"🎉 Someone joined via your link!")
                except: pass
        save_db()
    await update.message.reply_text("Bot Ready!", reply_markup=main_keyboard())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update, context): return
    uid = str(update.effective_user.id)
    if uid not in user_db: user_db[uid] = {"mode": None, "url": None, "count": 0, "premium": False, "res": None, "refs": 0}
    text = update.message.text
    is_admin = int(uid) in ADMIN_IDS

    if text == "🎬 Download Video":
        user_db[uid]["mode"] = "v_url"; await update.message.reply_text("Send YouTube link:")
    elif text == "✂️ Clip Video":
        user_db[uid]["mode"] = "c_url"; await update.message.reply_text("Send link for Clip:")
    elif text == "📸 Screenshot":
        user_db[uid]["mode"] = "s_url"; await update.message.reply_text("Send link for SS:")
    elif text == "🖼 Cover":
        user_db[uid]["mode"] = "cv_url"; await update.message.reply_text("Send link for Cover:")
    elif text == "🔗 Referral":
        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={uid}"
        msg = f"🔗 **Your Referral Link:**\n`{ref_link}`\n\n👥 **Referrals:** {user_db[uid].get('refs', 0)}\n 🎁 Each referral increases daily limit by +1."
        await update.message.reply_text(msg, parse_mode="Markdown")
    elif text == "💎 Premium":
        if user_db[uid].get("premium") or is_admin:
            await update.message.reply_text("🌟 You are already a Premium user!")
        else:
            msg = f"💎 **Join Premium!**\nTransfer **0.0005 BTC** to:\n`{BTC_ADDRESS}`\n**Send a photo of the receipt here.**"
            await update.message.reply_text(msg, parse_mode="Markdown")
    elif text == "ℹ️ Info":
        is_prem = user_db[uid].get("premium") or is_admin
        if is_prem: status_msg = "🌟 **Status:** Premium User"
        else:
            ref_bonus = user_db[uid].get("refs", 0)
            current_limit = VIDEO_LIMIT + ref_bonus
            left = current_limit - user_db[uid]["count"]
            status_msg = f"👤 **Status:** Regular User\n**Daily Limit:** {current_limit}\n**Remaining:** {max(0, left)}/{current_limit}"
        await update.message.reply_text(status_msg, parse_mode="Markdown")
    elif text == "✅ Finish":
        user_db[uid].update({"mode": None, "url": None, "res": None})
        await update.message.reply_text("System Reset.", reply_markup=main_keyboard())
    elif text == "👥 Total Users" and is_admin:
        await update.message.reply_text(f"Total Users: {len(user_db)}")
    elif text == "🌟 Prem Users" and is_admin:
        prems = [u for u in user_db if user_db[u].get("premium")]
        await update.message.reply_text(f"Premium Users: {len(prems)}")
    elif text == "➕ Add Premium" and is_admin:
        user_db[uid]["mode"] = "admin_add_prem"
        await update.message.reply_text("Send the ID of the user to make Premium:")
    elif text == "📢 Broadcast" and is_admin:
        user_db[uid]["mode"] = "admin_broadcast"
        await update.message.reply_text("Send broadcast message:")
    elif text == "🔙 Back to Main Menu":
        await update.message.reply_text("Main Menu:", reply_markup=main_keyboard())
    elif text.startswith("http"):
        mode = user_db[uid].get("mode")
        if mode in ["v_url", "c_url"]:
            s = await update.message.reply_text("Analyzing... 🔍")
            res_list = await get_resolutions(text)
            user_db[uid].update({"url": text, "mode": "wait_res_" + mode})
            await s.delete()
            await update.message.reply_text("Resolution:", reply_markup=ReplyKeyboardMarkup([[r] for r in res_list], resize_keyboard=True))
        elif mode == "s_url":
            user_db[uid].update({"url": text, "mode": "w_ss"})
            await update.message.reply_text("Time (e.g. 01:20):")
        elif mode == "cv_url": asyncio.create_task(background_worker(update, context, "cover", text))
    elif user_db[uid].get("url") or (user_db[uid].get("mode") and user_db[uid]["mode"].startswith("admin_")):
        mode = user_db[uid]["mode"]
        if mode == "wait_res_v_url": asyncio.create_task(background_worker(update, context, "video", user_db[uid]["url"], res=text))
        elif mode == "wait_res_c_url":
            user_db[uid].update({"res": text, "mode": "w_c_final"})
            await update.message.reply_text("Interval (e.g. 00:10-00:20):")
        elif mode == "w_c_final":
            asyncio.create_task(background_worker(update, context, "clip", user_db[uid]["url"], res=user_db[uid]["res"], extra=text.split("-")))
        elif mode == "w_ss": asyncio.create_task(background_worker(update, context, "ss", user_db[uid]["url"], extra=text))
        elif mode == "admin_add_prem":
            if text in user_db:
                user_db[text]["premium"] = True; save_db()
                await update.message.reply_text(f"✅ User {text} is Premium!", reply_markup=admin_keyboard())
            user_db[uid]["mode"] = None
        elif mode == "admin_broadcast":
            for user_id in user_db:
                try: await context.bot.send_message(chat_id=user_id, text=f"📢 **Announcement:**\n\n{text}", parse_mode="Markdown")
                except: pass
            await update.message.reply_text("✅ Sent.", reply_markup=admin_keyboard())
            user_db[uid]["mode"] = None

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if int(update.effective_user.id) in ADMIN_IDS:
        await update.message.reply_text("🛠 **Admin Panel**", reply_markup=admin_keyboard())

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    print("Bot is LIVE (Improved Fallback Quality)...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
      
