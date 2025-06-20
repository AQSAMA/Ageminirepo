import os
import logging
import threading
import base64
import requests
from io import BytesIO
from flask import Flask
from werkzeug.serving import make_server
from telegram import Update, File
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
import PyPDF2

# ---------------------------
# 1. UPTIME: Flask server
# ---------------------------

flask_app = Flask('')

@flask_app.route('/')
def home():
    return 'Telegram Gemini Bot is alive!'

def run_flask():
    make_server('0.0.0.0', 8080, flask_app).serve_forever()

threading.Thread(target=run_flask, daemon=True).start()

# ---------------------------
# 2. SETUP: Logging & Keys
# ---------------------------

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

# ---------------------------
# 3. Gemini API Caller
# ---------------------------

def call_gemini(parts: list[dict]) -> str:
    """
    Send a multimodal prompt to Gemini 2.5-flash.
    `parts` is a list of dicts, each with one of:
      { "text": str }
      { "image": { "mimeType": str, "data": base64_str } }
      { "audio": { "mimeType": str, "data": base64_str } }
      { "video": { "mimeType": str, "data": base64_str } }
    Returns the assistant’s text reply.
    """
    headers = {"Content-Type": "application/json"}
    params  = {"key": GEMINI_API_KEY}
    body = {"contents": [{"parts": parts}]}

    resp = requests.post(GEMINI_URL, params=params, headers=headers, json=body)
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        logger.error(f"Unexpected response format: {e}")
        return "Gemini returned an unexpected response."

# ---------------------------
# 4. Handlers
# ---------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hello! I am your multimodal Gemini 2.5-flash bot.\n"
        "Send text, images, audio, video, or PDFs."
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text
    parts = [{"text": user_text}]
    try:
        reply = call_gemini(parts)
    except Exception as e:
        logger.error(f"Gemini error (text): {e}")
        reply = "Error contacting Gemini."
    await update.message.reply_text(reply)

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Download highest-resolution photo
    file: File = await update.message.photo[-1].get_file()
    bio = BytesIO()
    await file.download_to_memory(out=bio)
    b64 = base64.b64encode(bio.getvalue()).decode('utf-8')
    parts = [
        {"text": "Please analyze this image:"},
        {"image": {"mimeType": "image/jpeg", "data": b64}}
    ]
    try:
        reply = call_gemini(parts)
    except Exception as e:
        logger.error(f"Gemini error (image): {e}")
        reply = "Error processing image."
    await update.message.reply_text(reply)

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    if doc.mime_type == 'application/pdf':
        file: File = await doc.get_file()
        bio = BytesIO(await file.download_as_bytearray())
        reader = PyPDF2.PdfReader(bio)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        prompt = f"Extracted text from PDF:\n{text}\n\nPlease summarize."
        parts = [{"text": prompt}]
        try:
            reply = call_gemini(parts)
        except Exception as e:
            logger.error(f"Gemini error (pdf): {e}")
            reply = "Error processing PDF."
    else:
        reply = f"Unsupported document type: {doc.mime_type}"
    await update.message.reply_text(reply)

async def audio_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    audio = update.message.effective_attachment or update.message.voice
    file: File = await audio.get_file()
    bio = BytesIO()
    await file.download_to_memory(out=bio)
    b64 = base64.b64encode(bio.getvalue()).decode('utf-8')
    parts = [
        {"text": "Please transcribe or analyze this audio:"},
        {"audio": {"mimeType": audio.mime_type or "audio/ogg", "data": b64}}
    ]
    try:
        reply = call_gemini(parts)
    except Exception as e:
        logger.error(f"Gemini error (audio): {e}")
        reply = "Error processing audio."
    await update.message.reply_text(reply)

async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    video = update.message.video
    file: File = await video.get_file()
    bio = BytesIO()
    await file.download_to_memory(out=bio)
    b64 = base64.b64encode(bio.getvalue()).decode('utf-8')
    parts = [
        {"text": "Please analyze this video:"},
        {"video": {"mimeType": "video/mp4", "data": b64}}
    ]
    try:
        reply = call_gemini(parts)
    except Exception as e:
        logger.error(f"Gemini error (video): {e}")
        reply = "Error processing video."
    await update.message.reply_text(reply)

# ---------------------------
# 5. Main
# ---------------------------

def main() -> None:
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",    start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.PHOTO,   photo_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    app.add_handler(MessageHandler(filters.VOICE  | filters.AUDIO, audio_handler))
    app.add_handler(MessageHandler(filters.VIDEO,   video_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
