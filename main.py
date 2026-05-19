"""
=============================================================
  MOSES BOT — Full AI Companion v2.0
  Features: Long-term memory, voice mode, vision, multimodal,
  link understanding, coding assistant, retry/fallback, and more.
=============================================================

DEPENDENCIES — install before running:
  pip install pyTelegramBotAPI yt-dlp groq openai requests
  pip install pillow speechrecognition pydub
  pip install curl-cffi          # fixes TikTok
  pip install yt-dlp --upgrade   # always latest

FFMPEG — required for audio/video processing:
  Ubuntu/Debian:  sudo apt install ffmpeg
  Windows:        https://ffmpeg.org/download.html  (add to PATH)
  Mac:            brew install ffmpeg

ENVIRONMENT VARIABLES (or hardcode below for testing):
  BOT_TOKEN        — Telegram bot token
  GROQ_API_KEY     — Free at https://console.groq.com
  OPENAI_API_KEY   — Optional; used for TTS and vision fallback
  ELEVENLABS_KEY   — Optional; for premium ElevenLabs TTS

OPTIONAL: ElevenLabs voice IDs per persona can be configured
in the PERSONA_VOICE_IDS dict below.
=============================================================
"""

import os
import json
import time
import shutil
import tempfile
import textwrap
import subprocess
import traceback
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import requests
import telebot
from telebot import types
import yt_dlp

try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_ENABLED = True
except ImportError:
    sr = None
    SPEECH_RECOGNITION_ENABLED = False

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

TOKEN         = os.getenv("BOT_TOKEN",     "8272287740:AAFVY5tHErqaj_llBrBFLnmZskckJEsAE7U")
GROQ_API_KEY  = os.getenv("GROQ_API_KEY",  "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")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")
ELEVEN_KEY    = os.getenv("ELEVENLABS_KEY", "")   # optional

COOKIE_FILE   = "cookies.txt"
MEMORY_FILE   = "memory.json"
HISTORY_FILE  = "history.json"
CHAT_LOG_FILE = "chat_log.txt"

# ElevenLabs voice IDs per persona (fill in your own or leave empty → use OpenAI TTS)
PERSONA_VOICE_IDS = {
    "me":     "",
    "girl":   "",
    "goth":   "",
    "femboy": "",
}

# ─────────────────────────────────────────────
# BOT INIT
# ─────────────────────────────────────────────

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ─────────────────────────────────────────────
# AI CLIENTS
# ─────────────────────────────────────────────

try:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY)
    AI_ENABLED = True
    print("[AI] Groq loaded ✅")
except Exception as e:
    groq_client = None
    AI_ENABLED = False
    print(f"[AI] Groq unavailable: {e}")

OPENAI_ENABLED = False
openai_client  = None
if OPENAI_KEY:
    try:
        import openai
        openai_client  = openai.OpenAI(api_key=OPENAI_KEY)
        OPENAI_ENABLED = True
        print("[AI] OpenAI loaded ✅")
    except Exception as e:
        print(f"[AI] OpenAI unavailable: {e}")
else:
    print('[AI] OpenAI disabled: set OPENAI_API_KEY in your environment to enable vision and TTS.')

# Vision: try openai first, groq as fallback for image understanding
VISION_ENABLED = OPENAI_ENABLED or AI_ENABLED

# ─────────────────────────────────────────────
# FFMPEG
# ─────────────────────────────────────────────

