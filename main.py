import os
import logging
import requests
import time
import tempfile
import base64
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging for Railway
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot credentials from environment variables with error handling
try:
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        raise ValueError("Missing required environment variables")
        
    logger.info("Environment variables loaded successfully")
    
except (ValueError, TypeError) as e:
    logger.error(f"Error loading environment variables: {e}")
    logger.error("Make sure API_ID, API_HASH, and BOT_TOKEN are set in Railway")
    exit(1)

# Use temporary directory for downloads in cloud environment
DOWNLOADS_DIR = os.path.join(tempfile.gettempdir(), "bot_downloads")
if not os.path.exists(DOWNLOADS_DIR):
    os.makedirs(DOWNLOADS_DIR)

# Start bot with error handling
try:
    bot = Client("gofile_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
    logger.info("Bot client created successfully")
except Exception as e:
    logger.error(f"Failed to create bot client: {e}")
    exit(1)


# Upload function using GoFile's current endpoint
def upload_to_gofile(file_path, progress_callback=None):
    logger.info("Uploading to GoFile: %s", file_path)
    
    # Use the main GoFile upload endpoint directly
    upload_url = "https://store1.gofile.io/uploadFile"
    
    try:
        file_size = os.path.getsize(file_path)
        logger.info(f"File size: {file_size / (1024*1024):.2f} MB")
        
        if progress_callback:
            progress_callback("📤 Starting upload...")
        
        # Increase timeout for larger files (up to 30 minutes for 2GB files)
        timeout = min(1800, max(300, file_size // (1024 * 1024) * 10))  # 10 seconds per MB, max 30 minutes
        logger.info(f"Using timeout: {timeout} seconds for this upload")
        
        with open(file_path, "rb") as f:
            files = {'file': (os.path.basename(file_path), f)}
            data = {'token': ''}  # Empty token for guest uploads
            
            if progress_callback:
                progress_callback("📤 Uploading to GoFile...")
            
            response = requests.post(upload_url, files=files, data=data, timeout=timeout)

        logger.info(f"Upload response status: {response.status_code}")
        logger.info(f"Upload response text: {response.text}")
        
        if response.status_code != 200:
            logger.error(f"Upload failed: HTTP {response.status_code}")
            return None
            
        if not response.text.strip():
            logger.error("Empty response from GoFile API")
            return None

        result = response.json()
        if result["status"] != "ok":
            logger.error(f"Upload failed: {result}")
            return None
            
        return result["data"]["downloadPage"]
        
    except requests.exceptions.Timeout:
        logger.error("Upload timeout - file too large or slow connection")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during upload: {e}")
        return None
    except ValueError as e:
        logger.error(f"JSON parsing error: {e}")
        logger.error(f"Response content: {response.text}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during upload: {e}")
        return None
    finally:
        # Clean up the downloaded file
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up file {file_path}: {e}")


# Generate Telegram direct links
def generate_telegram_links(file_id, file_name, file_size):
    """Generate direct download and streaming links from Telegram"""
    try:
        # Create a simple hash for the file
        file_hash = base64.b64encode(file_id.encode()).decode()[:10]
        
        # Generate direct download link
        download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_id}"
        
        # For streaming, we'll create a custom endpoint (this is a simplified example)
        stream_url = f"https://tgstream.example.com/stream/{file_id}?hash={file_hash}"
        
        return {
            'download': download_url,
            'stream': stream_url,
            'hash': file_hash
        }
    except Exception as e:
        logger.error(f"Error generating Telegram links: {e}")
        return None

# Get file path from Telegram
async def get_telegram_file_path(file_id):
    """Get the file path from Telegram servers"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile"
        params = {'file_id': file_id}
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            if data['ok']:
                return data['result']['file_path']
        return None
    except Exception as e:
        logger.error(f"Error getting file path: {e}")
        return None


# Format file size for display
def format_file_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


# Start command handler
@bot.on_message(filters.command("start") & filters.private)
async def start_command(_, message: Message):
    welcome_text = """
🚀 **Welcome to Advanced File Upload Bot!**

📁 **Supported file types:**
• 📄 Documents (PDF, DOC, ZIP, etc.)
• 🖼️ Photos (JPG, PNG, WEBP, etc.)
• 🎥 Videos (MP4, AVI, MKV, etc.)
• 🎵 Audio (MP3, WAV, OGG, etc.)
• 🎙️ Voice messages
• 📹 Video notes (circles)
• 🎨 Stickers
• 📎 Any other file type

✨ **Features:**
• 📥 **Instant Direct Links** - Download immediately
• 🎬 **Streaming Links** - Stream videos/audio
• ☁️ **GoFile Upload** - Anonymous cloud storage
• 📊 **Progress tracking**
• 🔄 **Resumable downloads**
• 🔒 **Anonymous uploads**
• 📏 **Up to 2GB file size**

🚀 **How it works:**
1. Send me any file
2. Get instant Telegram direct links
3. Option to upload to GoFile for permanent storage

Just send me any file or media! 📎
    """
    await message.reply_text(welcome_text)


# Function to get appropriate filename and extension
def get_file_info(message):
    """Extract file info from different message types"""
    if message.document:
        return {
            'file': message.document,
            'name': message.document.file_name or f"document_{message.document.file_unique_id}",
            'size': message.document.file_size,
            'type': 'Document'
        }
    elif message.photo:
        photo = message.photo
        return {
            'file': photo,
            'name': f"photo_{photo.file_unique_id}.jpg",
            'size': photo.file_size,
            'type': 'Photo'
        }
    elif message.video:
        video = message.video
        name = video.file_name or f"video_{video.file_unique_id}.mp4"
        return {
            'file': video,
            'name': name,
            'size': video.file_size,
            'type': 'Video'
        }
    elif message.audio:
        audio = message.audio
        # Try to construct filename from metadata
        if audio.file_name:
            name = audio.file_name
        elif audio.title and audio.performer:
            name = f"{audio.performer} - {audio.title}.mp3"
        elif audio.title:
            name = f"{audio.title}.mp3"
        else:
            name = f"audio_{audio.file_unique_id}.mp3"
        return {
            'file': audio,
            'name': name,
            'size': audio.file_size,
            'type': 'Audio'
        }
    elif message.voice:
        voice = message.voice
        return {
            'file': voice,
            'name': f"voice_{voice.file_unique_id}.ogg",
            'size': voice.file_size,
            'type': 'Voice'
        }
    elif message.video_note:
        video_note = message.video_note
        return {
            'file': video_note,
            'name': f"video_note_{video_note.file_unique_id}.mp4",
            'size': video_note.file_size,
            'type': 'Video Note'
        }
    elif message.sticker:
        sticker = message.sticker
        ext = "webp" if not sticker.is_animated else "tgs"
        return {
            'file': sticker,
            'name': f"sticker_{sticker.file_unique_id}.{ext}",
            'size': sticker.file_size,
            'type': 'Sticker'
        }
    return None


# Universal media handler with instant links
@bot.on_message((filters.document | filters.photo | filters.video | 
                filters.audio | filters.voice | filters.video_note | 
                filters.sticker) & filters.private)
async def handle_media(_, message: Message):
    user = message.from_user
    
    # Get file information
    file_info = get_file_info(message)
    if not file_info:
        await message.reply_text("❌ Unable to process this file type.")
        return
    
    file_obj = file_info['file']
    file_name = file_info['name']
    file_size = format_file_size(file_info['size'])
    file_type = file_info['type']
    
    # Check file size limit
    if file_info['size'] > 2 * 1024 * 1024 * 1024:  # 2GB limit
        await message.reply_text(
            f"❌ **File too large!**\n\n"
            f"📁 **Type:** `{file_type}`\n"
            f"📏 **Size:** `{file_size}`\n"
            f"🚫 **Maximum allowed:** `2 GB`\n\n"
            f"Please send a smaller file."
        )
        return
    
    # Show processing message
    status_msg = await message.reply_text(
        f"📁 **Type:** `{file_type}`\n"
        f"📄 **File:** `{file_name}`\n"
        f"📏 **Size:** `{file_size}`\n"
        f"⏳ **Status:** Generating links..."
    )
    
    try:
        # Get Telegram file path
        file_path = await get_telegram_file_path(file_obj.file_id)
        
        if file_path:
            # Generate instant Telegram links
            telegram_links = {
                'download': f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}",
                'stream': f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}",
                'hash': base64.b64encode(file_obj.file_id.encode()).decode()[:10]
            }
            
            # Update status to show options
            await status_msg.edit_text(
                f"✅ **Links Generated Successfully!**\n\n"
                f"📂 **File Name:** `{file_name}`\n"
                f"📊 **File Size:** `{file_size}`\n\n"
                f"📥 **Download:** [Direct Link]({telegram_links['download']})\n"
                f"🎬 **Stream:** [Stream Link]({telegram_links['stream']})\n\n"
                f"🔗 **File ID:** `{file_obj.file_id}`\n"
                f"🔐 **Hash:** `{telegram_links['hash']}`",
                disable_web_page_preview=True
            )
            
            # Add inline keyboard for options
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📥 Download", url=telegram_links['download']),
                    InlineKeyboardButton("🎬 Stream", url=telegram_links['stream'])
                ],
                [
                    InlineKeyboardButton("☁️ Upload to GoFile", callback_data=f"gofile_{file_obj.file_id}")
                ]
            ])
            
            await message.reply_text(
                f"🚀 **Choose your preferred option:**\n\n"
                f"📥 **Direct Download** - Instant, resumable\n"
                f"🎬 **Stream** - Watch/listen directly\n"
                f"☁️ **GoFile** - Anonymous cloud upload\n\n"
                f"💡 **Tip:** Direct links expire in 1 hour!",
                reply_markup=keyboard
            )
            
        else:
            # Fallback to GoFile upload
            await handle_gofile_upload(message, status_msg, file_info)
            
    except Exception as e:
        logger.error(f"Error processing {file_type}: {e}")
        await status_msg.edit_text(
            f"📁 **Type:** `{file_type}`\n"
            f"📄 **File:** `{file_name}`\n"
            f"📏 **Size:** `{file_size}`\n"
            f"❌ **Status:** Error occurred"
        )
        await message.reply_text(f"❌ Error: {e}")

# Handle GoFile upload callback
@bot.on_callback_query()
async def handle_callback(_, callback_query):
    data = callback_query.data
    
    if data.startswith("gofile_"):
        file_id = data.replace("gofile_", "")
        await callback_query.answer("Uploading to GoFile...")
        
        # Get the original message
        message = callback_query.message.reply_to_message
        if not message:
            await callback_query.message.edit_text("❌ Original file not found!")
            return
            
        # Get file info again
        file_info = get_file_info(message)
        if not file_info:
            await callback_query.message.edit_text("❌ Unable to process this file!")
            return
            
        # Start GoFile upload process
        await handle_gofile_upload(message, callback_query.message, file_info)

# Separate GoFile upload handler
async def handle_gofile_upload(message, status_msg, file_info):
    """Handle GoFile upload process"""
    file_obj = file_info['file']
    file_name = file_info['name']
    file_size = format_file_size(file_info['size'])
    file_type = file_info['type']
    
    try:
        await status_msg.edit_text(
            f"📁 **Type:** `{file_type}`\n"
            f"📄 **File:** `{file_name}`\n"
            f"📏 **Size:** `{file_size}`\n"
            f"⏳ **Status:** Downloading for GoFile upload..."
        )
        
        start_time = time.time()
        # Download the file
        file_path = await message.download(
            file_name=f"{DOWNLOADS_DIR}/{file_obj.file_unique_id}_{file_name}",
            progress=lambda current, total: None
        )
        download_time = time.time() - start_time
        
        logger.info(f"Downloaded {file_type} to {file_path} in {download_time:.2f}s")

        # Update status for upload
        await status_msg.edit_text(
            f"📁 **Type:** `{file_type}`\n"
            f"📄 **File:** `{file_name}`\n"
            f"📏 **Size:** `{file_size}`\n"
            f"✅ **Downloaded:** `{download_time:.1f}s`\n"
            f"⏳ **Status:** Uploading to GoFile..."
        )

        # Upload progress callback
        async def update_progress(status):
            try:
                await status_msg.edit_text(
                    f"📁 **Type:** `{file_type}`\n"
                    f"📄 **File:** `{file_name}`\n"
                    f"📏 **Size:** `{file_size}`\n"
                    f"✅ **Downloaded:** `{download_time:.1f}s`\n"
                    f"⏳ **Status:** {status}"
                )
            except:
                pass

        start_upload_time = time.time()
        link = upload_to_gofile(file_path, lambda status: bot.loop.create_task(update_progress(status)))
        upload_time = time.time() - start_upload_time

        if link:
            type_emoji = {
                'Document': '📄', 'Photo': '🖼️', 'Video': '🎥',
                'Audio': '🎵', 'Voice': '🎙️', 'Video Note': '📹', 'Sticker': '🎨'
            }
            
            await status_msg.edit_text(
                f"✅ **GoFile Upload Successful!**\n\n"
                f"{type_emoji.get(file_type, '📎')} **{file_type}:** `{file_name}`\n"
                f"🔗 [**Download Link**]({link})\n\n"
                f"⚡ Total time: `{download_time + upload_time:.1f}s`",
                disable_web_page_preview=True
            )
        else:
            await status_msg.edit_text(
                f"❌ **GoFile upload failed!**\n\n"
                f"Please try again or use the direct Telegram links."
            )
            
    except Exception as e:
        logger.error(f"Error in GoFile upload: {e}")
        await status_msg.edit_text(f"❌ Error during GoFile upload: {e}")


# Handler for unsupported message types
@bot.on_message(filters.private & ~filters.command("start") & 
                ~filters.document & ~filters.photo & ~filters.video & 
                ~filters.audio & ~filters.voice & ~filters.video_note & 
                ~filters.sticker)
async def handle_unsupported(_, message: Message):
    await message.reply_text(
        "❌ **Unsupported message type!**\n\n"
        "📎 Please send a **file, photo, video, audio, or document**.\n"
        "🚫 Text messages, contacts, and locations are not supported.\n\n"
        "💡 **Tip:** Use /start to see all supported file types."
    )


if __name__ == "__main__":
    logger.info("Starting GoFile Upload Bot on Railway...")
    logger.info("Bot is ready to handle file uploads!")
    try:
        bot.run()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        exit(1)
