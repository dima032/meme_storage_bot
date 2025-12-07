import logging
import os
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
from ml import get_tags
import database as db
import requests
from PIL import Image
import time
from tenacity import retry, wait_fixed, stop_after_attempt, before_log, after_log, retry_if_exception_type, retry_if_exception_type
import functools

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
                await update.inline_query.answer([], cache_time=1) # Respond to inline query with empty results
            elif update.callback_query:
                await update.callback_query.answer("You are not authorized to use this bot.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapped




@restricted
async def start(update: Update, context) -> None:
    """Sends a message when the command /start is issued."""
    await update.message.reply_text("Hi! I'm your personal meme storage bot. "
                                    "Send me a meme and I'll save it for you. "
                                    "You can also use inline mode to search for your memes by tags.")


@restricted
async def save_photo(update: Update, context) -> None:
    """Saves the photo when a user sends one and processes manual tags from caption/text."""
    file = await context.bot.get_file(update.message.photo[-1].file_id)
    file_name = f"{file.file_id}.jpg"
    
    conn = db.create_connection()
    if conn is not None:
        if db.meme_exists(conn, file_name):
            await update.message.reply_text("This meme is already saved.")
            conn.close()
            return
        
        photo_path = f"memes/{file_name}"
        thumbnail_path = f"thumbnails/{file_name}"
        await file.download_to_drive(photo_path)

        # Create and save thumbnail
        logger.info(f"Creating thumbnail for {photo_path}")
        try:
            with Image.open(photo_path) as img:
                img.thumbnail((320, 240))
                img.save(thumbnail_path, "JPEG")
            logger.info(f"Successfully created thumbnail: {thumbnail_path}")
        except Exception as e:
            logger.error(f"Could not create thumbnail for {photo_path}: {e}")

        # Get automatically generated tags from ML
        tags = set(get_tags(photo_path)) # Convert to set for easy adding
        
        # Process manual tags from caption or text message
        manual_input = update.message.caption if update.message.caption else update.message.text
        if manual_input:
            logger.info(f"Processing manual input for tags: '{manual_input}'")
            manual_words = manual_input.split()
            for word in manual_words:
                clean_word = ''.join(filter(str.isalnum, word)).lower()
                if len(clean_word) > 2:
                    tags.add(clean_word)
        
        db.insert_meme(conn, (file_name, ','.join(tags)))
        conn.close()

        await update.message.reply_text(f"Meme saved with tags: {', '.join(tags)}")
    else:
        await update.message.reply_text("Error connecting to the database.")


@restricted
async def inline_query(update: Update, context) -> None:
    """Handle the inline query."""
    query = update.inline_query.query
    
    conn = db.create_connection()
    if conn is not None:
        if query:
            results = db.find_memes_by_tag(conn, query)
        else:
            results = db.get_all_memes(conn)
        conn.close()
    else:
        results = []

    inline_results = []
    public_url = os.environ.get("PUBLIC_URL")
    logger.info(f"Using public URL: {public_url}")

    for result in results:
        photo_url = f"{public_url}/memes/{result[1]}"
        thumbnail_url = f"{public_url}/thumbnails/{result[1]}"
        meme_path = f"memes/{result[1]}"
        try:
            # Note: We don't need to open the image here to get width/height,
            # as Telegram clients typically handle that.
            # This improves performance by avoiding disk I/O.
            inline_results.append(
                InlineQueryResultPhoto(
                    id=f"{result[0]}_{time.time()}",
                    photo_url=photo_url,
                    thumbnail_url=thumbnail_url,
                )
            )
        except Exception as e:
            logger.error(f"Error creating inline result for {meme_path}: {e}")

    logger.info(f"Inline results being sent: {len(inline_results)} items")
    await update.inline_query.answer(inline_results, cache_time=1)


@restricted
async def dump(update: Update, context) -> None:
    """Dumps the database content to the chat."""
    conn = db.create_connection()
    if conn is not None:
        memes = db.get_all_memes(conn)
        conn.close()
    else:
        memes = []
    
    message = "Database content:\n"
    for meme in memes:
        message += f"ID: {meme[0]}, Path: {meme[1]}, Tags: {meme[2]}\n"
    
    await update.message.reply_text(message)
    

# States for conversation
CONFIRM_CLEAR, CANCEL_CLEAR = range(2)

@restricted
async def clear(update: Update, context) -> int:
    """Asks for confirmation to clear the database."""
    keyboard = [
        [
            InlineKeyboardButton("Yes, clear it", callback_data=str(CONFIRM_CLEAR)),
            InlineKeyboardButton("No, cancel", callback_data=str(CANCEL_CLEAR)),
        ]
    ]
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
        if conn is not None:
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
    logger.info("Starting thumbnail regeneration for existing memes...")
    await update.message.reply_text("Starting thumbnail regeneration for existing memes...")
    
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
        logger.info(f"Processing meme: {file_name}")
        photo_path = f"memes/{file_name}"
        thumbnail_path = f"thumbnails/{file_name}"

        if not os.path.exists(photo_path):
            logger.warning(f"Source meme image not found: {photo_path}")
            continue
        
        if os.path.exists(thumbnail_path):
            logger.info(f"Thumbnail already exists, skipping: {thumbnail_path}")
            skipped_count += 1
            continue
            
        try:
            logger.info(f"Creating thumbnail for {photo_path}")
            with Image.open(photo_path) as img:
                img.thumbnail((320, 240))
                img.save(thumbnail_path, "JPEG")
            logger.info(f"Successfully created thumbnail: {thumbnail_path}")
            generated_count += 1
        except Exception as e:
            logger.error(f"Could not create thumbnail for {photo_path}: {e}")

    await update.message.reply_text(f"Thumbnail regeneration complete.\n"
                                    f"Generated: {generated_count}\n"
                                    f"Skipped: {skipped_count}")


@restricted
async def rescan_memes(update: Update, context) -> None:
    """Scans the memes folder for orphan images and adds them to the database."""
    await update.message.reply_text("Starting scan for orphan memes...")
    logger.info("Starting scan for orphan memes...")

    # 1. Get all files on disk
    try:
        disk_memes = {f for f in os.listdir('memes') if os.path.isfile(os.path.join('memes', f))}
    except FileNotFoundError:
        await update.message.reply_text("Error: 'memes' directory not found.")
        logger.error("Could not find 'memes' directory during rescan.")
        return

    # 2. Get all files in database
    conn = db.create_connection()
    if conn is None:
        await update.message.reply_text("Error: Could not connect to the database.")
        return
    db_memes_records = db.get_all_memes(conn)
    db_memes = {record[1] for record in db_memes_records} # record[1] is the file_name

    # 3. Find the difference
    orphan_memes = disk_memes - db_memes
    logger.info(f"Found {len(orphan_memes)} orphan memes to process.")
    
    if not orphan_memes:
        await update.message.reply_text("Scan complete. No orphan memes found.")
        conn.close()
        return

    newly_added_count = 0
    await update.message.reply_text(f"Found {len(orphan_memes)} orphan memes. Processing now... This may take a while.")

    for file_name in orphan_memes:
        logger.info(f"Processing orphan meme: {file_name}")
        photo_path = f"memes/{file_name}"
        thumbnail_path = f"thumbnails/{file_name}"

        # 4. Generate tags and thumbnail, then insert into DB
        try:
            # Generate tags
            tags = set(get_tags(photo_path))
            
            # Create thumbnail
            with Image.open(photo_path) as img:
                img.thumbnail((320, 240))
                img.save(thumbnail_path, "JPEG")
            
            # Insert into database
            db.insert_meme(conn, (file_name, ','.join(tags)))
            logger.info(f"Successfully processed and added to DB: {file_name}")
            newly_added_count += 1
        except Exception as e:
            logger.error(f"Failed to process orphan meme {file_name}: {e}", exc_info=True)
    
    conn.close()
    await update.message.reply_text(f"Rescan complete. Successfully added {newly_added_count} new memes to the database.")


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()

    # Create a conversation handler for the /clear command
    clear_handler = ConversationHandler(
        entry_points=[CommandHandler("clear", clear)],
        states={
            CONFIRM_CLEAR: [CallbackQueryHandler(clear_confirmation)],
        },
        fallbacks=[CommandHandler("clear", clear)],
    )

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("dump", dump))
    application.add_handler(CommandHandler("regenerate_thumbnails", regenerate_thumbnails))
    application.add_handler(CommandHandler("rescan", rescan_memes))
    application.add_handler(clear_handler)

    # on non command i.e message - save the image on filesystem
    application.add_handler(MessageHandler(filters.PHOTO, save_photo))

    # on inline query
    application.add_handler(InlineQueryHandler(inline_query))

    # Run the bot until the user presses Ctrl-C
    application.run_polling()


if __name__ == "__main__":
    main()