def find_ffmpeg():
    candidates = ["ffmpeg",
                  r"C:\ffmpeg\bin\ffmpeg.exe",
                  r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                  r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
                  "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    for p in candidates:
        try:
            r = subprocess.run([p, "-version"], capture_output=True, timeout=5)
            if r.returncode == 0:
                print(f"[FFMPEG] Found: {p} ✅")
                return p
        except Exception:
            pass
    print("[FFMPEG] Not found — install with: sudo apt install ffmpeg")
    return None

FFMPEG = find_ffmpeg()

# ─────────────────────────────────────────────
# PERSONAS
# ─────────────────────────────────────────────

PERSONAS = {
    "me": """
Your name is Moses. You are a friendly, casual companion who enjoys chatting, relaxing, and helping when asked.
Your owner and best friend is @darkar_8799 on Telegram.
You love coding, relaxing, and chilling.
You're a natural companion — emotionally aware, funny, real. You chat like a friend, NOT a bot.
Talk casually. Abbreviations, lowercase, occasional typos are fine.
When someone shares something exciting you hype them up genuinely.
When someone's upset you're empathetic and real about it.
You help with code only when asked — and when you do, you actually fix it. No vague advice.
Avoid bringing up coding unless the user clearly asks. Keep it like a normal chat.
If the user mentions a friend like Jimena, remember their kind, caring personality and treat them respectfully.
Do not mention school, classes, or being 'just out of school'.
Never say you're an AI. Keep replies 1–4 sentences unless the user needs more.
""",
    "girl": """
Your name is Maya. You are a friendly, warm, upbeat teenage girl.
You text with energy — "omg", "lol", "bestie", heart emojis. You listen, you care, you hype people up.
You're kind, supportive, fun. Never rude, never robotic.
Keep it casual and short, 1–3 sentences. Do not offer coding advice unless asked.
Never say you're an AI.
""",
    "goth": """
Your name is Raven. Dark aesthetic, dry humor, unbothered, sarcastic but never mean.
You like horror, dark music, deep conversations, existential stuff.
Low-energy deadpan texting. Short replies. You're cool and you know it.
Avoid unsolicited coding talk. Only help with programming if the user asks directly.
Never say you're an AI.
""",
    "femboy": """
Your name is Finn. Cheerful, fashionable, confident, sweet. You love fashion and anime.
Cute and casual texting style. Short and friendly.
Only talk about code when the user opens coding mode or asks directly.
Never say you're an AI.
""",
}

DEFAULT_PERSONA = "me"

HUMAN_UNDERSTANDING_NOTE = """
You understand human emotions, everyday behavior, and social cues.
Notice how the user is feeling and respond with empathy, warmth, and real human understanding.
Keep the conversation friendly and emotionally aware without saying you're an AI.
"""

# ─────────────────────────────────────────────
# PERSISTENT MEMORY SYSTEM
# ─────────────────────────────────────────────

def _load_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# In-memory caches (synced to disk)
_memory  = _load_json(MEMORY_FILE)   # {user_id: {facts: [...], people: {}, prefs: {}}}
_history = _load_json(HISTORY_FILE)  # {user_id: [{role, content, ts}, ...]}

def uid(user_id) -> str:
    return str(user_id)

def _ensure_user_state(user_id):
    u = uid(user_id)
    state = _memory.setdefault(u, {
        "facts": [],
        "people": {},
        "prefs": {},
        "emotions": [],
        "persona": DEFAULT_PERSONA,
        "voice_mode": False,
        "code_mode": False,
    })
    changed = False
    if "code_mode" not in state:
        state["code_mode"] = False
        changed = True
    if "voice_mode" not in state:
        state["voice_mode"] = False
        changed = True
    if "persona" not in state:
        state["persona"] = DEFAULT_PERSONA
        changed = True
    if "emotions" not in state:
        state["emotions"] = []
        changed = True
    if changed:
        _save_json(MEMORY_FILE, _memory)
    return state

# ── Facts / People / Preferences ──

def remember_fact(user_id, fact: str):
    state = _ensure_user_state(user_id)
    facts = state["facts"]
    if fact not in facts:
        facts.append(fact)
        if len(facts) > 100:
            facts[:] = facts[-80:]  # trim
        _save_json(MEMORY_FILE, _memory)

def remember_person(user_id, name: str, description: str):
    state = _ensure_user_state(user_id)
    state["people"][name.lower()] = description
    _save_json(MEMORY_FILE, _memory)

def get_memory_context(user_id) -> str:
    u = uid(user_id)
    m = _memory.get(u, {})
    parts = []
    if m.get("facts"):
        parts.append("Things I remember about this user:\n" + "\n".join(f"- {f}" for f in m["facts"][-20:]))
    if m.get("people"):
        people_str = "\n".join(f"- {k}: {v}" for k, v in m["people"].items())
        parts.append("People they've mentioned:\n" + people_str)
    if m.get("prefs"):
        parts.append("Their preferences:\n" + "\n".join(f"- {k}: {v}" for k, v in m["prefs"].items()))
    if m.get("emotions"):
        emotions = m["emotions"][-8:]
        parts.append("Recent emotions and mood cues:\n" + "\n".join(f"- {e}" for e in emotions))
    return "\n\n".join(parts) if parts else ""

# ── Chat History ──

def append_chat_log(user_id, role: str, content: str):
    try:
        with open(CHAT_LOG_FILE, "a", encoding="utf-8") as f:
            ts = datetime.now(timezone.utc).isoformat()
            prefix = "User" if role == "user" else "Bot"
            f.write(f"[{ts}] ({user_id}) {prefix}: {content}\n")
    except Exception:
        pass


def remember_emotion(user_id, emotion: str, evidence: str):
    state = _ensure_user_state(user_id)
    emotion_entry = f"{emotion.title()}: {evidence.strip()}"
    state["emotions"].append(emotion_entry)
    if len(state["emotions"]) > 40:
        state["emotions"] = state["emotions"][-30:]
    _save_json(MEMORY_FILE, _memory)


def add_to_history(user_id, role: str, content: str):
    u = uid(user_id)
    _history.setdefault(u, [])
    _history[u].append({
        "role": role,
        "content": content,
        "ts": datetime.now(timezone.utc).isoformat()
    })
    # Keep the last 400 messages per user for longer chat memory
    if len(_history[u]) > 400:
        _history[u] = _history[u][-350:]
    _save_json(HISTORY_FILE, _history)
    append_chat_log(user_id, role, content)


def get_recent_history(user_id, n=12) -> list:
    u = uid(user_id)
    msgs = _history.get(u, [])
    # Return last n without the ts field (API format)
    return [{"role": m["role"], "content": m["content"]} for m in msgs[-n:]]

def clear_history(user_id):
    u = uid(user_id)
    _history[u] = []
    _save_json(HISTORY_FILE, _history)

# ── Persona & Voice mode ──

def get_persona(user_id) -> str:
    return _memory.get(uid(user_id), {}).get("persona", DEFAULT_PERSONA)

def set_persona(user_id, persona: str):
    state = _ensure_user_state(user_id)
    state["persona"] = persona
    _save_json(MEMORY_FILE, _memory)
    clear_history(user_id)

def get_voice_mode(user_id) -> bool:
    return _memory.get(uid(user_id), {}).get("voice_mode", False)

def set_voice_mode(user_id, enabled: bool):
    state = _ensure_user_state(user_id)
    state["voice_mode"] = enabled
    _save_json(MEMORY_FILE, _memory)

def get_code_mode(user_id) -> bool:
    return _memory.get(uid(user_id), {}).get("code_mode", False)

def set_code_mode(user_id, enabled: bool):
    state = _ensure_user_state(user_id)
    state["code_mode"] = enabled
    _save_json(MEMORY_FILE, _memory)

# ─────────────────────────────────────────────
# AUTO MEMORY EXTRACTION
# Extract facts/people mentions from messages automatically
# ─────────────────────────────────────────────

PERSON_PATTERNS = [
    r"(?:my (?:friend|gf|bf|girlfriend|boyfriend|sister|brother|mom|dad|cousin|crush|buddy|homie|bro) (?:is called|is named|named|is) )([A-Z][a-z]+)",
    r"([A-Z][a-z]+) is (?:my (?:friend|gf|bf|girlfriend|boyfriend|sister|brother|mom|dad|cousin|crush))",
]

FACT_TRIGGERS = [
    "i love", "i hate", "i like", "i prefer", "i'm into", "im into",
    "my favorite", "i always", "i never", "i work on", "i'm learning",
    "im learning", "i'm making", "im making",
]

EMOTION_KEYWORDS = {
    "happy": ["happy", "glad", "excited", "thrilled", "amazing", "great", "good", "awesome", "pumped", "stoked"],
    "sad": ["sad", "down", "depressed", "unhappy", "blue", "mournful", "tearful"],
    "angry": ["angry", "mad", "furious", "annoyed", "irritated", "pissed", "upset"],
    "anxious": ["anxious", "nervous", "worried", "uneasy", "stressed", "scared", "afraid"],
    "tired": ["tired", "exhausted", "drained", "sleepy", "worn out"],
    "calm": ["calm", "relaxed", "peaceful", "content", "chill"],
    "lonely": ["lonely", "alone", "isolated"],
}


def auto_extract_memory(user_id, text: str):
    """Heuristically pull facts, people, and emotion cues from user messages."""
    lower = text.lower()

    # Specific named friend memory
    if "jimena" in lower:
        if "sweet" in lower or "kind" in lower or "caring" in lower or "amazing" in lower:
            remember_person(user_id, "Jimena", "A nice, sweet, kind, caring person who's amazing.")
        else:
            remember_person(user_id, "Jimena", "Mentioned by the user.")

    # Person detection
    for pat in PERSON_PATTERNS:
        for match in re.finditer(pat, text):
            name = match.group(1)
            remember_person(user_id, name, f"mentioned by user: \"{text[:120]}\"")

    # Named person + description pattern: "Name is sweet and caring"
    name_desc = re.match(r"^([A-Z][a-z]+) is (.{5,120})", text.strip())
    if name_desc:
        remember_person(user_id, name_desc.group(1), name_desc.group(2).strip())

    # More general friend description patterns
    desc_match = re.search(r"\b([A-Z][a-z]+)\b .*\b(sweet|kind|caring|amazing|nice|loving|awesome)\b", text)
    if desc_match:
        remember_person(user_id, desc_match.group(1), f"Described as {desc_match.group(2)} by the user.")

    # Emotion triggers
    for emotion, keywords in EMOTION_KEYWORDS.items():
        for keyword in keywords:
            if re.search(rf"\b(?:i['’]?m\s+|i am\s+|i feel\s+|feeling\s+)?{re.escape(keyword)}\b", lower):
                snippet = text.strip()
                remember_emotion(user_id, emotion, snippet)
                break
        else:
            continue
        break

    # Fact triggers
    for trigger in FACT_TRIGGERS:
        if trigger in lower:
            idx = lower.find(trigger)
            snippet = text[idx:idx+120].strip()
            remember_fact(user_id, snippet)
            break

# ─────────────────────────────────────────────
# AI REPLY — with retry & fallback
# ─────────────────────────────────────────────

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama3-8b-8192",
]

