import os
import logging
import requests
import time
import tempfile
from pyrogram import Client, filters
from pyrogram.types import Message
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
        
        with open(file_path, "rb") as f:
            files = {'file': (os.path.basename(file_path), f)}
            data = {'token': ''}  # Empty token for guest uploads
            
            if progress_callback:
                progress_callback("📤 Uploading to GoFile...")
            
            response = requests.post(upload_url, files=files, data=data, timeout=300)

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
🚀 **Welcome to GoFile Upload Bot!**

📁 **How to use:**
• Send me any document/file
• I'll upload it to GoFile and give you a download link

✨ **Features:**
• Fast uploads to GoFile
• Progress tracking
• Automatic file cleanup
• Private uploads only

🔒 **Privacy:** Your files are uploaded anonymously to GoFile

Just send me a file to get started! 📎
    """
    await message.reply_text(welcome_text)


# Bot handler for document uploads
@bot.on_message(filters.document & filters.private)
async def handle_doc(_, message: Message):
    user = message.from_user
    doc = message.document
    
    # Show file info
    file_size = format_file_size(doc.file_size)
    file_name = doc.file_name or "Unknown"
    
    # Check file size limit (Railway has memory limits)
    if doc.file_size > 100 * 1024 * 1024:  # 100MB limit
        await message.reply_text(
            f"❌ **File too large!**\n\n"
            f"📏 **File size:** `{file_size}`\n"
            f"🚫 **Maximum allowed:** `100 MB`\n\n"
            f"Please send a smaller file."
        )
        return
    
    status_msg = await message.reply_text(
        f"📄 **File:** `{file_name}`\n"
        f"📏 **Size:** `{file_size}`\n"
        f"⏳ **Status:** Downloading..."
    )

    try:
        start_time = time.time()
        # Use temporary directory for downloads
        file_path = await message.download(
            file_name=f"{DOWNLOADS_DIR}/{doc.file_unique_id}_{doc.file_name}",
            progress=lambda current, total: None
        )
        download_time = time.time() - start_time
        
        logger.info(f"Downloaded to {file_path} in {download_time:.2f}s")

        # Update status for upload
        await status_msg.edit_text(
            f"📄 **File:** `{file_name}`\n"
            f"📏 **Size:** `{file_size}`\n"
            f"✅ **Downloaded:** `{download_time:.1f}s`\n"
            f"⏳ **Status:** Uploading to GoFile..."
        )

        # Upload progress callback
        async def update_progress(status):
            try:
                await status_msg.edit_text(
                    f"📄 **File:** `{file_name}`\n"
                    f"📏 **Size:** `{file_size}`\n"
                    f"✅ **Downloaded:** `{download_time:.1f}s`\n"
                    f"⏳ **Status:** {status}"
                )
            except:
                pass  # Ignore edit errors

        start_upload_time = time.time()
        link = upload_to_gofile(file_path, lambda status: bot.loop.create_task(update_progress(status)))
        upload_time = time.time() - start_upload_time

        if link:
            await status_msg.edit_text(
                f"📄 **File:** `{file_name}`\n"
                f"📏 **Size:** `{file_size}`\n"
                f"✅ **Downloaded:** `{download_time:.1f}s`\n"
                f"✅ **Uploaded:** `{upload_time:.1f}s`\n"
                f"🔗 **Status:** Upload Complete!"
            )
            
            await message.reply_text(
                f"✅ **Upload Successful!**\n\n"
                f"🔗 [**Download Link**]({link})\n\n"
                f"⚡ Total time: `{download_time + upload_time:.1f}s`",
                disable_web_page_preview=True
            )
        else:
            await status_msg.edit_text(
                f"📄 **File:** `{file_name}`\n"
                f"📏 **Size:** `{file_size}`\n"
                f"✅ **Downloaded:** `{download_time:.1f}s`\n"
                f"❌ **Status:** Upload Failed"
            )
            await message.reply_text("❌ Failed to upload to GoFile. Please try again.")

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(
            f"📄 **File:** `{file_name}`\n"
            f"📏 **Size:** `{file_size}`\n"
            f"❌ **Status:** Error occurred"
        )
        await message.reply_text(f"❌ Error: {e}")


# Handler for non-document files
@bot.on_message(filters.private & ~filters.command("start") & ~filters.document)
async def handle_other(_, message: Message):
    await message.reply_text(
        "❌ **Unsupported file type!**\n\n"
        "📎 Please send a **document/file** for upload.\n"
        "🚫 Photos, videos, and other media are not supported yet.\n\n"
        "💡 **Tip:** Use 'Send as File' option for photos/videos."
    )


if __name__ == "__main__":
    logger.info("Starting GoFile Upload Bot on Railway...")
    logger.info("Bot is ready to handle file uploads!")
    try:
        bot.run()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        exit(1)
