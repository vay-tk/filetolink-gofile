import os
import logging
import requests
import time
import tempfile
import base64
import json
import hashlib
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
    
    try:
        file_size = os.path.getsize(file_path)
        logger.info(f"File size: {file_size / (1024*1024):.2f} MB")
        
        if progress_callback:
            progress_callback("📤 Getting upload server...")
        
        # First try to get the best server
        upload_url = "https://store1.gofile.io/uploadFile"
        try:
            server_response = requests.get("https://api.gofile.io/getServer", timeout=10)
            if server_response.status_code == 200:
                server_data = server_response.json()
                if server_data.get("status") == "ok":
                    server = server_data["data"]["server"]
                    upload_url = f"https://{server}.gofile.io/uploadFile"
                    logger.info(f"Using server: {server}")
        except:
            logger.info("Using fallback server")
        
        if progress_callback:
            progress_callback("📤 Starting upload...")
        
        # Calculate timeout based on file size (minimum 5 minutes, maximum 30 minutes)
        timeout = min(1800, max(300, file_size // (1024 * 1024) * 15))  # 15 seconds per MB
        logger.info(f"Using timeout: {timeout} seconds for this upload")
        
        # Prepare the upload with streaming
        with open(file_path, "rb") as f:
            files = {'file': (os.path.basename(file_path), f, 'application/octet-stream')}
            
            if progress_callback:
                progress_callback("📤 Uploading to GoFile...")
            
            # Use session for better connection handling
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            response = session.post(
                upload_url, 
                files=files, 
                timeout=timeout,
                stream=True
            )

        logger.info(f"Upload response status: {response.status_code}")
        logger.info(f"Upload response headers: {dict(response.headers)}")
        
        if response.status_code != 200:
            logger.error(f"Upload failed: HTTP {response.status_code}")
            logger.error(f"Response content: {response.text}")
            return None
            
        response_text = response.text.strip()
        logger.info(f"Upload response text: {response_text}")
        
        if not response_text:
            logger.error("Empty response from GoFile API")
            return None

        try:
            result = response.json()
        except ValueError as e:
            logger.error(f"Invalid JSON response: {e}")
            logger.error(f"Raw response: {response_text}")
            return None
            
        if result.get("status") != "ok":
            logger.error(f"Upload failed: {result}")
            return None
            
        download_page = result.get("data", {}).get("downloadPage")
        if not download_page:
            logger.error("No download page in response")
            return None
            
        logger.info(f"Upload successful: {download_page}")
        return download_page
        
    except requests.exceptions.Timeout:
        logger.error(f"Upload timeout after {timeout} seconds - file too large or slow connection")
        return None
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error during upload: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during upload: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during upload: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
    finally:
        # Clean up the downloaded file
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up file {file_path}: {e}")


# File storage for instant links (in production, use a database)
file_storage = {}

# Generate unique file ID and store file info
def store_file_info(file_obj, file_name, file_size, file_type):
    """Store file information and generate unique ID"""
    try:
        # Generate unique file ID
        unique_data = f"{file_obj.file_id}_{file_obj.file_unique_id}_{int(time.time())}"
        file_hash = hashlib.md5(unique_data.encode()).hexdigest()[:10]
        unique_id = int(time.time() * 1000) % 1000000  # 6-digit unique ID
        
        # Store file information
        file_info = {
            'telegram_file_id': file_obj.file_id,
            'telegram_file_unique_id': file_obj.file_unique_id,
            'file_name': file_name,
            'file_size': file_size,
            'file_type': file_type,
            'created_at': int(time.time()),
            'hash': file_hash
        }
        
        file_storage[unique_id] = file_info
        logger.info(f"Stored file info for ID: {unique_id}")
        
        return unique_id, file_hash
        
    except Exception as e:
        logger.error(f"Error storing file info: {e}")
        return None, None

# Generate instant download and streaming links
def generate_instant_links(unique_id, file_hash, file_name, telegram_file_path):
    """Generate instant download and streaming links"""
    try:
        if not telegram_file_path:
            return None
            
        # Create working Telegram direct links
        base_telegram_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}"
        direct_download = f"{base_telegram_url}/{telegram_file_path}"
        
        # For streaming, use the same URL (browsers will handle it appropriately)
        direct_stream = f"{base_telegram_url}/{telegram_file_path}"
        
        # Create shortened/custom-looking URLs for professional appearance
        # These still point to real Telegram URLs
        custom_download = f"https://tg-dl.herokuapp.com/d/{unique_id}?f={file_hash}"
        custom_stream = f"https://tg-stream.herokuapp.com/s/{unique_id}?f={file_hash}"
        
        return {
            'download': direct_download,  # Use real working links
            'stream': direct_stream,      # Use real working links
            'custom_download': custom_download,  # Custom appearance (would need proxy)
            'custom_stream': custom_stream,      # Custom appearance (would need proxy)
            'telegram_direct': direct_download,
            'hash': file_hash,
            'id': unique_id,
            'file_path': telegram_file_path
        }
        
    except Exception as e:
        logger.error(f"Error generating instant links: {e}")
        return None

# Get file from storage
def get_file_from_storage(file_id, provided_hash):
    """Retrieve file info from storage with hash verification"""
    try:
        if file_id not in file_storage:
            return None
            
        file_info = file_storage[file_id]
        
        # Verify hash for security
        if file_info['hash'] != provided_hash:
            logger.warning(f"Hash mismatch for file {file_id}")
            return None
            
        return file_info
        
    except Exception as e:
        logger.error(f"Error retrieving file from storage: {e}")
        return None


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
• 📥 **Instant Custom Links** - Optimized download URLs
• 🎬 **Streaming Links** - Direct media streaming
• 📱 **Telegram Direct** - Official Telegram links
• ☁️ **GoFile Upload** - Permanent cloud storage
• 🔄 **Resumable downloads**
• 📊 **Progress tracking**
• 🔒 **Secure hash verification**
• 📏 **Up to 2GB file size**

🚀 **How it works:**
1. Send me any file
2. Get instant custom download/stream links
3. Links are fast, resumable, and secure
4. Optional GoFile upload for permanent storage

🔧 **Commands:**
• `/start` - Show this welcome message
• `/info <id> <hash>` - Get file information
• `/cleanup` - Clean old files (maintenance)

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
        # Get Telegram file path first
        file_path = await get_telegram_file_path(file_obj.file_id)
        
        if not file_path:
            await status_msg.edit_text(
                f"❌ **Unable to get file path**\n\n"
                f"📁 **Type:** `{file_type}`\n"
                f"📄 **File:** `{file_name}`\n"
                f"📏 **Size:** `{file_size}`\n\n"
                f"🔄 **Falling back to GoFile upload...**"
            )
            await handle_gofile_upload(message, status_msg, file_info)
            return
        
        # Store file information and generate unique ID
        unique_id, file_hash = store_file_info(file_obj, file_name, file_info['size'], file_type)
        
        if unique_id and file_hash:
            # Generate instant links with real Telegram URLs
            links = generate_instant_links(unique_id, file_hash, file_name, file_path)
            
            if links:
                # Update status with success
                await status_msg.edit_text(
                    f"✅ **Links Generated Successfully!**\n\n"
                    f"📂 **File Name:** `{file_name}`\n"
                    f"📊 **File Size:** `{file_size}`\n\n"
                    f"📥 **Download:** [Direct Link]({links['download']})\n"
                    f"🎬 **Stream:** [Stream Link]({links['stream']})\n\n"
                    f"🔗 **File ID:** `{file_obj.file_id}`\n"
                    f"🆔 **Unique ID:** `{unique_id}`\n"
                    f"🔐 **Hash:** `{file_hash}`",
                    disable_web_page_preview=True
                )
                
                # Create inline keyboard with working links
                keyboard_buttons = []
                
                # Primary buttons with working URLs
                primary_row = [
                    InlineKeyboardButton("📥 Download", url=links['download']),
                    InlineKeyboardButton("🎬 Stream", url=links['stream'])
                ]
                keyboard_buttons.append(primary_row)
                
                # Additional options
                fallback_row = [
                    InlineKeyboardButton("📱 Telegram Link", url=links['telegram_direct']),
                    InlineKeyboardButton("☁️ GoFile Upload", callback_data=f"gf_{unique_id}")
                ]
                keyboard_buttons.append(fallback_row)
                
                # Info button
                info_row = [
                    InlineKeyboardButton("ℹ️ File Info", callback_data=f"info_{unique_id}_{file_hash}")
                ]
                keyboard_buttons.append(info_row)
                
                keyboard = InlineKeyboardMarkup(keyboard_buttons)
                
                # Send final message with options
                final_msg = f"""🚀 **Choose your preferred option:**

📥 **Direct Download** - Instant, resumable
🎬 **Direct Stream** - Stream in browser
📱 **Telegram Link** - Official Telegram URL
☁️ **GoFile Upload** - Permanent cloud storage

⚡ **File Details:**
🆔 ID: `{unique_id}`
🔐 Hash: `{file_hash}`
📏 Size: `{file_size}`
📁 Type: `{file_type}`

💡 **Note:** Links are direct from Telegram servers!
📢 **Join @YourChannel for updates!**"""

                await message.reply_text(final_msg, reply_markup=keyboard)
                
                # Store additional metadata for analytics
                logger.info(f"Generated working links for {file_type}: {file_name} (ID: {unique_id})")
                
            else:
                # Fallback to GoFile upload if link generation fails
                await status_msg.edit_text(
                    f"⚠️ **Link generation failed**\n\n"
                    f"📁 **Type:** `{file_type}`\n"
                    f"📄 **File:** `{file_name}`\n"
                    f"📏 **Size:** `{file_size}`\n\n"
                    f"🔄 **Falling back to GoFile upload...**"
                )
                await handle_gofile_upload(message, status_msg, file_info)
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
    
    if data.startswith("gf_"):
        # Extract unique_id from callback data
        unique_id = int(data.replace("gf_", ""))
        await callback_query.answer("Uploading to GoFile...")
        
        # Get file info from storage
        if unique_id not in file_storage:
            await callback_query.message.edit_text("❌ File information not found!")
            return
            
        stored_file_info = file_storage[unique_id]
        
        # Get the original message to reconstruct file info
        message = callback_query.message.reply_to_message
        if not message:
            await callback_query.message.edit_text("❌ Original file not found!")
            return
            
        # Get file info again from the original message
        file_info = get_file_info(message)
        if not file_info:
            await callback_query.message.edit_text("❌ Unable to process this file!")
            return
            
        # Start GoFile upload process
        await handle_gofile_upload(message, callback_query.message, file_info)
    
    elif data.startswith("info_"):
        # Handle file info request
        try:
            parts = data.replace("info_", "").split("_")
            if len(parts) >= 2:
                unique_id = int(parts[0])
                file_hash = parts[1]
                
                file_info = get_file_from_storage(unique_id, file_hash)
                
                if file_info:
                    info_text = f"""📋 **File Information:**

🆔 **ID:** `{unique_id}`
📄 **Name:** `{file_info['file_name']}`
📏 **Size:** `{format_file_size(file_info['file_size'])}`
📁 **Type:** `{file_info['file_type']}`
🔐 **Hash:** `{file_hash}`
📅 **Created:** `{time.ctime(file_info['created_at'])}`
🔗 **Telegram ID:** `{file_info['telegram_file_id']}`

💡 **Usage:** Send `/info {unique_id} {file_hash}` to get this info anytime!"""
                    
                    await callback_query.answer()
                    await callback_query.message.reply_text(info_text)
                else:
                    await callback_query.answer("❌ File not found!", show_alert=True)
            else:
                await callback_query.answer("❌ Invalid file info!", show_alert=True)
                
        except Exception as e:
            await callback_query.answer(f"❌ Error: {e}", show_alert=True)


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
            f"⏳ **Status:** Preparing upload..."
        )

        # Upload progress callback with more frequent updates
        last_update = [time.time()]
        async def update_progress(status):
            try:
                current_time = time.time()
                # Update every 3 seconds to avoid rate limits
                if current_time - last_update[0] >= 3:
                    await status_msg.edit_text(
                        f"📁 **Type:** `{file_type}`\n"
                        f"📄 **File:** `{file_name}`\n"
                        f"📏 **Size:** `{file_size}`\n"
                        f"✅ **Downloaded:** `{download_time:.1f}s`\n"
                        f"⏳ **Status:** {status}"
                    )
                    last_update[0] = current_time
            except Exception as e:
                logger.warning(f"Failed to update progress: {e}")

        start_upload_time = time.time()
        
        # Add timeout handling for the upload
        try:
            link = upload_to_gofile(file_path, lambda status: bot.loop.create_task(update_progress(status)))
        except Exception as e:
            logger.error(f"Upload function failed: {e}")
            link = None
            
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
                f"📁 **Type:** `{file_type}`\n"
                f"📄 **File:** `{file_name}`\n"
                f"📏 **Size:** `{file_size}`\n"
                f"⏰ **Upload time:** `{upload_time:.1f}s`\n\n"
                f"💡 **Try using the direct Telegram links instead!**"
            )
            
    except Exception as e:
        logger.error(f"Error in GoFile upload: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await status_msg.edit_text(
            f"❌ **Error during GoFile upload**\n\n"
            f"📁 **Type:** `{file_type}`\n"
            f"📄 **File:** `{file_name}`\n"
            f"❌ **Error:** `{str(e)[:100]}...`\n\n"
            f"💡 **Please try using the direct Telegram links!**"
        )


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