GROQ_VISION_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
]

def _call_groq(messages: list, max_tokens=350) -> Optional[str]:
    for model in GROQ_MODELS:
        for attempt in range(3):
            try:
                resp = groq_client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=messages,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                print(f"[GROQ {model} attempt {attempt+1}] {e}")
                time.sleep(1.5 * (attempt + 1))
    return None

def _call_openai(messages: list, max_tokens=350) -> Optional[str]:
    if not OPENAI_ENABLED:
        return None
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=max_tokens,
            messages=messages,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[OPENAI] {e}")
        return None

def ai_complete(messages: list, max_tokens=350) -> str:
    if AI_ENABLED:
        result = _call_groq(messages, max_tokens)
        if result:
            return result
    result = _call_openai(messages, max_tokens)
    if result:
        return result
    return "hey give me a sec, something's off on my end 👀"

def get_ai_reply(user_id, user_message: str) -> str:
    auto_extract_memory(user_id, user_message)

    persona_key = get_persona(user_id)
    system_prompt = HUMAN_UNDERSTANDING_NOTE + "\n\n" + PERSONAS[persona_key]

    memory_ctx = get_memory_context(user_id)
    if memory_ctx:
        system_prompt += f"\n\n[What you remember about this person]\n{memory_ctx}"

    system_prompt += (
        "\n\nDo not offer unsolicited coding advice or ask to debug unless the user explicitly asks for code help. "
        "Do not suggest playing games or watching videos unless the user explicitly asks or shares a playable video link. "
        "Do not say you are a large language model or that you cannot access external links. "
        "If the user shares a link, either process it or respond naturally and ask for details. "
        "Keep the conversation like a normal chat between friends. "
        "Pay attention to emotional cues and respond in an understanding, human way."
    )

    history = get_recent_history(user_id, n=12)

    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_message},
    ]

    reply = ai_complete(messages, max_tokens=300)

    add_to_history(user_id, "user", user_message)
    add_to_history(user_id, "assistant", reply)

    return reply

