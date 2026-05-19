# =============================================================
# MOSES BOT — FULLY FIXED STARTUP + 409 FIX
# =============================================================

import os
import sys
import time
import json
import signal
import traceback
import tempfile
import shutil
import subprocess
import logging
import re

from pathlib import Path
from datetime import datetime, timezone

# ─────────────────────────────────────────────
# REQUIRED LIBRARIES
# ─────────────────────────────────────────────

import requests
import telebot
from telebot import types
import yt_dlp

# Optional speech recognition
try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_ENABLED = True
except ImportError:
    sr = None
    SPEECH_RECOGNITION_ENABLED = False

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.getLogger("telebot").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ─────────────────────────────────────────────
# TOKENS / ENV
# ─────────────────────────────────────────────

TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
ELEVEN_KEY = os.getenv("ELEVENLABS_KEY", "")

# Validate token
if not TOKEN:
    print("[FATAL] BOT_TOKEN missing.")
    sys.exit(1)

# ─────────────────────────────────────────────
# FILES
# ─────────────────────────────────────────────

COOKIE_FILE = "cookies.txt"
MEMORY_FILE = "memory.json"
HISTORY_FILE = "history.json"
CHAT_LOG_FILE = "chat_log.txt"

# ─────────────────────────────────────────────
# SAFE JSON SAVE
# ─────────────────────────────────────────────

def _save_json(path: str, data: dict):
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(temp_path, path)

def _load_json(path: str):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

# ─────────────────────────────────────────────
# MEMORY
# ─────────────────────────────────────────────

_memory = _load_json(MEMORY_FILE)
_history = _load_json(HISTORY_FILE)

# ─────────────────────────────────────────────
# TELEGRAM BOT INIT
# ─────────────────────────────────────────────

bot = telebot.TeleBot(
    TOKEN,
    parse_mode="HTML",
    threaded=True,
    num_threads=4,
)

# ─────────────────────────────────────────────
# GROQ AI
# ─────────────────────────────────────────────

AI_ENABLED = False
groq_client = None

try:
    from groq import Groq

    if GROQ_API_KEY:
        groq_client = Groq(api_key=GROQ_API_KEY)
        AI_ENABLED = True
        print("[AI] Groq loaded ✅")
    else:
        print("[AI] GROQ_API_KEY missing.")

except Exception as e:
    print(f"[AI] Groq failed: {e}")

# ─────────────────────────────────────────────
# OPENAI
# ─────────────────────────────────────────────

OPENAI_ENABLED = False
openai_client = None

if OPENAI_KEY:
    try:
        import openai

        openai_client = openai.OpenAI(api_key=OPENAI_KEY)
        OPENAI_ENABLED = True

        print("[AI] OpenAI loaded ✅")

    except Exception as e:
        print(f"[AI] OpenAI failed: {e}")
else:
    print("[AI] OpenAI disabled.")

# ─────────────────────────────────────────────
# FFMPEG DETECTION
# ─────────────────────────────────────────────

def find_ffmpeg():
    candidates = [
        "ffmpeg",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]

    for p in candidates:
        try:
            r = subprocess.run(
                [p, "-version"],
                capture_output=True,
                timeout=5,
            )

            if r.returncode == 0:
                print(f"[FFMPEG] Found: {p} ✅")
                return p

        except Exception:
            pass

    print("[FFMPEG] Not found.")
    return None

FFMPEG = find_ffmpeg()

# ─────────────────────────────────────────────
# ANTI-SPAM
# ─────────────────────────────────────────────

LAST_MESSAGE_TIME = {}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def uid(user_id):
    return str(user_id)

def add_to_history(user_id, role, content):
    u = uid(user_id)

    if u not in _history:
        _history[u] = []

    _history[u].append({
        "role": role,
        "content": content,
        "ts": datetime.now(timezone.utc).isoformat()
    })

    if len(_history[u]) > 200:
        _history[u] = _history[u][-150:]

    _save_json(HISTORY_FILE, _history)

# ─────────────────────────────────────────────
# AI REPLY
# ─────────────────────────────────────────────

def ai_complete(prompt: str):

    if not AI_ENABLED:
        return "AI is currently unavailable."

    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=300,
            messages=[
                {
                    "role": "system",
                    "content": "You are Moses, a casual friendly assistant."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return resp.choices[0].message.content.strip()

    except Exception as e:
        print(f"[AI ERROR] {e}")
        return "something broke on my side 😭"

# ─────────────────────────────────────────────
# VIDEO DOWNLOAD
# ─────────────────────────────────────────────

def cleanup(temp_dir):
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)

def download_file(url):

    temp_dir = tempfile.mkdtemp()

    out_tmpl = os.path.join(
        temp_dir,
        "%(title).120s.%(ext)s"
    )

    opts = {
        "outtmpl": out_tmpl,
        "quiet": True,
        "noplaylist": True,
        "retries": 10,
        "fragment_retries": 10,
        "continuedl": True,
        "socket_timeout": 60,
        "http_chunk_size": 1048576,
        "windowsfilenames": True,
        "cookiefile": COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            )
        },

        "format": (
            "bestvideo[height<=720]+bestaudio/"
            "best[height<=720]/best"
        ),

        "merge_output_format": "mp4",
    }

    if FFMPEG:
        opts["ffmpeg_location"] = FFMPEG

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:

            info = ydl.extract_info(url, download=True)

            if "entries" in info:
                info = list(info["entries"])[0]

            file_path = (
                info.get("requested_downloads", [{}])[0]
                .get("filepath")
            )

            if not file_path:
                file_path = ydl.prepare_filename(info)

            return file_path, temp_dir

    except Exception as e:
        print(f"[DOWNLOAD ERROR] {e}")

    cleanup(temp_dir)

    return None, None

