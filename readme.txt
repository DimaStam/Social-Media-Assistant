---------------------------------------------------
Bot is developing
---------------------------------------------------

# Telegram Bot – Coffee Shop Social Media Assistant

This bot helps generate **ready-to-use social media posts** for a coffee shop.  
Simply send a **photo of a drink or dessert** to the bot, and it will return engaging captions for Instagram and Facebook.

---

## 📌 Features
- 🖼️ Accepts photo uploads in Telegram  
- 🤖 Uses OpenAI to analyze the image and generate captions  
- ✍️ Creates post-ready text:
  - Instagram: description + hashtags + emojis  
  - Facebook: description + CTA (without hashtags)  
- 🏷️ Adds hashtags, captions, and alt-text  
- ☁️ Uploads photos to AWS S3 for AI processing  

---

## ⚙️ Requirements
- Python 3.9+
- Libraries: `python-telegram-bot`, `python-dotenv`, `openai`, `boto3`, `pytz`

