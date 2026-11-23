import os
import tempfile
import httpx
import yt_dlp
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

application = Application.builder().token(BOT_TOKEN).build()

INSTRUCTIONS_TEXT = (
    "Bot Guide:\n\n"
    "1. Download Video:\n"
    "Send a public video link (for example from YouTube, Facebook, or another "
    "supported site). The bot checks the link, downloads the video, and sends "
    "it back.\n\n"
    "2. Gemini AI (Uses Your Own API Key):\n"
    "- Save your key: /setkey YOUR_GEMINI_API_KEY\n"
    "- Ask a question: /ai YOUR_QUESTION\n"
    "- Delete your key: /clearkey\n"
    "Responses start with a short, direct answer to save tokens.\n\n"
    "Commands:\n"
    "/start - Welcome and quick start\n"
    "/help - Full instructions\n"
    "/setkey - Save your Gemini API key\n"
    "/ai - Ask Gemini a question\n"
    "/clearkey - Remove your saved Gemini key\n\n"
    "Note: Only download videos you have permission to download. Private, "
    "login-gated, or DRM-protected videos may fail."
)


async def save_user_gemini_key(user_id: int, api_key: str) -> None:
    raise NotImplementedError("Connect save_user_gemini_key to your database.")


async def get_user_gemini_key(user_id: int) -> str | None:
    raise NotImplementedError("Connect get_user_gemini_key to your database.")


async def delete_user_gemini_key(user_id: int) -> None:
    raise NotImplementedError("Connect delete_user_gemini_key to your database.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(INSTRUCTIONS_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(INSTRUCTIONS_TEXT)


async def set_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Invalid format.\n"
            "Send your key alone after /setkey:\n"
            "/setkey AIzaSyYourKeyHere"
        )
        return

    api_key = context.args[0].strip()
    user_id = update.effective_user.id

    try:
        await save_user_gemini_key(user_id, api_key)
    except Exception:
        await update.message.reply_text(
            "Could not save your key right now. Please try again later."
        )
        return

    try:
        await update.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "Saved your Gemini API key.\n"
            "You can now ask questions with:\n"
            "/ai Explain how DNS works"
        ),
    )


async def clear_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    try:
        await delete_user_gemini_key(user_id)
    except Exception:
        await update.message.reply_text(
            "Could not remove your key right now. Please try again later."
        )
        return

    await update.message.reply_text("Your saved Gemini API key has been removed.")


async def ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Please include a question.\n"
            "Example: /ai What is a webhook?"
        )
        return

    question = " ".join(context.args).strip()
    user_id = update.effective_user.id

    try:
        user_key = await get_user_gemini_key(user_id)
    except Exception:
        await update.message.reply_text(
            "Could not load your API key right now. Please try again later."
        )
        return

    if not user_key:
        await update.message.reply_text(
            "No Gemini API key found for your account.\n"
            "First run:\n"
            "/setkey YOUR_GEMINI_API_KEY\n"
            "Then run:\n"
            "/ai YOUR_QUESTION"
        )
        return

    await update.message.chat.send_action("typing")

    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "Give a balanced, short, direct answer first. "
                        "Add brief supporting detail only when needed. "
                        "Do not repeat the question or pad output to save tokens."
                    )
                }
            ]
        },
        "contents": [
            {
                "parts": [{"text": question}]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 350,
            "temperature": 0.4,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                GEMINI_URL,
                headers={"x-goog-api-key": user_key},
                json=payload,
            )
    except httpx.TimeoutException:
        await update.message.reply_text("Gemini timed out. Try a shorter question.")
        return
    except Exception:
        await update.message.reply_text("Network error while contacting Gemini.")
        return

    if resp.status_code != 200:
        await update.message.reply_text(
            f"Gemini returned an error (HTTP {resp.status_code}). "
            "Check that your API key is valid and active."
        )
        return

    try:
        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        reply_text = "".join(p.get("text", "") for p in parts).strip()
    except Exception:
        reply_text = ""

    if not reply_text:
        await update.message.reply_text("Gemini returned an empty response.")
        return

    await update.message.reply_text(reply_text[:4000])


async def download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = update.message.text.strip()
    status_msg = await update.message.reply_text("Step 1/3: Checking link...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        ydl_opts = {
            "outtmpl": f"{tmp_dir}/video.%(ext)s",
            "format": "mp4/best[ext=mp4]/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }

        try:
            await status_msg.edit_text("Step 2/3: Downloading video...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = ydl.prepare_filename(info)
        except Exception:
            await status_msg.edit_text(
                "Download failed.\n"
                "Check that:\n"
                "- The URL is public and accessible\n"
                "- The site is not blocking automated downloads or requiring login\n"
                "- You have permission to download the video"
            )
            return

        if not os.path.exists(file_path):
            await status_msg.edit_text("Downloaded file could not be found.")
            return

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > 48:
            await status_msg.edit_text(
                f"File is {file_size_mb:.1f} MB, which exceeds the safe upload limit."
            )
            return

        try:
            await status_msg.edit_text("Step 3/3: Sending video to Telegram...")
            with open(file_path, "rb") as video_file:
                await update.message.reply_video(video=video_file)
            await status_msg.delete()
        except Exception:
            await status_msg.edit_text(
                "Video downloaded, but Telegram upload failed. "
                "The format or size may not be supported."
            )


application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("setkey", set_key))
application.add_handler(CommandHandler("clearkey", clear_key))
application.add_handler(CommandHandler("ai", ai))
application.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"^https?://"),
        download,
    )
)


async def handler(request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return {"statusCode": 403, "body": "Forbidden"}

    payload = await request.json()
    update = Update.de_json(payload, application.bot)
    await application.process_update(update)
    return {"statusCode": 200, "body": "OK"}
