import os
import json
import re
import traceback
import asyncio
from tqdm import tqdm
from telethon.tl import types
from telethon.utils import get_display_name

from telegram_api import init_telegram_client

client = init_telegram_client('backup')

VIDEO_TIMEOUT = 60 * 15
MEDIA_TIMEOUT = 60 * 2
DOWNLOAD_RETRIES = 2

# Getting Path
backup_path = 'dialogs'
os.makedirs(backup_path, exist_ok=True)


# Clearing dialog name from inadmissible symbols
def sanitize_folder_name(name):
     return re.sub(r'[\\/*?:"<>|]', '_', str(name))


# Creating folders for dialogs and chats
async def create_chat_folder(dialog):
    if isinstance(dialog.entity, (types.User, types.Chat)):
        clean_name = sanitize_folder_name(dialog.name)
        folder_name = f'{clean_name}_ID_{dialog.id}'
        chat_folder = os.path.join(backup_path, folder_name)
        try:
            os.makedirs(chat_folder, exist_ok=True)
            print(f"The folder was created for: {dialog.name} -> {folder_name}")
            return chat_folder
        except Exception as e:
            print(f"Error for: {dialog.name}: {str(e)}")

    return None

# Getting media data, including stickers
def get_media_info(media):
    if isinstance(media, types.MessageMediaDocument) and media.document:
        for attr in media.document.attributes:
            # For stickers
            if isinstance(attr, types.DocumentAttributeHasStickers):
                return {
                    "type": "sticker",
                    "emoji": attr.alt,
                    "sticker_id": media.document.id,
                    "pack_id": getattr(media.document, 'stickerset', None)
                }
    
    # For photo
    if isinstance(media, types.MessageMediaPhoto):
        file_size = 0
        if media.photo and media.photo.sizes:
            largest_size = media.photo.sizes[-1]
            if hasattr(largest_size, 'size'):
                file_size = largest_size.size
            elif hasattr(largest_size, 'sizes') and largest_size.sizes:
                file_size = sum(largest_size.sizes)
                
        return {
            "type": "photo",
            "size": file_size
        }
    
    # For Docs and Video
    if isinstance(media, types.MessageMediaDocument) and media.document:
        file_name = None
        is_video = False
        for attr in media.document.attributes:
            if isinstance(attr, types.DocumentAttributeFilename):
                file_name = attr.file_name
            if isinstance(attr, types.DocumentAttributeVideo):
                is_video = True

        media_type = "video" if is_video else "document"

        return {
            "type": media_type,
            "file_name": file_name,
            "mime_type": media.document.mime_type,
            "size": media.document.size
        }
    
    return {"type": "unknown"}

# Choosing whether to save media
media_allowed = False

while True:
    media_check = input('Do you want to save the media? [y/n]\n>>> ')
    if media_check.lower() == 'y':
        media_allowed = True
        break
    elif media_check.lower() == 'n':
        media_allowed = False
        break
    else:
        print("Type 'y' or 'n' ")

# Choosing limit of messages to save
message_limit = 0

while True:
    limit_input_check = input('Do you want to limit amount of messages to save? [y/n]\n>>> ')
    if limit_input_check == 'n':
        message_limit = 0
        break
    else:
        limit_input = int(input('How many messages do you want to save?\n>>> '))
        message_limit = limit_input
        break

# Getting chat name
def get_chat_name(chat_entity):
    if isinstance(chat_entity, types.User):
        return chat_entity.first_name or chat_entity.username or "Unknown User"
    elif isinstance(chat_entity, types.Chat):
        return chat_entity.title
    return "Unknown Chat"

# Cache for sender names
sender_cache = {}

# Getting info about sender
async def get_sender_info(sender_id):
    if sender_id in sender_cache:
        return sender_cache[sender_id]
    
    try:
        sender_entity = await client.get_entity(sender_id)

        if isinstance(sender_entity, types.User):
            sender_info = {
                "id": sender_id,
                "name": get_display_name(sender_entity),
                "username": sender_entity.username,
                "phone": sender_entity.phone
            }
        elif isinstance(sender_entity, types.Chat):
            sender_info = {
                "id": sender_id,
                "name": sender_entity.title,
                "type": "Channel" if isinstance(sender_entity, types.Channel) else "Group"
            }
        else:
            sender_info = {"id": sender_id, "name": "Unknown"}
        
        sender_cache[sender_id] = sender_info
        return sender_info
        
    except Exception as e:
        print(f"Error receiving sender information {sender_id}: {str(e)}")
        return {"id": sender_id, "name": "Unknown"}