# ─────────────────────────────────────────────
# SEND MEDIA
# ─────────────────────────────────────────────

def send_media(chat_id, file_path):

    if not os.path.exists(file_path):
        bot.send_message(chat_id, "❌ file missing")
        return

    size_mb = os.path.getsize(file_path) / (1024 * 1024)

    if size_mb > 49:
        bot.send_message(
            chat_id,
            f"❌ file too large ({size_mb:.1f}MB)"
        )
        return

    with open(file_path, "rb") as f:

        ext = Path(file_path).suffix.lower()

        if ext in [".mp3", ".wav", ".ogg", ".m4a"]:
            bot.send_audio(chat_id, f)
        else:
            bot.send_video(
                chat_id,
                f,
                supports_streaming=True
            )

# ─────────────────────────────────────────────
# START COMMAND
# ─────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):

    bot.send_message(
        message.chat.id,
        (
            "🤖 <b>Moses Bot v2.0</b>\n\n"
            "send me links, videos, code, or chat with me."
        )
    )

# ─────────────────────────────────────────────
# DOWNLOAD COMMAND
# ─────────────────────────────────────────────

@bot.message_handler(commands=["download"])
def cmd_download(message):

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        bot.send_message(
            message.chat.id,
            "usage:\n/download <url>"
        )
        return

    url = parts[1]

    msg = bot.send_message(
        message.chat.id,
        "⬇️ downloading..."
    )

    temp_dir = None

    try:
        fp, temp_dir = download_file(url)

        if not fp:
            bot.edit_message_text(
                "❌ download failed",
                message.chat.id,
                msg.message_id
            )
            return

        bot.delete_message(
            message.chat.id,
            msg.message_id
        )

        send_media(message.chat.id, fp)

    except Exception as e:
        print(f"[DOWNLOAD COMMAND ERROR] {e}")

        bot.send_message(
            message.chat.id,
            "⚠️ download failed"
        )

    finally:
        cleanup(temp_dir)

# ─────────────────────────────────────────────
# MAIN TEXT HANDLER
# ─────────────────────────────────────────────

@bot.message_handler(func=lambda m: True)
def handle_text(message):

    if not message.text:
        return

    text = message.text.strip()

    if not text:
        return

    user_id = message.from_user.id

    # Anti spam
    now = time.time()
    last = LAST_MESSAGE_TIME.get(user_id, 0)

    if now - last < 1:
        return

    LAST_MESSAGE_TIME[user_id] = now

    bot.send_chat_action(
        message.chat.id,
        "typing"
    )

    reply = ai_complete(text)

    add_to_history(user_id, "user", text)
    add_to_history(user_id, "assistant", reply)

    bot.send_message(
        message.chat.id,
        reply
    )

# ─────────────────────────────────────────────
# CLEAN SHUTDOWN
# ─────────────────────────────────────────────

BOT_RUNNING = False

def shutdown_handler(signum=None, frame=None):

    global BOT_RUNNING

    BOT_RUNNING = False

    print("\n[SHUTDOWN] stopping...")

    try:
        bot.stop_polling()
    except Exception:
        pass

    try:
        bot.remove_webhook()
    except Exception:
        pass

    print("[SHUTDOWN] done")

    sys.exit(0)

signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# ─────────────────────────────────────────────
# RUN BOT
# ─────────────────────────────────────────────

def run_bot():

    global BOT_RUNNING

    if BOT_RUNNING:
        print("[WARNING] already running")
        return

    BOT_RUNNING = True

    print("=" * 55)
    print("  Moses Bot v2.0 starting...")
    print(f"  AI:      {'✅ Groq' if AI_ENABLED else '❌'}")
    print(f"  OpenAI:  {'✅' if OPENAI_ENABLED else '❌'}")
    print(f"  FFMPEG:  {'✅' if FFMPEG else '❌'}")
    print("=" * 55)

    while BOT_RUNNING:

        try:
            print("[BOT] removing webhook...")

            bot.remove_webhook(
                drop_pending_updates=True
            )

            time.sleep(2)

            print("[BOT] starting polling...")

            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=30,
                skip_pending=True,
                allowed_updates=["message"],
                none_stop=True,
                interval=2,
            )

        except KeyboardInterrupt:
            shutdown_handler()

        except Exception as e:

            err = str(e)

            print(f"[CRASH] {err}")

            traceback.print_exc()

            # 409 FIX
            if "409" in err or "getUpdates request" in err:

                print("[FIX] another instance detected")

                try:
                    bot.stop_polling()
                except Exception:
                    pass

                time.sleep(15)
                continue

            # Network timeout
            if "Read timed out" in err:
                print("[NETWORK] timeout")
                time.sleep(5)
                continue

            print("[RETRY] restarting in 5 sec")
            time.sleep(5)

# ─────────────────────────────────────────────
# START
# ─────────────────────────────────────────────

if __name__ == "__main__":
    run_bot()
