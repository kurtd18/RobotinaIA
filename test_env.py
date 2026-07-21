from dotenv import load_dotenv
import os

load_dotenv()

print("OPENAI_API_KEY:", os.getenv("OPENAI_API_KEY"))
print("TELEGRAM_BOT_TOKEN:", os.getenv("TELEGRAM_BOT_TOKEN"))
print("TELEGRAM_CHAT_ID:", os.getenv("TELEGRAM_CHAT_ID"))