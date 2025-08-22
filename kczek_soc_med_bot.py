import os
import pytz
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv
import boto3

load_dotenv()

# === Konfiguracja ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_KEY")
CITY_TAG = os.getenv("CITY_TAG", "#kawiarnia")
TZ = os.getenv("TZ", "Europe/Warsaw")
ZONE = pytz.timezone(TZ)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# === Funkcje AI ===
async def generate_ai_content(image_path: str, note: str = None):
    prompt_image = f"""
Jesteś specjalistą social media dla kawiarni.
Twoje zadanie:
1. Zidentyfikuj co jest na zdjęciu (np. cappuccino, latte, ciasto).
2. Napisz apetyczny opis produktu (55–80 słów), w języku polskim, ton: ciepły, sensoryczny, zachęcający.
3. Dodaj krótkie CTA na końcu (np. "Wpadaj dziś do 18:00!").
4. Dodaj 5–8 hashtagów (PL/EN, bez znaków diakrytycznych). Najpierw lokalne (#kawa #kawiarnia #Wrocław), potem produktowe.
5. Dodaj ALT-text (max 120 znaków, prosty opis zdjęcia).
6. Zbuduj finalne posty:
   - Instagram: opis + linia oddzielająca + hashtagi. Użyj 1–3 emoji.
   - Facebook: pełne zdanie z caption + CTA (bez hashtagów).

Wynik zwróć **w czystym JSON** w strukturze:
{{
  "caption": "...",
  "hashtags": ["...", "..."],
  "alt": "...",
  "instagram_text": "...",
  "facebook_text": "..."
}}
"""
    if note:
        prompt_image += f"\nDodatkowa uwaga od użytkownika: {note}"

    # Upload image to S3 and get public URL
    bucket_name = "kawiarnia-social-media-images"
    public_url = upload_to_s3(image_path, bucket_name)

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": prompt_image},
                {"type": "image_url", "image_url": {"url": public_url}}
            ]}
        ]
    )

    import json
    try:
        data = json.loads(response.choices[0].message.content)
    except Exception:
        data = {
            "caption": "Aromatyczna kawa, idealna na chwilę relaksu.",
            "hashtags": ["#kawa", "#kawiarnia"],
            "alt": "Filiżanka kawy na stole w kawiarni",
            "instagram_text": "Aromatyczna kawa ☕ Zapraszamy na chwilę relaksu.\n———\n#kawa #kawiarnia",
            "facebook_text": "Aromatyczna kawa czeka na Ciebie w naszej kawiarni. Wpadaj dziś do 18:00!"
        }
    return data

def generate_post_text(ai_data):
    caption = ai_data["caption"]
    hashtags = ai_data["hashtags"]
    hashtags_line = " ".join(hashtags[:10])
    instagram_text = f"{caption}\n———\n{hashtags_line}"
    facebook_text = instagram_text
    return {"instagram_text": instagram_text, "facebook_text": facebook_text}

# === Image handler ===
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Odebrano zdjęcie od użytkownika")
    note = update.message.caption
    photo_file = await update.message.photo[-1].get_file()
    photo_path = f"temp_{update.message.message_id}.jpg"
    await photo_file.download_to_drive(photo_path)
    print(f"Zdjęcie zapisane: {photo_path}")

    ai_data = await generate_ai_content(photo_path, note)
    post_texts = generate_post_text(ai_data)
    print("AI wygenerowało treść:")
    print(post_texts)

    await update.message.reply_text(f"✅ Podpis gotowy!\: {post_texts['instagram_text']}")

# === Upload do S3 ===
def upload_to_s3(file_path, bucket_name, object_name=None):
    s3 = boto3.client("s3")
    if object_name is None:
        object_name = os.path.basename(file_path)
    s3.upload_file(file_path, bucket_name, object_name)
    region = s3.get_bucket_location(Bucket=bucket_name)['LocationConstraint']
    return f"https://{bucket_name}.s3.{region}.amazonaws.com/{object_name}"

# === Start bota ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot działa... wyślij zdjęcie!")

def main():
    print("Uruchamiam bota...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.run_polling()

if __name__ == "__main__":
    main()
