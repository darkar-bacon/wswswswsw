import os
import json
import time
import traceback
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import requests
import telebot

# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("8272287740:AAFVY5tHErqaj_llBrBFLnmZskckJEsAE7U")
GROQ_API_KEY = os.getenv("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")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

if not TOKEN:
    raise ValueError("Missing BOT_TOKEN")

if not GROQ_API_KEY:
    raise ValueError("Missing GROQ_API_KEY")

MEMORY_FILE = "memory.json"
HISTORY_FILE = "history.json"

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(level=logging.INFO)

logging.getLogger("telebot").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

# =========================================================
# BOT
# =========================================================

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# =========================================================
# AI
# =========================================================

from groq import Groq

groq_client = Groq(api_key=GROQ_API_KEY)

OPENAI_ENABLED = False
openai_client = None

if OPENAI_KEY:
    try:
        from openai import OpenAI

        openai_client = OpenAI(api_key=OPENAI_KEY)
        OPENAI_ENABLED = True
        print("[AI] OpenAI enabled")
    except Exception as e:
        print(f"[OPENAI] {e}")

# =========================================================
# MEMORY
# =========================================================

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_json(path, data):
    temp = path + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(temp, path)

memory = load_json(MEMORY_FILE)
history = load_json(HISTORY_FILE)

MAX_HISTORY = 80

def uid(user_id):
    return str(user_id)

def ensure_user(user_id):
    u = uid(user_id)

    if u not in memory:
        memory[u] = {
            "persona": "me",
            "facts": [],
        }

    return memory[u]

def remember_fact(user_id, fact):
    state = ensure_user(user_id)

    if fact not in state["facts"]:
        state["facts"].append(fact)

    state["facts"] = state["facts"][-20:]

    save_json(MEMORY_FILE, memory)

def add_history(user_id, role, content):
    u = uid(user_id)

    if u not in history:
        history[u] = []

    history[u].append({
        "role": role,
        "content": content,
        "ts": datetime.now(timezone.utc).isoformat()
    })

    history[u] = history[u][-MAX_HISTORY:]

    save_json(HISTORY_FILE, history)

def get_history(user_id, n=12):
    u = uid(user_id)

    if u not in history:
        return []

    return [
        {
            "role": x["role"],
            "content": x["content"]
        }
        for x in history[u][-n:]
    ]

def clear_history(user_id):
    history[uid(user_id)] = []
    save_json(HISTORY_FILE, history)

# =========================================================
# PERSONAS
# =========================================================

PERSONAS = {
    "me": """
Your name is Moses.
You are chill, funny, casual, and emotionally aware.
You talk naturally like a real friend.
Keep replies short unless more detail is needed.
Never say you're an AI.
""",

    "girl": """
Your name is Maya.
You are upbeat, sweet, energetic, and supportive.
Use casual texting style.
Never say you're an AI.
""",

    "goth": """
Your name is Raven.
Dry humor. Dark aesthetic. Calm and sarcastic.
Never rude.
Never say you're an AI.
""",

    "femboy": """
Your name is Finn.
Cute, cheerful, stylish, and friendly.
Never say you're an AI.
"""
}

def get_persona(user_id):
    return ensure_user(user_id).get("persona", "me")

def set_persona(user_id, persona):
    state = ensure_user(user_id)
    state["persona"] = persona
    save_json(MEMORY_FILE, memory)

# =========================================================
# SAFE SEND
# =========================================================

def send_reply(chat_id, text):
    MAX_LEN = 4000

    for i in range(0, len(text), MAX_LEN):
        bot.send_message(chat_id, text[i:i + MAX_LEN])

# =========================================================
# SEARCH
# =========================================================

def web_search(query):
    try:
        url = (
            "https://api.duckduckgo.com/"
            f"?q={requests.utils.quote(query)}"
            "&format=json&no_html=1"
        )

        r = requests.get(url, timeout=10)

        data = r.json()

        if data.get("AbstractText"):
            return data["AbstractText"][:500]

        for topic in data.get("RelatedTopics", []):
            if isinstance(topic, dict) and topic.get("Text"):
                return topic["Text"][:400]

    except Exception as e:
        print(f"[SEARCH] {e}")

    return ""

# =========================================================
# IMAGE VISION
# =========================================================

def get_image_reply(user_id, image_bytes, caption=""):
    if not OPENAI_ENABLED:
        return "image understanding isn't enabled rn"

    import base64

    b64 = base64.b64encode(image_bytes).decode()

    persona = PERSONAS[get_persona(user_id)]

    prompt = "React naturally to this image."

    if caption:
        prompt += f" Caption: {caption}"

    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=250,
            messages=[
                {
                    "role": "system",
                    "content": persona
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}"
                            }
                        }
                    ]
                }
            ]
        )

        return resp.choices[0].message.content.strip()

    except Exception as e:
        print(f"[VISION] {e}")
        return "couldn't read that image rn"

# =========================================================
# AI CHAT
# =========================================================