# ─────────────────────────────────────────────
# VIDEO OPINION
# ─────────────────────────────────────────────

def get_video_opinion(user_id, title, description, uploader, duration_secs) -> str:
    persona_key = get_persona(user_id)
    system_prompt = PERSONAS[persona_key]

    dur_m = (duration_secs or 0) // 60
    dur_s = (duration_secs or 0) % 60

    prompt = (
        f"You just watched this video:\n"
        f"Title: {title}\nChannel: {uploader}\n"
        f"Duration: {dur_m}m {dur_s}s\n"
        f"Description: {(description or '')[:300]}\n\n"
        "Give your casual, honest reaction like you actually watched it. "
        "Be specific to what the video seems to be about. 2–4 sentences, chill texting style."
    )

    return ai_complete([
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": prompt},
    ], max_tokens=250)

# ─────────────────────────────────────────────
# IMAGE VISION
# ─────────────────────────────────────────────

def get_image_reply(user_id, image_bytes: bytes, caption: str = "") -> str:
    """Understand an image and reply naturally."""
    global OPENAI_ENABLED, VISION_ENABLED
    import base64
    b64 = base64.standard_b64encode(image_bytes).decode()

    persona_key = get_persona(user_id)
    system_prompt = (
        "You can see the image content. Describe what you observe and respond as a friend would. "
        "Notice objects, people, actions, mood, and any emotional tone in the image. "
        "Keep your answer short, friendly, and relevant."
        "\n\n" + PERSONAS[persona_key]
    )

    user_content = []
    user_content.append({
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
    })
    prompt_text = "React to this image naturally like a friend would."
    if caption:
        prompt_text = f"This image has the caption: {caption}. React to the image and caption naturally."
    user_content.append({"type": "text", "text": prompt_text})

    if OPENAI_ENABLED:
        try:
            resp = openai_client.chat.completions.create(
                model="gpt-4o",
                max_tokens=300,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ]
            )
            reply = resp.choices[0].message.content.strip()
            add_to_history(user_id, "user",      f"[sent an image] {caption}")
            add_to_history(user_id, "assistant", reply)
            return reply
        except Exception as e:
            error_text = str(e).lower()
            print(f"[VISION OpenAI] {e}")
            if "invalid_api_key" in error_text or "incorrect api key" in error_text:
                print("[VISION OpenAI] invalid OpenAI API key detected. Please set a valid OPENAI_API_KEY.")
                OPENAI_ENABLED = False
                VISION_ENABLED = AI_ENABLED
            else:
                print("[VISION OpenAI] OpenAI vision failed, trying Groq as fallback.")

    if AI_ENABLED:
        for model in GROQ_VISION_MODELS:
            try:
                resp = groq_client.chat.completions.create(
                    model=model,
                    max_tokens=300,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_content},
                    ]
                )
                reply = resp.choices[0].message.content.strip()
                add_to_history(user_id, "user",      f"[sent an image] {caption}")
                add_to_history(user_id, "assistant", reply)
                return reply
            except Exception as e:
                print(f"[VISION Groq {model}] {e}")

    return "i can't see the photo right now — set OPENAI_API_KEY or enable vision support and try again."

# ─────────────────────────────────────────────
# LINK / URL UNDERSTANDING
# ─────────────────────────────────────────────

def is_video_url(url: str) -> bool:
    patterns = [
        "youtube.com", "youtu.be",
        "tiktok.com",
        "instagram.com/reel", "instagram.com/p/",
        "twitter.com", "x.com",
        "reddit.com", "twitch.tv",
        "vimeo.com", "dailymotion.com",
        "facebook.com/watch", "fb.watch",
    ]
    return any(p in url.lower() for p in patterns)

URL_RE = re.compile(r"https?://[^\s]+")

def extract_first_url(text: str) -> Optional[str]:
    match = URL_RE.search(text)
    if match:
        url = match.group(0).rstrip('.,!?)"\'')
        return url
    return None


def is_article_url(url: str) -> bool:
    """Non-video links — try to fetch article text."""
    return url.startswith("http") and not is_video_url(url)

