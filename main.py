import os
import telebot
from groq import Groq
import requests
from PIL import Image
from io import BytesIO
import speech_recognition as sr
from pydub import AudioSegment
import json
import subprocess
import sys
from pathlib import Path
import tempfile

# Use environment variables - NO hardcoded keys
TOKEN = os.getenv("token")
GROQ_API_KEY = os.getenv("api")

if not TOKEN or not GROQ_API_KEY:
    raise ValueError("Missing TOKEN or GROQ_API_KEY environment variables")

bot = telebot.TeleBot(TOKEN)
client = Groq(api_key=GROQ_API_KEY)

# Store conversation history per user
user_conversations = {}

def get_user_conversation(user_id):
    if user_id not in user_conversations:
        user_conversations[user_id] = []
    return user_conversations[user_id]

def download_video(url: str, output_dir: str, audio_only: bool = False, cookiefile: str = None):
    """Download video/audio from YouTube, TikTok, Instagram, etc."""
    output_path = os.path.join(output_dir, "%(title).120s.%(ext)s")
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-o",
        output_path,
        "--no-playlist",
        "--merge-output-format",
        "mp4",
        url,
    ]
    if audio_only:
        cmd.extend(["-x", "--audio-format", "mp3"])
    if cookiefile:
        cmd.extend(["--cookies", cookiefile])
    cmd.extend([
        "--user-agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--geo-bypass",
        "--no-check-certificate",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        "--socket-timeout",
        "30",
    ])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Download failed: {result.stderr}")
    
    # Find the downloaded file
    files = list(Path(output_dir).glob("*"))
    if files:
        return str(files[0])
    return None

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = """Welcome to Moses Bot! 🤖

I can help you with:
• Text conversations (powered by Groq)
• Image analysis
• Voice messages
• Video downloads (YouTube, TikTok, Instagram)

Commands:
/start - Show this message
/clear - Clear conversation history
/help - Get help
/download <url> - Download video
/downloadaudio <url> - Download audio only (MP3)

Just send me a message, image, or voice note!"""
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['clear'])
def clear_history(message):
    user_id = message.from_user.id
    if user_id in user_conversations:
        user_conversations[user_id] = []
    bot.reply_to(message, "Conversation history cleared! 🧹")

@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """📚 Help Guide:

Text: Send any message for AI conversation
Image: Send an image for analysis
Voice: Send a voice message for transcription + response

Downloads:
/download <url> - Download video from YouTube, TikTok, Instagram
/downloadaudio <url> - Download audio only (MP3)

/clear - Reset conversation
/start - Show welcome message"""
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['download'])
def handle_download(message):
    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            bot.reply_to(message, "Usage: /download <url>")
            return
        
        url = args[1]
        bot.reply_to(message, "⏳ Downloading video... This may take a while.")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = download_video(url, temp_dir, audio_only=False)
            if file_path and os.path.exists(file_path):
                with open(file_path, 'rb') as video_file:
                    bot.send_document(message.chat.id, video_file, caption="✅ Download complete!")
            else:
                bot.reply_to(message, "❌ Download failed or file not found")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['downloadaudio'])
def handle_download_audio(message):
    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            bot.reply_to(message, "Usage: /downloadaudio <url>")
            return
        
        url = args[1]
        bot.reply_to(message, "⏳ Downloading audio... This may take a while.")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = download_video(url, temp_dir, audio_only=True)
            if file_path and os.path.exists(file_path):
                with open(file_path, 'rb') as audio_file:
                    bot.send_document(message.chat.id, audio_file, caption="✅ Audio download complete!")
            else:
                bot.reply_to(message, "❌ Download failed or file not found")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    user_id = message.from_user.id
    user_message = message.text
    
    conversation = get_user_conversation(user_id)
    conversation.append({"role": "user", "content": user_message})
    
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=conversation,
            max_tokens=1024,
        )
        
        assistant_message = response.choices[0].message.content
        conversation.append({"role": "assistant", "content": assistant_message})
        
        bot.reply_to(message, assistant_message)
    except Exception as e:
        bot.reply_to(message, f"Error: {str(e)}")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        image = Image.open(BytesIO(downloaded_file))
        
        user_id = message.from_user.id
        conversation = get_user_conversation(user_id)
        
        user_message = message.caption or "Analyze this image"
        conversation.append({"role": "user", "content": user_message})
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=conversation,
            max_tokens=1024,
        )
        
        assistant_message = response.choices[0].message.content
        conversation.append({"role": "assistant", "content": assistant_message})
        
        bot.reply_to(message, assistant_message)
    except Exception as e:
        bot.reply_to(message, f"Error processing image: {str(e)}")

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Convert to WAV for speech recognition
        audio = AudioSegment.from_file(BytesIO(downloaded_file), format="ogg")
        wav_data = BytesIO()
        audio.export(wav_data, format="wav")
        wav_data.seek(0)
        
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_data) as source:
            audio_data = recognizer.record(source)
        
        text = recognizer.recognize_google(audio_data)
        
        user_id = message.from_user.id
        conversation = get_user_conversation(user_id)
        conversation.append({"role": "user", "content": text})
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=conversation,
            max_tokens=1024,
        )
        
        assistant_message = response.choices[0].message.content
        conversation.append({"role": "assistant", "content": assistant_message})
        
        bot.reply_to(message, f"You said: {text}\n\n{assistant_message}")
    except Exception as e:
        bot.reply_to(message, f"Error processing voice: {str(e)}")

if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling()
