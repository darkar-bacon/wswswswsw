import os
import telebot
from groq import Groq
import requests
from PIL import Image
from io import BytesIO
import speech_recognition as sr
from pydub import AudioSegment
import json

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

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = """
    Welcome to Moses Bot! 🤖
    
    I can help you with:
    • Text conversations (powered by Groq)
    • Image analysis
    • Voice messages
    
    Commands:
    /start - Show this message
    /clear - Clear conversation history
    /help - Get help
    
    Just send me a message, image, or voice note!
    """
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['clear'])
def clear_history(message):
    user_id = message.from_user.id
    if user_id in user_conversations:
        user_conversations[user_id] = []
    bot.reply_to(message, "Conversation history cleared! 🧹")

@bot.message_handler(commands=['help'])
def send_help(message):
    help_text = """
    📚 Help Guide:
    
    Text: Send any message for AI conversation
    Image: Send an image for analysis
    Voice: Send a voice message for transcription + response
    
    /clear - Reset conversation
    /start - Show welcome message
    """
    bot.reply_to(message, help_text)

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