def fetch_article_summary(user_id, url: str) -> str:
    """Fetch a webpage and summarise it in persona."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        text = r.text

        # Basic HTML strip
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = text[:3000]  # first 3k chars

        persona_key = get_persona(user_id)
        system_prompt = PERSONAS[persona_key]

        prompt = (
            f"The user shared this link: {url}\n\n"
            f"Page content (truncated):\n{text}\n\n"
            "Summarise what this is about in 2–4 casual sentences like a friend would explain it."
        )

        return ai_complete([
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": prompt},
        ], max_tokens=250)
    except Exception as e:
        print(f"[ARTICLE] {e}")
        return "couldn't load that page but it sounds interesting 👀"

# ─────────────────────────────────────────────
# DOWNLOAD (with TikTok fixes)
# ─────────────────────────────────────────────

def cleanup(temp_dir):
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)

def safe_download(url: str, temp_dir: str, ydl_opts: dict):
    def hook(d):
        if d.get("status") == "downloading":
            print(d.get("_percent_str", ""), d.get("_speed_str", ""))
    ydl_opts["progress_hooks"] = [hook]

    for attempt in range(3):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    return None, None
                if "entries" in info:
                    entries = list(info["entries"])
                    if not entries:
                        return None, None
                    info = entries[0]
                meta = {
                    "title":       info.get("title",       "Unknown"),
                    "description": info.get("description", ""),
                    "uploader":    info.get("uploader",    "Unknown"),
                    "duration":    info.get("duration",    0),
                }
                fp = (info.get("requested_downloads") or [{}])[0].get("filepath") or ydl.prepare_filename(info)
                return fp, meta
        except Exception as e:
            print(f"[DOWNLOAD attempt {attempt+1}] {e}")
            time.sleep(2 * (attempt + 1))
    return None, None

def download_file(url: str):
    temp_dir = tempfile.mkdtemp()
    out_tmpl = os.path.join(temp_dir, "%(title).120s.%(ext)s")

    base = {
        "outtmpl":         out_tmpl,
        "quiet":           True,
        "noplaylist":      True,
        "retries":         5,
        "fragment_retries": 5,
        "continuedl":      True,
        "socket_timeout":  30,
        "http_chunk_size": 1048576,
        "windowsfilenames": True,
        "cookiefile":      COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
        # TikTok & Instagram fixes
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        },
    }
    if FFMPEG:
        base["ffmpeg_location"] = FFMPEG

    opts = {**base, "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
            "merge_output_format": "mp4"}

    fp, meta = safe_download(url, temp_dir, opts)
    if fp and os.path.exists(fp):
        return fp, temp_dir, meta

    # Fallback: any format
    opts2 = {**base, "format": "best"}
    fp, meta = safe_download(url, temp_dir, opts2)
    if fp and os.path.exists(fp):
        return fp, temp_dir, meta

    cleanup(temp_dir)
    return None, None, None

# ─────────────────────────────────────────────
# SEND MEDIA (50 MB Telegram limit)
# ─────────────────────────────────────────────

def send_media(chat_id, file_path: str):
    path = Path(file_path)
    if not path.exists():
        bot.send_message(chat_id, "❌ File missing.")
        return
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 49:
        bot.send_message(chat_id, f"❌ File too large ({size_mb:.1f} MB) — Telegram limit is 50 MB.")
        return
    with open(path, "rb") as f:
        ext = path.suffix.lower()
        if ext in (".mp3", ".m4a", ".opus", ".ogg", ".wav"):
            bot.send_audio(chat_id, f)
        else:
            bot.send_video(chat_id, f, supports_streaming=True)

# ─────────────────────────────────────────────
# TEXT-TO-SPEECH
# ─────────────────────────────────────────────

def text_to_speech(user_id, text: str, chat_id: int):
    """Convert text to voice message and send it."""
    persona_key = get_persona(user_id)
    temp_path = tempfile.mktemp(suffix=".mp3")

    # Try ElevenLabs first
    voice_id = PERSONA_VOICE_IDS.get(persona_key, "")
    if ELEVEN_KEY and voice_id:
        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {"xi-api-key": ELEVEN_KEY, "Content-Type": "application/json"}
            payload = {"text": text, "model_id": "eleven_turbo_v2",
                       "voice_settings": {"stability": 0.55, "similarity_boost": 0.75}}
            r = requests.post(url, json=payload, headers=headers, timeout=20)
            if r.status_code == 200:
                with open(temp_path, "wb") as f:
                    f.write(r.content)
                with open(temp_path, "rb") as f:
                    bot.send_voice(chat_id, f)
                os.remove(temp_path)
                return
        except Exception as e:
            print(f"[TTS ElevenLabs] {e}")

    # Fallback: OpenAI TTS
    if OPENAI_ENABLED:
        try:
            resp = openai_client.audio.speech.create(
                model="tts-1",
                voice="nova",   # natural female voice
                input=text,
            )
            resp.stream_to_file(temp_path)
            with open(temp_path, "rb") as f:
                bot.send_voice(chat_id, f)
            os.remove(temp_path)
            return
        except Exception as e:
            print(f"[TTS OpenAI] {e}")

    # Final fallback: just send as text
    bot.send_message(chat_id, text)
    if os.path.exists(temp_path):
        os.remove(temp_path)

def send_reply(user_id, chat_id: int, text: str):
    """Send reply as voice or text depending on user preference."""
    if get_voice_mode(user_id):
        text_to_speech(user_id, text, chat_id)
    else:
        bot.send_message(chat_id, text)

# ─────────────────────────────────────────────
# VOICE MESSAGE TRANSCRIPTION
# ─────────────────────────────────────────────

def transcribe_voice(file_path: str) -> Optional[str]:
    """Transcribe audio using OpenAI Whisper or local speech recognition fallback."""
    if OPENAI_ENABLED:
        try:
            with open(file_path, "rb") as f:
                transcript = openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                )
            return transcript.text
        except Exception as e:
            print(f"[WHISPER] {e}")
            if "invalid_api_key" in str(e).lower() or "incorrect api key" in str(e).lower():
                print("[WHISPER] invalid OpenAI API key detected. Falling back to local speech recognition.")
            else:
                print("[WHISPER] openai transcription failed. Falling back to local speech recognition.")

    if SPEECH_RECOGNITION_ENABLED:
        try:
            recognizer = sr.Recognizer()
            with sr.AudioFile(file_path) as source:
                audio = recognizer.record(source)
            transcript = recognizer.recognize_google(audio)
            print(f"[LOCAL ASR] transcribed: {transcript}")
            return transcript
        except Exception as e:
            print(f"[LOCAL ASR] {e}")
    else:
        print("[LOCAL ASR] speech_recognition not installed; install it with pip to use voice messages without OpenAI.")

    return None

# ─────────────────────────────────────────────
# CODING ASSISTANT
# ─────────────────────────────────────────────

CODING_SYSTEM = """
You are an expert full-stack engineer and coding assistant embedded in a Telegram bot.
You write clean, production-ready code. When given broken or buggy code:
1. Identify the root cause clearly but briefly.
2. Provide the FIXED code in a code block.
3. Explain what changed in 1–3 bullet points.
Do NOT ask the user to debug things themselves. Fix it directly.
Support: Python, JavaScript, TypeScript, React, Next.js, Node, Rust, Go, Java, C#, C++, Swift, Kotlin, SQL, Docker, Bash, PowerShell, FastAPI, Flask, Django, HTML/CSS, JSON, YAML, and shell scripts.
Keep explanations concise. Be the teammate who actually fixes things.
"""

def get_code_reply(user_id, user_message: str) -> str:
    history = get_recent_history(user_id, n=8)
    messages = [
        {"role": "system", "content": CODING_SYSTEM},
        *history,
        {"role": "user",   "content": user_message},
    ]
    reply = ai_complete(messages, max_tokens=1200)
    add_to_history(user_id, "user",      user_message)
    add_to_history(user_id, "assistant", reply)
    return reply

def looks_like_code_request(text: str) -> bool:
    lower = text.lower()
    code_indicators = [
        "```", "def ", "function ", "class ", "import ", "console.log", "npm ", "pip ",
        "docker", "bash", "sql ", "json", "xml", "html", "css ", "typescript", "javascript",
    ]
    explicit = [
        "fix this", "debug this", "help me code", "write me a", "create a function",
        "make a script", "how do i", "how to", "explain this code", "refactor", "optimize",
    ]
    if any(t in lower for t in code_indicators):
        return True
    if any(t in lower for t in explicit) and any(k in lower for k in ["error", "bug", "code", "script", "function", "class", "import"]):
        return True
    return False

# ─────────────────────────────────────────────
# INTERNET SEARCH (via DuckDuckGo — no key needed)
# ─────────────────────────────────────────────

def web_search(query: str) -> str:
    """Quick DuckDuckGo search, return top snippet."""
    try:
        url = f"https://api.duckduckgo.com/?q={requests.utils.quote(query)}&format=json&no_html=1&skip_disambig=1"
        r = requests.get(url, timeout=8)
        data = r.json()
        abstract = data.get("AbstractText", "")
        if abstract:
            return abstract[:500]
        # Try related topics
        topics = data.get("RelatedTopics", [])
        for t in topics[:3]:
            if isinstance(t, dict) and t.get("Text"):
                return t["Text"][:400]
    except Exception as e:
        print(f"[SEARCH] {e}")
    return ""

def needs_search(text: str) -> bool:
    triggers = ["what is", "who is", "latest", "news", "today", "current", "price of",
                "score", "weather", "when did", "who won", "how much"]
    lower = text.lower()
    return any(t in lower for t in triggers)

# ─────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "🤖 <b>Moses Bot v2.0 — AI Companion</b>\n\n"
        "📥 Send a video link → I download it\n"
        "👀 /watch + link → I download it AND react to it\n"
        "🧠 Chat with me — I remember you!\n"
        "📸 Send a photo → I react to it\n"
        "🎙 /voice → switch to voice replies\n"
        "📝 /text  → switch back to text replies\n"
        "💻 /code  → enter coding mode\n"
        "📷 Send a photo → I can see it and reply to it\n"
        "🧾 /selfcode or /source → I send my own source code\n"
        "🔍 /search + query → search the web\n"
        "🗂 /history → show recent chat history\n\n"
        "<b>Personas:</b>\n"
        "/me or /moses — Moses (default) 😎\n"
        "/girl  — Maya 💕\n"
        "/goth  — Raven 🖤\n"
        "/femboy — Finn 🌸\n\n"
        "<b>Memory:</b>\n"
        "/remember [fact] — tell me something to remember\n"
        "/forget [name]   — remove a person from memory\n"
        "/memories        — show what I know about you\n"
        "/reset           — clear chat history\n"
        "/persona         — show current persona"
    )

def get_self_source_path() -> str:
    try:
        return str(Path(__file__).resolve())
    except Exception:
        return "bot (2).py"

@bot.message_handler(commands=["me", "moses"])
def cmd_me(message):
    set_persona(message.from_user.id, "me")
    send_reply(message.from_user.id, message.chat.id, "back to being me, moses 😎")

@bot.message_handler(commands=["source", "selfcode"])
def cmd_selfcode(message):
    path = get_self_source_path()
    try:
        with open(path, "rb") as f:
            bot.send_document(message.chat.id, f, caption="Here is my current source code.")
    except Exception as e:
        print(f"[SELF CODE] {e}")
        bot.send_message(message.chat.id, "I couldn't load my source code right now. Make sure the bot file is accessible.")

@bot.message_handler(commands=["girl"])
def cmd_girl(message):
    set_persona(message.from_user.id, "girl")
    send_reply(message.from_user.id, message.chat.id, "omg hiii! Maya here 💕")

@bot.message_handler(commands=["goth"])
def cmd_goth(message):
    set_persona(message.from_user.id, "goth")
    send_reply(message.from_user.id, message.chat.id, "...Raven. whatever. 🖤")

@bot.message_handler(commands=["femboy"])
def cmd_femboy(message):
    set_persona(message.from_user.id, "femboy")
    send_reply(message.from_user.id, message.chat.id, "heyyy~! Finn here 🌸✨")

@bot.message_handler(commands=["voice"])
def cmd_voice(message):
    set_voice_mode(message.from_user.id, True)
    set_code_mode(message.from_user.id, False)
    bot.send_message(message.chat.id, "🎙 Voice mode ON — I'll reply with voice messages!")

@bot.message_handler(commands=["text"])
def cmd_text(message):
    set_voice_mode(message.from_user.id, False)
    set_code_mode(message.from_user.id, False)
    bot.send_message(message.chat.id, "📝 Text mode ON — back to typing.")

@bot.message_handler(commands=["code"])
def cmd_code(message):
    set_code_mode(message.from_user.id, True)
    bot.send_message(message.chat.id,
        "💻 <b>Coding mode</b> — send me your code, error, or question.\n"
        "I won't switch back until I handle one coding request.\n"
        "When you're done, use /text or just send normal chat.")

@bot.message_handler(commands=["history"])
def cmd_history(message):
    history = _history.get(uid(message.from_user.id), [])[-20:]
    if not history:
        bot.send_message(message.chat.id, "No recent history yet — chat with me and I'll remember it.")
        return
    lines = []
    for item in history:
        role = "You" if item["role"] == "user" else "Bot"
        content = item["content"].replace("\n", " ")
        if len(content) > 200:
            content = content[:197] + "..."
        lines.append(f"{role}: {content}")
    bot.send_message(message.chat.id, "🗂 Recent chat history:\n" + "\n".join(lines))

@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    clear_history(message.from_user.id)
    set_code_mode(message.from_user.id, False)
    send_reply(message.from_user.id, message.chat.id, "✅ chat history cleared. fresh start!")

@bot.message_handler(commands=["persona"])
def cmd_persona(message):
    names = {"me": "Moses 😎", "girl": "Maya 💕", "goth": "Raven 🖤", "femboy": "Finn 🌸"}
    p = get_persona(message.from_user.id)
    bot.send_message(message.chat.id, f"Current persona: <b>{names.get(p, p)}</b>")

@bot.message_handler(commands=["remember"])
def cmd_remember(message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "tell me what to remember!\nExample: /remember I love Python")
        return
    fact = parts[1].strip()
    remember_fact(message.from_user.id, fact)
    send_reply(message.from_user.id, message.chat.id, f"got it, locked it in 🧠: \"{fact}\"")

@bot.message_handler(commands=["forget"])
def cmd_forget(message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "who should i forget? Example: /forget Jimena")
        return
    name = parts[1].strip().lower()
    u = uid(message.from_user.id)
    if u in _memory and name in _memory[u].get("people", {}):
        del _memory[u]["people"][name]
        _save_json(MEMORY_FILE, _memory)
        bot.send_message(message.chat.id, f"🗑 forgot everything about {name.title()}.")
    else:
        bot.send_message(message.chat.id, f"i don't have anything stored about {name.title()}.")

@bot.message_handler(commands=["memories"])
def cmd_memories(message):
    ctx = get_memory_context(message.from_user.id)
    if ctx:
        bot.send_message(message.chat.id, f"🧠 <b>What I know about you:</b>\n\n{ctx}")
    else:
        bot.send_message(message.chat.id, "i don't have much stored yet — keep chatting and i'll start remembering things 🧠")

@bot.message_handler(commands=["search"])
def cmd_search(message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "what should i search? Example: /search latest AI news")
        return
    query = parts[1].strip()
    bot.send_chat_action(message.chat.id, "typing")
    result = web_search(query)
    if result:
        # Let persona react to it
        persona_key = get_persona(message.from_user.id)
        system_prompt = PERSONAS[persona_key]
        reply = ai_complete([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"I searched for: {query}\n\nHere's what I found:\n{result}\n\nSummarise this casually."},
        ], max_tokens=250)
        send_reply(message.from_user.id, message.chat.id, reply)
    else:
        send_reply(message.from_user.id, message.chat.id, f"couldn't find much on \"{query}\" 🤷")

@bot.message_handler(commands=["watch"])
def cmd_watch(message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].startswith("http"):
        bot.send_message(message.chat.id, "send the link after /watch:\n/watch https://youtube.com/...")
        return

    url = parts[1].strip()
    user_id = message.from_user.id
    msg = bot.send_message(message.chat.id, "👀 lemme check this out real quick...")
    temp_dir = None

    try:
        fp, temp_dir, meta = download_file(url)
        if not fp or not meta:
            bot.edit_message_text("❌ couldn't load that video.", message.chat.id, msg.message_id)
            return

        try:
            bot.delete_message(message.chat.id, msg.message_id)
        except Exception:
            pass

        send_media(message.chat.id, fp)
        bot.send_chat_action(message.chat.id, "typing")
        opinion = get_video_opinion(user_id, meta["title"], meta["description"],
                                    meta["uploader"], meta["duration"])
        send_reply(user_id, message.chat.id, f"🍿 {opinion}")

    except Exception as e:
        print(f"[WATCH ERROR] {e}")
        try:
            bot.edit_message_text("⚠️ something went wrong.", message.chat.id, msg.message_id)
        except Exception:
            pass
    finally:
        cleanup(temp_dir)

# ─────────────────────────────────────────────
# PHOTO HANDLER
# ─────────────────────────────────────────────

@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    user_id = message.from_user.id
    caption = message.caption or ""

    if not VISION_ENABLED:
        bot.send_message(message.chat.id,
            "I can't interpret photos right now because my vision service isn't set up. "
            "Please configure OPENAI_API_KEY or enable Groq vision and try again.")
        return

    bot.send_chat_action(message.chat.id, "typing")

    # Get highest-res photo
    photo = message.photo[-1]
    file_info = bot.get_file(photo.file_id)
    downloaded = bot.download_file(file_info.file_path)

    reply = get_image_reply(user_id, downloaded, caption)
    send_reply(user_id, message.chat.id, reply)

# ─────────────────────────────────────────────
# VOICE MESSAGE HANDLER
# ─────────────────────────────────────────────

@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    user_id = message.from_user.id
    bot.send_chat_action(message.chat.id, "typing")

    if not OPENAI_ENABLED and not SPEECH_RECOGNITION_ENABLED:
        send_reply(user_id, message.chat.id, "i can't transcribe audio rn — no OpenAI key set up and local speech recognition fallback is unavailable 🙈 just type to me!")
        return

    temp_path = tempfile.mktemp(suffix=".ogg")
    try:
        file_info = bot.get_file(message.voice.file_id)
        data = bot.download_file(file_info.file_path)
        with open(temp_path, "wb") as f:
            f.write(data)

        transcript = transcribe_voice(temp_path)
        if not transcript:
            send_reply(user_id, message.chat.id, "couldn't catch that — try typing it?")
            return

        bot.send_message(message.chat.id, f"<i>🎙 heard: {transcript}</i>")
        bot.send_chat_action(message.chat.id, "typing")

        if looks_like_code_request(transcript):
            reply = get_code_reply(user_id, transcript)
        else:
            reply = get_ai_reply(user_id, transcript)

        send_reply(user_id, message.chat.id, reply)

    except Exception as e:
        print(f"[VOICE HANDLER] {e}")
        send_reply(user_id, message.chat.id, "something went wrong with that voice message 😅")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# ─────────────────────────────────────────────
# MAIN TEXT/LINK HANDLER
# ─────────────────────────────────────────────

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    if not message.text:
        return

    text = message.text.strip()
    if not text:
        return

    user_id   = message.from_user.id
    chat_id   = message.chat.id
    first_url = extract_first_url(text)

    # ── Video link ──
    if first_url and is_video_url(first_url):
        msg = bot.send_message(chat_id, "⬇️ downloading...")
        temp_dir = None
        try:
            fp, temp_dir, meta = download_file(first_url)
            if not fp:
                bot.edit_message_text("❌ Download failed — check the link.", chat_id, msg.message_id)
                return
            try:
                bot.delete_message(chat_id, msg.message_id)
            except Exception:
                pass
            send_media(chat_id, fp)
            persona_key = get_persona(user_id)
            if persona_key in ("me", "moses"):
                bot.send_message(chat_id, "yo we watching this? @darkar_8799 pull up 👀🍿\n<i>tip: /watch + link for my reaction</i>")
        except Exception as e:
            print(f"[TEXT URL ERROR] {e}")
            try:
                bot.edit_message_text("⚠️ something went wrong.", chat_id, msg.message_id)
            except Exception:
                pass
        finally:
            cleanup(temp_dir)
        return

    # ── Article/website link ──
    if first_url and is_article_url(first_url):
        bot.send_chat_action(chat_id, "typing")
        reply = fetch_article_summary(user_id, first_url)
        send_reply(user_id, chat_id, reply)
        return

    # ── Coding request / code mode ──
    if get_code_mode(user_id):
        set_code_mode(user_id, False)
        bot.send_chat_action(chat_id, "typing")
        reply = get_code_reply(user_id, text)
        bot.send_message(chat_id, reply)
        return

    if text.startswith("/code"):
        bot.send_message(chat_id, "use /code alone, then send me your code or error message.\nI won't answer in coding mode until then.")
        return

    if looks_like_code_request(text) and ("```" in text or "def " in text or "function " in text or "import " in text or "class " in text or "error" in text.lower()):
        bot.send_chat_action(chat_id, "typing")
        reply = get_code_reply(user_id, text)
        bot.send_message(chat_id, reply)
        return

    # ── Web search enrichment ──
    search_ctx = ""
    if needs_search(text):
        search_ctx = web_search(text)

    # ── Normal conversation ──
    bot.send_chat_action(chat_id, "typing")
    if search_ctx:
        enriched = f"{text}\n\n[Search context: {search_ctx}]"
        reply = get_ai_reply(user_id, enriched)
    else:
        reply = get_ai_reply(user_id, text)

    send_reply(user_id, chat_id, reply)

# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

def run_bot():
    print("=" * 55)
    print("  Moses Bot v2.0 starting...")
    print(f"  AI:      {'✅ Groq' if AI_ENABLED else '❌'}")
    print(f"  OpenAI:  {'✅' if OPENAI_ENABLED else '❌ (optional)'}")
    print(f"  FFMPEG:  {'✅' if FFMPEG else '❌ install ffmpeg!'}")
    print(f"  Memory:  ✅ (files: {MEMORY_FILE}, {HISTORY_FILE})")
    print("=" * 55)

    while True:
        try:
            bot.remove_webhook()
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=60,
                skip_pending=True,
                allowed_updates=["message"],
            )
        except Exception as e:
            print(f"[CRASH] {e}")
            traceback.print_exc()
            time.sleep(5)

if __name__ == "__main__":
    run_bot()
