import logging
import os
import sys
import asyncio
import uvicorn
import sqlite3
import hashlib
import tempfile
import shutil
from fastapi import FastAPI, HTTPException
from starlette.responses import FileResponse
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultPhoto, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    InlineQueryHandler,
    ConversationHandler,
    CallbackQueryHandler,
)
import database as db
import ml
from PIL import Image
import time
import functools

# --- Security Configuration ---
URL_SIGNING_SECRET = os.environ.get("URL_SIGNING_SECRET")
if not URL_SIGNING_SECRET:
    logging.critical("FATAL: URL_SIGNING_SECRET environment variable not set.")
    sys.exit(1)

signer = URLSafeTimedSerializer(URL_SIGNING_SECRET)
MEME_DIR = "/app/data/memes"
THUMBNAIL_DIR = "/app/data/thumbnails"


# --- FastAPI App Setup ---
web_app = FastAPI()

def _get_secure_file_path(token: str, base_dir: str):
    """Validates a signed token and returns a secure file path."""
    try:
        # Validate token, max_age is 1 hour (3600 seconds)
        filename = signer.loads(token, max_age=3600)
    except (SignatureExpired, BadTimeSignature):
        raise HTTPException(status_code=403, detail="Invalid or expired token")

    # Path traversal check
    full_path = os.path.abspath(os.path.join(base_dir, filename))
    if not full_path.startswith(os.path.abspath(base_dir)):
        raise HTTPException(status_code=403, detail="Path traversal attempt detected")
        
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="File not found")

    return full_path

@web_app.get("/memes/{token:path}")
async def serve_meme(token: str):
    file_path = _get_secure_file_path(token, MEME_DIR)
    return FileResponse(file_path, media_type="image/jpeg")

@web_app.get("/thumbnails/{token:path}")
async def serve_thumbnail(token: str):
    file_path = _get_secure_file_path(token, THUMBNAIL_DIR)
    return FileResponse(file_path, media_type="image/jpeg")

# Health check endpoint
@web_app.get("/")
async def root():
    return {"message": "Server is running"}

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load allowed Telegram IDs
ALLOWED_TELEGRAM_IDS_STR = os.environ.get("ALLOWED_TELEGRAM_IDS")
if ALLOWED_TELEGRAM_IDS_STR:
    ALLOWED_TELEGRAM_IDS = {int(uid.strip()) for uid in ALLOWED_TELEGRAM_IDS_STR.split(',')}
    logger.info(f"Bot will only respond to Telegram IDs: {ALLOWED_TELEGRAM_IDS}")
else:
    ALLOWED_TELEGRAM_IDS = None
    logger.warning("No ALLOWED_TELEGRAM_IDS found in environment variables. Bot will respond to ALL users.")