# Download func with retries and progress bar
async def download_with_retry(message, file_path, media_type, max_retries=DOWNLOAD_RETRIES):
    timeout = VIDEO_TIMEOUT if media_type == "video" else MEDIA_TIMEOUT
    
    for attempt in range(max_retries):
        pbar = None
        download_task = None
        try:
            # Getting media size
            file_size = 0
            if media_type == "video" and isinstance(message.media, types.MessageMediaDocument):
                file_size = message.media.document.size
            elif media_type == "document" and isinstance(message.media, types.MessageMediaDocument):
                file_size = message.media.document.size
            elif media_type == "photo" and isinstance(message.media, types.MessageMediaPhoto):
                if message.media.photo and message.media.photo.sizes:
                    largest_size = message.media.photo.sizes[-1]
                    if hasattr(largest_size, 'size'):
                        file_size = largest_size.size
                    elif hasattr(largest_size, 'sizes') and largest_size.sizes:
                        file_size = sum(largest_size.sizes)
            
            # Creating progress bar
            if file_size > 0:
                pbar = tqdm(
                    total=file_size,
                    unit='B',
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=f"⏬ {os.path.basename(file_path)}",
                    leave=False
                )
                
                def update_progress(current, total):
                    if pbar.total != total:
                        pbar.total = total
                    pbar.update(current - pbar.n)
                
                progress_callback = update_progress
            else:
                progress_callback = None

            # Creating task for download
            download_task = asyncio.create_task(
                message.download_media(file=file_path, progress_callback=progress_callback)
            )

            await asyncio.wait_for(download_task, timeout=timeout)
            
            if pbar:
                pbar.close()
            return True
            
        except asyncio.TimeoutError:
            print(f"\n⌛ Timeout downloading ({timeout} sec), attempt {attempt+1}/{max_retries}")
            if download_task and not download_task.done():
                download_task.cancel()
                try:
                    await download_task
                except asyncio.CancelledError:
                    pass
            
            if pbar:
                pbar.close()
            
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
                    
        except Exception as e:
            print(f"\n⚠️ Download error: {str(e)}")
            traceback.print_exc()
            if pbar:
                pbar.close()
            break
    
    return False


# Saving all messages in json file
async def save_messages(chat_entity, folder_path):
    try:
        chat_name = get_chat_name(chat_entity)
        print(f"\n📂 Starting to save messages for: {chat_name}")
        
        # Creating folder for media
        media_path = None
        if media_allowed:
            media_path = os.path.join(folder_path, 'media')
            os.makedirs(media_path, exist_ok=True)
            print(f'📁 Media folder: {media_path}')

        messages = []

        # Getting messages
        async for message in client.iter_messages(chat_entity, limit=message_limit):
            sender_info = None
            if message.sender_id:
                sender_info = await get_sender_info(message.sender_id)

            msg_data = {
                "id": message.id,
                "date": message.date.isoformat() if message.date else None,
                "sender_info": sender_info,
                "text": message.text,
                "out": message.out
            }
            
            # Getting sticker info
            if message.media:
                media_info = get_media_info(message.media)

                if media_info.get("type") == "sticker":
                    emoji = media_info.get("emoji", "")
                    if msg_data["text"]:
                        msg_data["text"] += f" [Sticker: {emoji}]"
                    else:
                        msg_data["text"] = f"[Sticker: {emoji}]"

                # Saving media if user choose to save it
                if media_allowed and media_path:
                    try:
                        extension = ".bin"
                        
                        if media_info["type"] == "photo":
                            extension = ".jpg"
                        elif media_info["type"] == "sticker":
                            extension = ".webp"
                        elif media_info.get("file_name"):
                            extension = os.path.splitext(media_info["file_name"])[1]
                        elif media_info["type"] == "video":
                            extension = ".mp4"
                        
                        file_name = f"media_{message.id}{extension}"
                        file_path = os.path.join(media_path, file_name)
                        
                        success = await download_with_retry(
                            message,
                            file_path,
                            media_info.get("type"),
                            DOWNLOAD_RETRIES
                        )
                        
                        if success:
                            media_info["file"] = file_name
                            media_info["path"] = f"media/{file_name}"
                            print(f"\n✅ Downloaded: {file_name} ({media_info['type']})")
                        else:
                            media_info["error"] = "download_failed"
                            print(f"\n❌ Download failed: {file_name}")
                        
                    except Exception as e:
                        print(f"\n⚠️ Error downloading media: {str(e)}")
                        traceback.print_exc()
                        media_info["error"] = str(e)
                
                msg_data["media"] = media_info
            
            messages.append(msg_data)
            
            if len(messages) % 10 == 0:
                print(f'\n📊 Messages processed: {len(messages)}')
        
        file_path = os.path.join(folder_path, 'messages.json')
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ Successfully saved {len(messages)} messages in {file_path}")
        return True
        
    except Exception as e:
        print(f"\n❌ Error saving messages: {str(e)}")
        traceback.print_exc()
        return False


# Starting all
async def main():
    print("Starting backup...")
    
    async for dialog in client.iter_dialogs():
        chat_name = dialog.name
        print(f"Dialog processing: {chat_name}")
        
        folder_path = await create_chat_folder(dialog)
        
        if folder_path:
            print(f"Folder path: {folder_path}")
            
            success = await save_messages(dialog.entity, folder_path)
            
            if success:
                print(f"Messages for {chat_name} are successfully saved")
            else:
                print(f"Couldn't save messages for {chat_name}")
        else:
            print(f"Couldn't create a folder for {chat_name}, skipping...")

    print("\nBackup completed!")

with client:
    client.loop.run_until_complete(main())