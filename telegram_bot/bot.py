import os
import logging
import requests
import io
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Moved logger initialization ---
# Setting up logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
# --- End of moved block ---

# --- Loading environment variables from .env file ---
try:
    from dotenv import load_dotenv
    # Try to load variables from .env file
    # Check several possible paths to .env file
    possible_paths = [
        './.env', 
        '../.env', 
        '../../.env',
        '/app/.env'  # Typical path for Docker container
    ]
    
    for env_path in possible_paths:
        if os.path.exists(env_path):
            logger.info(f"Loading environment variables from {env_path}")
            load_dotenv(env_path)
            break
except ImportError:
    logger.warning("The dotenv library is not installed. Skipping loading variables from .env file.")

# --- Built-in functions from pict.py ---
def fetch_unsplash_images(query, num=1, access_key=None):
    """Searches for images on Unsplash and returns a list of tuples (url, photographer, image id)."""
    if not access_key:
        logger.warning("Error: Unsplash access key not provided.")
        return []
        
    # Using the official API endpoint
    url = f"https://api.unsplash.com/search/photos"
    headers = {
        "Authorization": f"Client-ID {access_key}"
    }
    params = {
        "query": query,
        "per_page": num,
        "orientation": "landscape"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status() 
        data = response.json()
        
        if "results" in data and data["results"]:
            # Return tuples (url, photographer_name, photographer_username, photo_id)
            image_info = [(
                img["urls"]["regular"], 
                img["user"]["name"], 
                img["user"]["username"],
                img["id"]
            ) for img in data["results"]]
            return image_info
        else:
            logger.info(f"Unsplash: no images found for '{query}'.")
            return []
             
    except requests.exceptions.RequestException as e:
        logger.error(f"Unsplash API request error: {e}")
        return []
    except Exception as e: 
        logger.error(f"Unexpected error during Unsplash request: {e}")
        return []

def trigger_unsplash_download(photo_id, access_key=None):
    """Sends a request to Unsplash API to register a download (Unsplash requirement)."""
    if not access_key or not photo_id:
        return False
        
    try:
        download_url = f"https://api.unsplash.com/photos/{photo_id}/download"
        headers = {
            "Authorization": f"Client-ID {access_key}"
        }
        response = requests.get(download_url, headers=headers, timeout=5)
        response.raise_for_status()
        logger.info(f"Successfully sent download request for photo ID: {photo_id}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error registering Unsplash download: {e}")
        return False

def download_image_data(image_url):
    """Downloads an image by URL and returns its content (bytes)."""
    try:
        img_response = requests.get(image_url, stream=True, timeout=15)
        img_response.raise_for_status() 
        return img_response.content
    except requests.exceptions.RequestException as e:
        logger.error(f"Error downloading image {image_url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error downloading image {image_url}: {e}")
        return None
# --- End of built-in functions ---

# Getting environment variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_HOST = os.getenv("API_HOST", "cambridge-api")
API_PORT = os.getenv("API_PORT", "8000")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")

# Logging variable values (without token, for security)
logger.info(f"API_HOST: {API_HOST}")
logger.info(f"API_PORT: {API_PORT}")
logger.info(f"UNSPLASH_ACCESS_KEY set: {'Yes' if UNSPLASH_ACCESS_KEY else 'No'}")

# Check for required keys
if not TELEGRAM_BOT_TOKEN:
    logger.critical("Environment variable TELEGRAM_BOT_TOKEN is not set!")
    exit("Error: TELEGRAM_BOT_TOKEN not found.")
if not UNSPLASH_ACCESS_KEY:
    logger.warning("Environment variable UNSPLASH_ACCESS_KEY is not set! Image search feature will be unavailable.")

API_URL = f"http://{API_HOST}:{API_PORT}"

# Maximum message length in Telegram
MAX_MESSAGE_LENGTH = 4000  # Leaving some buffer for safety (actual limit is 4096)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is used."""
    await update.message.reply_text(
        "Hi! I'm a bot for searching word definitions in Cambridge Dictionary. "
        "Just send me an English word."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends help when the /help command is used."""
    await update.message.reply_text(
        "Send me an English word, and I'll find its definition in Cambridge Dictionary."
    )

def split_message(text, max_length=MAX_MESSAGE_LENGTH):
    """Splits long text into parts of suitable size."""
    if len(text) <= max_length:
        return [text]
    
    parts = []
    current_part = ""
    
    # Split text by paragraphs for more natural division
    paragraphs = text.split('\n\n')
    
    for paragraph in paragraphs:
        # If paragraph itself is too long, split it by lines
        if len(paragraph) > max_length:
            lines = paragraph.split('\n')
            for line in lines:
                # If even one line is too long, split it into parts
                if len(line) > max_length:
                    for i in range(0, len(line), max_length):
                        chunk = line[i:i+max_length]
                        if len(current_part + chunk) > max_length:
                            parts.append(current_part)
                            current_part = chunk
                        else:
                            current_part += chunk
                else:
                    if len(current_part + '\n' + line) > max_length:
                        parts.append(current_part)
                        current_part = line
                    else:
                        current_part = current_part + '\n' + line if current_part else line
        else:
            if len(current_part + '\n\n' + paragraph) > max_length:
                parts.append(current_part)
                current_part = paragraph
            else:
                current_part = current_part + '\n\n' + paragraph if current_part else paragraph
    
    if current_part:
        parts.append(current_part)
    
    return parts

async def download_and_send_audio(update, audio_url, caption="", voice_type="US"):
    """Downloads audio by URL and sends it to the chat."""
    try:
        response = requests.get(
            audio_url, 
            stream=True,
            headers={"User-Agent": "Mozilla/5.0"},  # Adding header
            verify=False  # Disabling SSL verification
        )
        response.raise_for_status()
        
        audio_data = io.BytesIO(response.content)
        audio_data.name = f"pronunciation_{voice_type}.mp3"
        
        # Send audio
        await update.message.reply_voice(
            voice=audio_data, 
            caption=caption,
            filename=audio_data.name
        )
        return True
    except Exception as e:
        logger.error(f"Error downloading/sending audio: {e}")
        return False

async def search_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search for word definition through API service and send image."""
    word = update.message.text.strip().lower()
    
    if not word:
        await update.message.reply_text("Please enter a word to search.")
        return
    
    await update.message.reply_text(f"Looking up the definition for '{word}'...")
    
    try:
        response = requests.get(f"{API_URL}/search/{word}", timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "error" in data:
            await update.message.reply_text(f"Error: {data['error']}")
            return
        
        # Format the main message
        result = f"📚 *{data['word'].capitalize()}*\n\n"
        
        # Format parts of speech
        if "pos" in data and data["pos"]:
            result += f"🔤 *Part of speech:* {', '.join(data['pos'])}\n\n"
        
        # Pronunciation
        if "pronunciation" in data and data["pronunciation"]:
            result += "*Pronunciation:*\n"
            unique_prons = {}
            for pron in data["pronunciation"]:
                key = f"{pron['lang']}-{pron['pron']}"
                if key not in unique_prons:
                    unique_prons[key] = pron
            
            for key, pron in unique_prons.items():
                lang_label = "🇬🇧 UK" if pron['lang'] == 'uk' else "🇺🇸 US" if pron['lang'] == 'us' else pron['lang'].upper()
                result += f"{lang_label}: {pron['pron']}\n"
            result += "\n"
        
        # Definitions
        if "definition" in data and data["definition"]:
            result += "*Definitions:*\n"
            for i, definition in enumerate(data["definition"], 1):
                pos = f" ({definition['pos']})" if 'pos' in definition and definition['pos'] else ""
                result += f"{i}.{pos} {definition['text']}\n"
                
                # If translation exists
                if "translation" in definition and definition["translation"]:
                    result += f"   _Translation:_ {definition['translation']}\n"
                
                # If examples exist
                if "example" in definition and definition["example"]:
                    result += "   _Examples:_\n"
                    for ex in definition["example"][:3]:
                        result += f"   • {ex['text']}\n"
                        if 'translation' in ex and ex['translation']:
                            result += f"     {ex['translation']}\n"
                    result += "\n"
        else:
            result += "No definitions found.\n"
        
        # Split the final message into parts and send
        message_parts = split_message(result)
        
        for i, part in enumerate(message_parts):
            if i == 0:
                # First part without additional information
                await update.message.reply_text(part, parse_mode="Markdown")
            else:
                # Subsequent parts with indication that this is a continuation
                await update.message.reply_text(f"(Continued {i+1}/{len(message_parts)})\n\n{part}", parse_mode="Markdown")
        
        # Send audio if available
        uk_pron_sent = False
        us_pron_sent = False
        if "pronunciation" in data and data["pronunciation"]:
            uk_pron = next((p for p in data["pronunciation"] if p["lang"] == "uk"), None)
            us_pron = next((p for p in data["pronunciation"] if p["lang"] == "us"), None)
            
            if uk_pron:
                uk_pron_sent = await download_and_send_audio(
                    update, 
                    uk_pron["url"], 
                    f"🇬🇧 British pronunciation of the word '{data['word']}'",
                    "UK"
                )
            
            if us_pron and (not uk_pron or us_pron["url"] != uk_pron["url"]):
                us_pron_sent = await download_and_send_audio(
                    update, 
                    us_pron["url"], 
                    f"🇺🇸 American pronunciation of the word '{data['word']}'",
                    "US"
                )

        # --- Modified block for searching and sending images ---
        if UNSPLASH_ACCESS_KEY:
            logger.info(f"Searching for an image for '{word}' on Unsplash...")
            image_results = fetch_unsplash_images(word, num=1, access_key=UNSPLASH_ACCESS_KEY)

            if image_results:
                # Unpack photo information
                image_url, photographer_name, photographer_username, photo_id = image_results[0]
                logger.info(f"Image found: {image_url}. Photographer: {photographer_name}. Downloading...")
                image_data = download_image_data(image_url)

                if image_data:
                    try:
                        image_bytes_io = io.BytesIO(image_data)
                        image_bytes_io.name = f"{word}_unsplash.jpg"
                        
                        # Create proper attribution according to Unsplash requirements
                        photographer_url = f"https://unsplash.com/@{photographer_username}?utm_source=dictionary_bot&utm_medium=referral"
                        unsplash_url = "https://unsplash.com/?utm_source=dictionary_bot&utm_medium=referral"
                        
                        # Change attribution format to English with clickable links
                        attribution = (
                            f"🖼️ Illustration for the word '{word.capitalize()}'\n"
                            f"Photo by [{photographer_name}]({photographer_url}) on [Unsplash]({unsplash_url})"
                        )
                        
                        await update.message.reply_photo(
                            photo=image_bytes_io, 
                            caption=attribution,
                            parse_mode="Markdown"
                        )
                        logger.info(f"Image for '{word}' successfully sent.")
                        
                        # Register photo usage according to Unsplash API
                        trigger_unsplash_download(photo_id, UNSPLASH_ACCESS_KEY)
                    except Exception as e:
                        logger.error(f"Error sending photo for '{word}': {e}", exc_info=True)
                else:
                    logger.warning(f"Failed to download image data for '{word}' from URL: {image_url}")
            else:
                logger.info(f"No images found for '{word}' on Unsplash.")
        else:
            logger.debug("UNSPLASH_ACCESS_KEY not configured, skipping image search.")
        # --- End of modified block ---

    except requests.RequestException as e:
        logger.error(f"Error while requesting API: {e}")
        await update.message.reply_text("Error connecting to dictionary service. Please try again later.")
    except Exception as e:
        logger.error(f"Unexpected error occurred while processing word '{word}': {e}", exc_info=True)
        await update.message.reply_text("An internal error occurred. Please try again later.")

def main() -> None:
    """Start the bot."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_word))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()