LAST_MESSAGE = {}

def ai_reply(user_id, text):
    now = time.time()

    if now - LAST_MESSAGE.get(user_id, 0) < 1:
        return "slow down 😭"

    LAST_MESSAGE[user_id] = now

    lower = text.lower()

    if lower.startswith("i like"):
        remember_fact(user_id, text)

    persona = PERSONAS[get_persona(user_id)]

    facts = ensure_user(user_id).get("facts", [])

    memory_context = ""

    if facts:
        memory_context = (
            "\nThings remembered about the user:\n"
            + "\n".join(f"- {x}" for x in facts[-10:])
        )

    messages = [
        {
            "role": "system",
            "content": persona + memory_context
        },
        *get_history(user_id),
        {
            "role": "user",
            "content": text
        }
    ]

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=300,
            messages=messages
        )

        reply = response.choices[0].message.content.strip()

    except Exception as e:
        print(f"[AI] {e}")
        reply = "my brain lagged give me a sec 😭"

    add_history(user_id, "user", text)
    add_history(user_id, "assistant", reply)

    return reply

# =========================================================
# COMMANDS
# =========================================================

@bot.message_handler(commands=["start"])
def start(message):
    send_reply(
        message.chat.id,
        """
🤖 <b>Moses Bot</b>

🧠 AI companion with memory
💬 Natural conversations
📸 Image understanding
💻 Coding help
🔍 Web search

Commands:
/me
/girl
/goth
/femboy
/reset
/history
/persona
/search
"""
    )

@bot.message_handler(commands=["me"])
def me(message):
    set_persona(message.from_user.id, "me")
    send_reply(message.chat.id, "back to moses 😎")

@bot.message_handler(commands=["girl"])
def girl(message):
    set_persona(message.from_user.id, "girl")
    send_reply(message.chat.id, "maya here 💕")

@bot.message_handler(commands=["goth"])
def goth(message):
    set_persona(message.from_user.id, "goth")
    send_reply(message.chat.id, "...raven 🖤")

@bot.message_handler(commands=["femboy"])
def femboy(message):
    set_persona(message.from_user.id, "femboy")
    send_reply(message.chat.id, "finn here 🌸")

@bot.message_handler(commands=["reset"])
def reset(message):
    clear_history(message.from_user.id)
    send_reply(message.chat.id, "history cleared")

@bot.message_handler(commands=["persona"])
def persona(message):
    p = get_persona(message.from_user.id)
    send_reply(message.chat.id, f"current persona: {p}")

@bot.message_handler(commands=["history"])
def show_history(message):
    data = get_history(message.from_user.id, 10)

    if not data:
        send_reply(message.chat.id, "no history yet")
        return

    text = []

    for item in data:
        role = "You" if item["role"] == "user" else "Bot"
        text.append(f"{role}: {item['content']}")

    send_reply(message.chat.id, "\n\n".join(text))

@bot.message_handler(commands=["search"])
def search(message):
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        send_reply(message.chat.id, "usage: /search cats")
        return

    query = parts[1]

    result = web_search(query)

    if not result:
        send_reply(message.chat.id, "couldn't find much")
        return

    reply = ai_reply(
        message.from_user.id,
        f"Search result for '{query}':\n\n{result}"
    )

    send_reply(message.chat.id, reply)

# =========================================================
# PHOTO
# =========================================================

@bot.message_handler(content_types=["photo"])
def photo(message):
    if not OPENAI_ENABLED:
        send_reply(message.chat.id, "vision isn't enabled")
        return

    try:
        file_info = bot.get_file(message.photo[-1].file_id)

        downloaded = bot.download_file(file_info.file_path)

        caption = message.caption or ""

        reply = get_image_reply(
            message.from_user.id,
            downloaded,
            caption
        )

        send_reply(message.chat.id, reply)

    except Exception as e:
        print(f"[PHOTO] {e}")
        send_reply(message.chat.id, "couldn't process image")

# =========================================================
# MAIN TEXT
# =========================================================

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    try:
        if not message.text:
            return

        text = message.text.strip()

        if not text:
            return

        user_id = message.from_user.id

        bot.send_chat_action(message.chat.id, "typing")

        reply = ai_reply(user_id, text)

        send_reply(message.chat.id, reply)

    except Exception as e:
        print(f"[TEXT] {e}")
        traceback.print_exc()

        send_reply(
            message.chat.id,
            "something broke 😭"
        )

# =========================================================
# RUN
# =========================================================

def run_bot():
    print("=" * 50)
    print("Moses Bot starting...")
    print("Railway optimized build")
    print("=" * 50)

    bot.remove_webhook()

    while True:
        try:
            bot.infinity_polling(
                timeout=20,
                long_polling_timeout=20,
                skip_pending=True,
                allowed_updates=["message"]
            )

        except Exception as e:
            print(f"[CRASH] {e}")
            traceback.print_exc()

            time.sleep(10)

if __name__ == "__main__":
    run_bot()
