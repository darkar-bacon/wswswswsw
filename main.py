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

import requests
import telebot
from telebot import types
import yt_dlp

BOT_RUNNING = False

# ─────────────────────────────────────────────
# SAFE JSON SAVE
# Prevents corrupted memory/history files
# ─────────────────────────────────────────────

def _save_json(path: str, data: dict):
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(temp_path, path)

# ─────────────────────────────────────────────
# BETTER TELEBOT INIT
# ─────────────────────────────────────────────

bot = telebot.TeleBot(
    TOKEN,
    parse_mode="HTML",
    threaded=True,
    num_threads=4,
)

# ─────────────────────────────────────────────
# SHUTDOWN HANDLER
# ─────────────────────────────────────────────

def shutdown_handler(signum=None, frame=None):
    global BOT_RUNNING

    BOT_RUNNING = False

    print("\n[SHUTDOWN] Stopping bot cleanly...")

    try:
        bot.stop_polling()
    except Exception:
        pass

    try:
        bot.remove_webhook()
    except Exception:
        pass

    print("[SHUTDOWN] Done.")
    sys.exit(0)

# Handle Ctrl+C / container shutdown
signal.signal(signal.SIGINT, shutdown_handler)
signal.signal(signal.SIGTERM, shutdown_handler)

# ─────────────────────────────────────────────
# ANTI-SPAM SYSTEM
# ─────────────────────────────────────────────

LAST_MESSAGE_TIME = {}

# ─────────────────────────────────────────────
# MAIN RUN FUNCTION
# ─────────────────────────────────────────────

def run_bot():
    global BOT_RUNNING

    if BOT_RUNNING:
        print("[WARNING] Bot already running.")
        return

    BOT_RUNNING = True

    print("=" * 55)
    print("  Moses Bot v2.0 starting...")
    print(f"  AI:      {'✅ Groq' if AI_ENABLED else '❌'}")
    print(f"  OpenAI:  {'✅' if OPENAI_ENABLED else '❌ (optional)'}")
    print(f"  FFMPEG:  {'✅' if FFMPEG else '❌ install ffmpeg!'}")
    print(f"  Memory:  ✅ (files: {MEMORY_FILE}, {HISTORY_FILE})")
    print("=" * 55)

    while BOT_RUNNING:
        try:
            print("[BOT] Cleaning old Telegram sessions...")

            # Remove any webhook
            bot.remove_webhook(drop_pending_updates=True)

            # Small delay so Telegram fully resets
            time.sleep(2)

            print("[BOT] Starting polling...")

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

            # ─────────────────────────────
            # FIX 409 TELEGRAM CONFLICT
            # ─────────────────────────────

            if "409" in err or "getUpdates request" in err:
                print("[FIX] Another bot instance is running.")
                print("[FIX] Waiting before reconnecting...")

                try:
                    bot.stop_polling()
                except Exception:
                    pass

                time.sleep(15)
                continue

            # Network reconnects
            if "Read timed out" in err:
                print("[NETWORK] Telegram timeout.")
                time.sleep(5)
                continue

            # Generic retry
            print("[RETRY] Restarting in 5 seconds...")
            time.sleep(5)

# ─────────────────────────────────────────────
# BETTER DOWNLOAD SETTINGS
# ─────────────────────────────────────────────

def download_file(url: str):
    temp_dir = tempfile.mkdtemp()
    out_tmpl = os.path.join(temp_dir, "%(title).120s.%(ext)s")

    base = {
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
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
    }

    if FFMPEG:
        base["ffmpeg_location"] = FFMPEG

    opts = {
        **base,
        "format": (
            "bestvideo[height<=720]+bestaudio/"
            "best[height<=720]/best"
        ),
        "merge_output_format": "mp4",
    }

    fp, meta = safe_download(url, temp_dir, opts)

    if fp and os.path.exists(fp):
        return fp, temp_dir, meta

    opts2 = {
        **base,
        "format": "best",
    }

    fp, meta = safe_download(url, temp_dir, opts2)

    if fp and os.path.exists(fp):
        return fp, temp_dir, meta

    cleanup(temp_dir)
    return None, None, None

# ─────────────────────────────────────────────
# TEXT HANDLER WITH ANTI-SPAM
# ─────────────────────────────────────────────

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    if not message.text:
        return

    text = message.text.strip()

    if not text:
        return

    user_id = message.from_user.id

    # ─────────────────────────────
    # ANTI-SPAM
    # ─────────────────────────────

    now = time.time()
    last = LAST_MESSAGE_TIME.get(user_id, 0)

    if now - last < 1:
        return

    LAST_MESSAGE_TIME[user_id] = now

    # Continue your existing logic here...
    # your old handle_text code goes below this line

# ─────────────────────────────────────────────
# START BOT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    run_bot()