# Add a command to retrieve file info (for testing)
@bot.on_message(filters.command("info") & filters.private)
async def file_info_command(_, message: Message):
    """Get file information by ID"""
    try:
        command_parts = message.text.split()
        if len(command_parts) < 3:
            await message.reply_text(
                "📋 **Usage:** `/info <file_id> <hash>`\n\n"
                "🔍 **Example:** `/info 123456 abcd123456`\n\n"
                "💡 Get these values from the file generation message."
            )
            return
            
        file_id = int(command_parts[1])
        file_hash = command_parts[2]
        
        file_info = get_file_from_storage(file_id, file_hash)
        
        if file_info:
            await message.reply_text(
                f"📋 **File Information:**\n\n"
                f"🆔 **ID:** `{file_id}`\n"
                f"📄 **Name:** `{file_info['file_name']}`\n"
                f"📏 **Size:** `{format_file_size(file_info['file_size'])}`\n"
                f"📁 **Type:** `{file_info['file_type']}`\n"
                f"🔐 **Hash:** `{file_hash}`\n"
                f"📅 **Created:** `{time.ctime(file_info['created_at'])}`\n"
                f"🔗 **Telegram ID:** `{file_info['telegram_file_id']}`"
            )
        else:
            await message.reply_text("❌ **File not found or invalid hash!**")
            
    except ValueError:
        await message.reply_text("❌ **Invalid file ID! Must be a number.**")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** {e}")

# Add storage cleanup command (for maintenance)
@bot.on_message(filters.command("cleanup") & filters.private)
async def cleanup_command(_, message: Message):
    """Clean up old files from storage"""
    try:
        current_time = int(time.time())
        old_files = []
        
        for file_id, file_info in list(file_storage.items()):
            # Remove files older than 24 hours
            if current_time - file_info['created_at'] > 86400:
                old_files.append(file_id)
                del file_storage[file_id]
        
        await message.reply_text(
            f"🧹 **Cleanup Complete!**\n\n"
            f"🗑️ **Removed:** `{len(old_files)}` old files\n"
            f"📊 **Active files:** `{len(file_storage)}`\n"
            f"⏰ **Cleanup threshold:** 24 hours"
        )
        
    except Exception as e:
        await message.reply_text(f"❌ **Cleanup error:** {e}")


if __name__ == "__main__":
    logger.info("Starting GoFile Upload Bot on Railway...")
    logger.info("Bot is ready to handle file uploads!")
    try:
        bot.run()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        exit(1)
