import os
import pytz
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv
import boto3
import requests
import assemblyai as aai

load_dotenv()

# === Konfiguracja ===
BOT_TOKEN = os.getenv("TELEGRAM_BOT_KEY")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY")
fb_token = os.getenv("FB_PAGE_TOKEN")
fb_id = os.getenv("FB_PAGE_ID")
ig_token = os.getenv("IG_ACCESS_TOKEN")
ig_id = os.getenv("IG_USER_ID")

user_sessions = {}

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
    user_id = update.message.from_user.id
    note = update.message.caption
    photo_file = await update.message.photo[-1].get_file()
    photo_path = f"temp_{update.message.message_id}.jpg"
    await photo_file.download_to_drive(photo_path)
    user_sessions[user_id] = {
        "photo_path": photo_path,
        "note": note,
        "stage": "photo_uploaded"
    }
    await update.message.reply_text(
        "Zdjęcie odebrane 👍 Dodaj notatkę (opcjonalnie), albo napisz 'zobacz' aby wygenerować podgląd posta."
    )

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    file_path = str(await file.download_to_drive(f"voice_{update.message.message_id}.ogg"))
    transcriber = aai.Transcriber(config=aai.TranscriptionConfig(language_code="pl"))
    transcript = transcriber.transcribe(file_path)
    if transcript.status == aai.TranscriptStatus.error:
        await update.message.reply_text("❌ Nie udało się rozpoznać głosu.")
        return
    text = transcript.text
    session = user_sessions.get(user_id, {})
    session["note"] = text
    session["stage"] = "note_added"
    user_sessions[user_id] = session
    await update.message.reply_text(
        f"Rozpoznano notatkę: {text}\nNapisz 'zobacz' aby wygenerować podgląd posta."
    )

async def handle_text_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    note_text = update.message.text
    session = user_sessions.get(user_id, {})
    # If user is at preview stage, treat as correction
    if session.get("stage") == "preview_shown":
        session["correction"] = note_text
        session["note"] = note_text  # treat correction as new note
        ai_data = await generate_ai_content(session["photo_path"], note_text)
        post_texts = generate_post_text(ai_data)
        session["post_texts"] = post_texts
        user_sessions[user_id] = session
        await update.message.reply_text(
            f"Oto podgląd posta 👇\nInstagram: {post_texts['instagram_text']}\n\nFacebook: {post_texts['facebook_text']}\nChcesz coś zmienić? Dodaj poprawkę w wiadomości albo napisz 'gotowe', jeśli jest ok."
        )
    else:
        session["note"] = note_text
        session["stage"] = "note_added"
        user_sessions[user_id] = session
        await update.message.reply_text(
            "Notatka dodana. Napisz 'zobacz' aby wygenerować podgląd posta."
        )

async def handle_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    session = user_sessions.get(user_id)
    if not session or "photo_path" not in session:
        await update.message.reply_text("Najpierw wyślij zdjęcie.")
        return
    ai_data = await generate_ai_content(session["photo_path"], session.get("note"))
    post_texts = generate_post_text(ai_data)
    session["post_texts"] = post_texts
    session["stage"] = "preview_shown"
    user_sessions[user_id] = session
    await update.message.reply_text(
        f"Oto podgląd posta 👇\nInstagram: {post_texts['instagram_text']}\n\nFacebook: {post_texts['facebook_text']}\nChcesz coś zmienić? Dodaj poprawkę w wiadomości albo napisz 'gotowe', jeśli jest ok."
    )

async def handle_ready(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    session = user_sessions.get(user_id)
    if not session or session.get("stage") != "preview_shown":
        await update.message.reply_text("Najpierw wygeneruj podgląd posta ('zobacz').")
        return
    session["stage"] = "ready_to_publish"
    user_sessions[user_id] = session
    reply_markup = ReplyKeyboardMarkup([["Tak", "Nie"]], one_time_keyboard=True)
    await update.message.reply_text(
        "Opublikować post? (Tak/Nie)",
        reply_markup=reply_markup
    )

async def handle_publish_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    session = user_sessions.get(user_id)
    if not session or session.get("stage") != "ready_to_publish" or "post_texts" not in session or "photo_path" not in session:
        await update.message.reply_text("Brak posta do publikacji.")
        return
    if update.message.text.lower() == "tak":
        bucket_name = "kawiarnia-social-media-images"
        public_url = upload_to_s3(session["photo_path"], bucket_name)
        fb_result = post_to_facebook(fb_token, fb_id, session["post_texts"]["facebook_text"], public_url)
        ig_result = post_to_instagram(ig_token, ig_id, session["post_texts"]["instagram_text"], public_url)
        session["stage"] = "published"
        await update.message.reply_text("✅ Posty zostały opublikowane!")
    else:
        session["stage"] = "preview_shown"
        await update.message.reply_text("Post nie został opublikowany. Możesz dodać nową notatkę albo zakończyć.")

# === Upload do S3 ===
def upload_to_s3(file_path, bucket_name, object_name=None):
    s3 = boto3.client("s3")
    if object_name is None:
        object_name = os.path.basename(file_path)
    s3.upload_file(file_path, bucket_name, object_name)
    region = s3.get_bucket_location(Bucket=bucket_name)['LocationConstraint']
    return f"https://{bucket_name}.s3.{region}.amazonaws.com/{object_name}"

def post_to_facebook(page_access_token, page_id, message, image_url):
    url = f"https://graph.facebook.com/{page_id}/photos"
    payload = {
        "url": image_url,
        "caption": message,
        "access_token": page_access_token
    }
    response = requests.post(url, data=payload)
    return response.json()

def post_to_instagram(insta_access_token, insta_user_id, caption, image_url):
    # Step 1: Create media object
    media_url = f"https://graph.facebook.com/v19.0/{insta_user_id}/media"
    media_payload = {
        "image_url": image_url,
        "caption": caption,
        "access_token": insta_access_token
    }
    media_resp = requests.post(media_url, data=media_payload).json()
    creation_id = media_resp.get("id")
    # Step 2: Publish media object
    publish_url = f"https://graph.facebook.com/v19.0/{insta_user_id}/media_publish"
    publish_payload = {
        "creation_id": creation_id,
        "access_token": insta_access_token
    }
    publish_resp = requests.post(publish_url, data=publish_payload)
    return publish_resp.json()

# === Start bota ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot działa... wyślij zdjęcie!")

def main():
    print("Uruchamiam bota...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^zobacz$"), handle_preview))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^gotowe$"), handle_ready))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^(Tak|Nie)$"), handle_publish_decision))
    # All other text is either note or correction
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^(zobacz|gotowe|Tak|Nie)$"), handle_text_note))
    app.run_polling()

if __name__ == "__main__":
    main()