def restricted(func):
    """Decorator to restrict access to certain Telegram user IDs."""
    @functools.wraps(func)
    async def wrapped(update: Update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if ALLOWED_TELEGRAM_IDS and user_id not in ALLOWED_TELEGRAM_IDS:
            logger.warning(f"Unauthorized access denied for user {user_id}. Function: {func.__name__}")
            if update.message:
                await update.message.reply_text("You are not authorized to use this bot.")
            elif update.inline_query:
                await update.inline_query.answer([], cache_time=1)
            elif update.callback_query:
                await update.callback_query.answer("You are not authorized to use this bot.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


def _calculate_hash(file_path):
    """Calculates the SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


@restricted
async def start(update: Update, context) -> None:
    """Sends a message when the command /start is issued."""
    await update.message.reply_text("Hi! I'm your personal meme storage bot. "
                                    "Send me a meme with a caption to tag it. "
                                    "You can also use inline mode to search for your memes by tags.")


@restricted
async def save_photo(update: Update, context) -> None:
    """Saves the photo, extracts tags via OCR and caption, and checks for duplicates."""
    photo_obj = update.message.photo[-1]
    file = await context.bot.get_file(photo_obj.file_id)
    file_name = f"{photo_obj.file_id}.jpg"

    conn = db.create_connection()
    if conn is None:
        await update.message.reply_text("Error connecting to the database.")
        return

    temp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file_path = temp_file.name
            await file.download_to_drive(temp_file_path)
            content_hash = _calculate_hash(temp_file_path)

        photo_path = os.path.join(MEME_DIR, file_name)
        thumbnail_path = os.path.join(THUMBNAIL_DIR, file_name)

        # Get tags from both OCR and user caption
        tags = set()
        
        # 1. Get tags from OCR
        logger.info(f"Running OCR on {temp_file_path}...")
        ocr_tags = ml.get_tags_for_image(temp_file_path)
        if ocr_tags:
            tags.update(ocr_tags)
            logger.info(f"OCR tags found: {', '.join(ocr_tags)}")
        
        # 2. Get tags from caption
        manual_input = update.message.caption if update.message.caption else ""
        if manual_input:
            caption_tags = set()
            for word in manual_input.split():
                clean_word = ''.join(filter(str.isalnum, word)).lower()
                if len(clean_word) > 2:
                    caption_tags.add(clean_word)
            tags.update(caption_tags)

        # Save to database
        try:
            db.insert_meme(conn, (content_hash, file_name, ','.join(sorted(list(tags)))))
            shutil.move(temp_file_path, photo_path)
            temp_file_path = None # Prevent deletion in finally block

            # Create thumbnail
            logger.info(f"Creating thumbnail for {photo_path}")
            try:
                with Image.open(photo_path) as img:
                    img.thumbnail((320, 240))
                    img.save(thumbnail_path, "JPEG")
                logger.info(f"Successfully created thumbnail: {thumbnail_path}")
            except Exception as e:
                logger.error(f"Could not create thumbnail for {photo_path}: {e}")
            
            # Send confirmation message
            if tags:
                await update.message.reply_text(f"Meme saved with tags (OCR + Caption): {', '.join(sorted(list(tags)))}")
            else:
                await update.message.reply_text("Meme saved. No tags were found via OCR or caption.")

        except sqlite3.IntegrityError:
            logger.info(f"Duplicate meme received with content_hash: {content_hash}")
            await update.message.reply_text("This meme is already saved.")

    finally:
        if conn:
            conn.close()
        # Clean up temp file if it wasn't moved
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)

@restricted
async def inline_query(update: Update, context) -> None:
    """Handle the inline query."""
    query = update.inline_query.query.lower()
    
    conn = db.create_connection()
    if conn is None: return
    
    all_memes = db.get_all_memes(conn)
    conn.close()

    results = []
    if query:
        search_tags = {tag.strip() for tag in query.split() if len(tag.strip()) > 0}
        for meme in all_memes:
            meme_tags = {t.strip() for t in meme[2].split(',') if t.strip()}
            if search_tags.issubset(meme_tags):
                results.append(meme)
    else:
        results = all_memes

    results.sort(key=lambda x: x[0], reverse=True)
    results = results[:50]

    inline_results = []
    public_url = os.environ.get("PUBLIC_URL")
    if public_url and not public_url.startswith("http"):
        public_url = f"https://{public_url}"
    
    for result in results:
        filename = result[1]
        photo_token = signer.dumps(filename)
        thumb_token = signer.dumps(filename) # Can use the same token
        
        photo_url = f"{public_url}/memes/{photo_token}"
        thumbnail_url = f"{public_url}/thumbnails/{thumb_token}"
        photo_path = os.path.join(MEME_DIR, filename)

        width, height = 0, 0
        try:
            with Image.open(photo_path) as img:
                width, height = img.size
        except Exception as e:
            logger.error(f"Could not open image {photo_path} to get dimensions: {e}")
            continue

        try:
            inline_results.append(
                InlineQueryResultPhoto(
                    id=f"{result[0]}_{time.time()}",
                    photo_url=photo_url,
                    thumbnail_url=thumbnail_url,
                    photo_width=width,
                    photo_height=height,
                )
            )
        except Exception as e:
            logger.error(f"Error creating inline result for meme {filename}: {e}")

    logger.info(f"Inline results being sent: {len(inline_results)} items")
    await update.inline_query.answer(inline_results, cache_time=1)


@restricted
async def dump(update: Update, context) -> None:
    """Dumps the database content to the chat."""
    conn = db.create_connection()
    if conn is None: return
    
    memes = db.get_all_memes(conn)
    conn.close()
    
    message = "Database content:\n"
    for meme in memes:
        message += f"ID: {meme[0]}, Path: {meme[1]}, Tags: {meme[2]}, Hash: {meme[3]}\n"
    
    for i in range(0, len(message), 4096):
        await update.message.reply_text(message[i:i + 4096])


# States for conversation
CONFIRM_CLEAR, CANCEL_CLEAR = range(2)

@restricted
async def clear(update: Update, context) -> int:
    """Asks for confirmation to clear the database."""
    keyboard = [[InlineKeyboardButton("Yes, clear it", callback_data=str(CONFIRM_CLEAR)),
                 InlineKeyboardButton("No, cancel", callback_data=str(CANCEL_CLEAR))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Are you sure you want to clear the entire meme database? This action cannot be undone.", reply_markup=reply_markup)
    return CONFIRM_CLEAR


@restricted
async def clear_confirmation(update: Update, context) -> int:
    """Clears the database or cancels the operation."""
    query = update.callback_query
    await query.answer()
    
    if query.data == str(CONFIRM_CLEAR):
        conn = db.create_connection()
        if conn:
            db.clear_database(conn)
            conn.close()
            await query.edit_message_text(text="Database cleared.")
        else:
            await query.edit_message_text(text="Error connecting to the database.")
    else:
        await query.edit_message_text(text="Operation cancelled.")
    return ConversationHandler.END


@restricted
async def regenerate_thumbnails(update: Update, context) -> None:
    """Generates thumbnails for all existing memes that don't have one."""
    await update.message.reply_text("Starting thumbnail regeneration...")
    
    conn = db.create_connection()
    if conn is None:
        await update.message.reply_text("Error connecting to the database.")
        return
        
    memes = db.get_all_memes(conn)
    conn.close()
    
    generated_count = 0
    skipped_count = 0
    
    for meme in memes:
        file_name = meme[1]
        photo_path = os.path.join(MEME_DIR, file_name)
        thumbnail_path = os.path.join(THUMBNAIL_DIR, file_name)

        if not os.path.exists(photo_path):
            logger.warning(f"Source meme image not found: {photo_path}")
            continue
        
        if os.path.exists(thumbnail_path):
            skipped_count += 1
            continue
            
        try:
            with Image.open(photo_path) as img:
                img.thumbnail((320, 240))
                img.save(thumbnail_path, "JPEG")
            generated_count += 1
            logger.info(f"Generated thumbnail for {file_name}")
        except Exception as e:
            logger.error(f"Could not create thumbnail for {photo_path}: {e}")

    await update.message.reply_text(f"Thumbnail regeneration complete. Generated: {generated_count}, Skipped: {skipped_count}")


@restricted
async def rescan(update: Update, context) -> None:
    """Scans the memes folder for images not in the DB, runs OCR, and adds them."""
    await update.message.reply_text("Starting library rescan...")

    conn = db.create_connection()
    if conn is None:
        await update.message.reply_text("Error connecting to the database.")
        return
    
    try:
        existing_hashes = db.get_all_hashes(conn)
        added_count = 0
        thumb_generated_count = 0
        
        if not os.path.isdir(MEME_DIR):
            await update.message.reply_text(f"Error: Meme directory not found at {MEME_DIR}")
            return

        await update.message.reply_text("Scanning files... This may take a while if OCR is needed.")
        for filename in os.listdir(MEME_DIR):
            file_path = os.path.join(MEME_DIR, filename)
            if not os.path.isfile(file_path):
                continue
            
            content_hash = _calculate_hash(file_path)
            
            if content_hash not in existing_hashes:
                try:
                    logger.info(f"New meme found: {filename}. Running OCR...")
                    tags = ml.get_tags_for_image(file_path)
                    
                    db.insert_meme(conn, (content_hash, filename, ','.join(sorted(list(tags)))))
                    added_count += 1
                    logger.info(f"Added new meme from scan: {filename} with tags: {', '.join(tags)}")
                except sqlite3.IntegrityError:
                    logger.warning(f"Meme from scan was already in DB (race condition): {filename}")
                    continue
            
            thumbnail_path = os.path.join(THUMBNAIL_DIR, filename)
            if not os.path.exists(thumbnail_path):
                try:
                    with Image.open(file_path) as img:
                        img.thumbnail((320, 240))
                        img.save(thumbnail_path, "JPEG")
                    thumb_generated_count += 1
                    logger.info(f"Generated missing thumbnail for {filename}")
                except Exception as e:
                    logger.error(f"Could not create thumbnail for {file_path}: {e}")

        await update.message.reply_text(f"Rescan complete. Added: {added_count} new memes. Generated: {thumb_generated_count} missing thumbnails.")

    finally:
        if conn:
            conn.close()


@restricted
async def retag_all(update: Update, context) -> None:
    """Iterates through all memes in the DB, re-runs OCR, and updates their tags."""
    await update.message.reply_text("Starting to re-tag all memes... This will take a while.")

    conn = db.create_connection()
    if conn is None:
        await update.message.reply_text("Error connecting to the database.")
        return
    
    try:
        all_memes = db.get_all_memes(conn)
        total_memes = len(all_memes)
        processed_count = 0
        
        logger.info(f"Starting re-tagging process for {total_memes} memes.")

        for i, meme in enumerate(all_memes):
            _, file_name, old_tags, content_hash = meme
            
            if content_hash is None:
                logger.warning(f"Skipping meme with missing content_hash: {file_name}")
                continue

            file_path = os.path.join(MEME_DIR, file_name)
            if not os.path.exists(file_path):
                logger.warning(f"Meme file not found, skipping: {file_path}")
                continue

            logger.info(f"Re-tagging {file_path} ({i+1}/{total_memes})")
            new_tags = ml.get_tags_for_image(file_path)
            
            # Here you might want to merge with existing manual tags if you have them.
            # For now, we'll just overwrite with the new OCR tags.
            db.update_meme_tags(conn, content_hash, ','.join(sorted(list(new_tags))))
            processed_count += 1

        logger.info("Re-tagging process finished.")
        await update.message.reply_text(f"Re-tagging complete. Processed {processed_count}/{total_memes} memes.")

    except Exception as e:
        logger.error(f"An error occurred during re-tagging: {e}")
        await update.message.reply_text(f"An error occurred: {e}")
    finally:
        if conn:
            conn.close()


async def main() -> None:
    """Runs the bot and the web server concurrently."""
    application = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()

    clear_handler = ConversationHandler(
        entry_points=[CommandHandler("clear", clear)],
        states={CONFIRM_CLEAR: [CallbackQueryHandler(clear_confirmation)]},
        fallbacks=[CommandHandler("clear", clear)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("dump", dump))
    application.add_handler(CommandHandler("regenerate_thumbnails", regenerate_thumbnails))
    application.add_handler(CommandHandler("rescan", rescan))
    application.add_handler(CommandHandler("retag", retag_all))
    application.add_handler(clear_handler)
    application.add_handler(MessageHandler(filters.PHOTO, save_photo))
    application.add_handler(InlineQueryHandler(inline_query))
    
    config = uvicorn.Config(web_app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)

    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        logger.info("Telegram Bot started.")
        
        await server.serve()
        logger.info("Web server stopped.")
        
        await application.updater.stop()
        await application.stop()
        logger.info("Telegram Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
