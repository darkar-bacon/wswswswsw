import os
import json
import time
import re
from datetime import datetime, timezone

import telebot
from groq import Groq

# =========================================================
# ENV VARIABLES (Railway)
# =========================================================

BOT_TOKEN = os.getenv("8272287740:AAFVY5tHErqaj_llBrBFLnmZskckJEsAE7U")
GROQ_API_KEY = os.getenv("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")

if not BOT_TOKEN:
    raise ValueError("Missing BOT_TOKEN")

if not GROQ_API_KEY:
    raise ValueError("Missing GROQ_API_KEY")

# =========================================================
# BOT SETUP
# =========================================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
client = Groq(api_key=GROQ_API_KEY)

# =========================================================
# FILES
# =========================================================

MEMORY_FILE = "memory.json"
HISTORY_FILE = "history.json"

# =========================================================
# LOAD / SAVE
# =========================================================

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

memory_data = load_json(MEMORY_FILE)
history_data = load_json(HISTORY_FILE)

# =========================================================
# PERSONAS
# =========================================================

PERSONAS = {
    "me": """
Your name is Moses.

You are friendly, casual, funny, emotionally aware, and realistic.
Talk like a real friend.
Never say you are AI.
Keep replies short and natural.
""",

    "girl": """
Your name is Maya.

You are sweet, energetic, supportive, fun, and friendly.
Use casual texting style.
Never say you are AI.
""",

    "goth": """
Your name is Raven.

Dark humor, dry personality, chill energy.
Short responses.
Never say you are AI.
""",

    "femboy": """
Your name is Finn.

Cute, cheerful, fashionable, friendly.
Anime vibes.
Never say you are AI.
"""
}

DEFAULT_PERSONA = "me"

# =========================================================
# USER HELPERS
# =========================================================

def uid(user_id):
    return str(user_id)

def ensure_user(user_id):
    u = uid(user_id)

    if u not in memory_data:
        memory_data[u] = {
            "persona": DEFAULT_PERSONA,
            "facts": []
        }

    if u not in history_data:
        history_data[u] = []

    save_json(MEMORY_FILE, memory_data)
    save_json(HISTORY_FILE, history_data)

    return memory_data[u]

# =========================================================
# MEMORY
# =========================================================

def remember_fact(user_id, fact):
    ensure_user(user_id)

    u = uid(user_id)

    if fact not in memory_data[u]["facts"]:
        memory_data[u]["facts"].append(fact)

    memory_data[u]["facts"] = memory_data[u]["facts"][-50:]

    save_json(MEMORY_FILE, memory_data)

def get_memory_context(user_id):
    ensure_user(user_id)

    u = uid(user_id)

    facts = memory_data[u]["facts"]

    if not facts:
        return ""

    return "\n".join([f"- {x}" for x in facts[-15:]])

# =========================================================
# HISTORY
# =========================================================

def add_history(user_id, role, content):
    ensure_user(user_id)

    u = uid(user_id)

    history_data[u].append({
        "role": role,
        "content": content,
        "time": datetime.now(timezone.utc).isoformat()
    })

    history_data[u] = history_data[u][-20:]

    save_json(HISTORY_FILE, history_data)

def get_history(user_id):
    ensure_user(user_id)

    u = uid(user_id)

    return [
        {
            "role": x["role"],
            "content": x["content"]
        }
        for x in history_data[u][-10:]
    ]

def clear_history(user_id):
    ensure_user(user_id)

    history_data[uid(user_id)] = []

    save_json(HISTORY_FILE, history_data)

# =========================================================
# PERSONA
# =========================================================

def get_persona(user_id):
    ensure_user(user_id)

    return memory_data[uid(user_id)]["persona"]

def set_persona(user_id, persona):
    ensure_user(user_id)

    memory_data[uid(user_id)]["persona"] = persona

    save_json(MEMORY_FILE, memory_data)

# =========================================================
# AI
# =========================================================

def ai_reply(user_id, text):
    persona = get_persona(user_id)

    memory_context = get_memory_context(user_id)

    system_prompt = PERSONAS[persona]

    if memory_context:
        system_prompt += f"\n\nThings remembered about the user:\n{memory_context}"

    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    messages.extend(get_history(user_id))

    messages.append({
        "role": "user",
        "content": text
    })

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=300
        )

        reply = response.choices[0].message.content.strip()

    except Exception as e:
        print(f"[AI ERROR] {e}")
        return "something broke 😭"

    add_history(user_id, "user", text)
    add_history(user_id, "assistant", reply)

    return reply

# =========================================================
# COMMANDS
# =========================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    bot.reply_to(
        message,
        """
<b>Moses Bot</b>

💬 AI chat
🧠 Memory
🎭 Personas

Commands:
/me
/girl
/goth
/femboy
/reset
/remember
/memories
/persona
"""
    )

@bot.message_handler(commands=["reset"])
def reset_cmd(message):
    clear_history(message.from_user.id)

    bot.reply_to(message, "history cleared 🧹")

@bot.message_handler(commands=["persona"])
def persona_cmd(message):
    p = get_persona(message.from_user.id)

    bot.reply_to(message, f"current persona: <b>{p}</b>")

@bot.message_handler(commands=["remember"])
def remember_cmd(message):
    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        bot.reply_to(message, "usage:\n/remember something")
        return

    fact = parts[1]

    remember_fact(message.from_user.id, fact)

    bot.reply_to(message, "locked in 🧠")

@bot.message_handler(commands=["memories"])
def memories_cmd(message):
    text = get_memory_context(message.from_user.id)

    if not text:
        text = "nothing stored yet"

    bot.reply_to(message, text)

# =========================================================
# PERSONA COMMANDS
# =========================================================

@bot.message_handler(commands=["me"])
def me_cmd(message):
    set_persona(message.from_user.id, "me")
    bot.reply_to(message, "moses activated 😎")

@bot.message_handler(commands=["girl"])
def girl_cmd(message):
    set_persona(message.from_user.id, "girl")
    bot.reply_to(message, "maya activated 💕")

@bot.message_handler(commands=["goth"])
def goth_cmd(message):
    set_persona(message.from_user.id, "goth")
    bot.reply_to(message, "raven activated 🖤")

@bot.message_handler(commands=["femboy"])
def femboy_cmd(message):
    set_persona(message.from_user.id, "femboy")
    bot.reply_to(message, "finn activated 🌸")

# =========================================================
# AUTO MEMORY
# =========================================================

FACT_TRIGGERS = [
    "i like",
    "i love",
    "i hate",
    "my favorite",
    "i enjoy",
    "im into",
    "i'm into"
]

def auto_memory(user_id, text):
    lower = text.lower()

    for trigger in FACT_TRIGGERS:
        if trigger in lower:
            remember_fact(user_id, text[:120])
            break

# =========================================================
# TEXT HANDLER
# =========================================================

@bot.message_handler(func=lambda m: True)
def text_handler(message):
    if not message.text:
        return

    text = message.text.strip()

    if not text:
        return

    user_id = message.from_user.id

    auto_memory(user_id, text)

    bot.send_chat_action(message.chat.id, "typing")

    reply = ai_reply(user_id, text)

    bot.reply_to(message, reply)

# =========================================================
# RUN
# =========================================================

print("=" * 50)
print("Moses Bot Running")
print("=" * 50)

while True:
    try:
        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=60,
            skip_pending=True
        )

    except Exception as e:
        print(f"[CRASH] {e}")
        time.sleep(5)
