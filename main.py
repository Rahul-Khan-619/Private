import asyncio
import random
import logging
import os
import re
import time
from telethon import TelegramClient, events
import config

# Configure logging
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)

# Initialize the client
client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)

# Queue for processing photos
photo_queue = None
MAX_QUEUE_SIZE = 4 # Increased since we have 2 workers

# Rate Limiting
user_last_seen = {}
RATE_LIMIT_SECONDS = 7200 # 2 Hours

# Album Handling
processed_grouped_ids = []
MAX_GROUPED_IDS = 100

# Load Promo Links
PROMO_LINKS = []
try:
    with open("promo_links.txt", "r") as f:
        PROMO_LINKS = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    print("Warning: promo_links.txt not found. Promo links will be empty.")

async def process_photo_with_bot(bot_username, source_chat_id, message):
    """Processes a single photo with the specified bot."""
    photo_path = None
    try:
        print(f"[{bot_username}] Processing photo from chat {source_chat_id}...")
        
        final_photo_msg = None
        
        # 1. Download Photo
        print(f"[{bot_username}] Downloading photo...")
        photo_path = await client.download_media(message, file=f"temp_input_{random.randint(1000,9999)}.jpg")
        
        async with client.conversation(bot_username, timeout=1200) as conv:
            # Send Photo
            print(f"[{bot_username}] Sending photo to bot...")
            await conv.send_file(photo_path)
            
            # 2. Wait for "Task submitted successfully!" or "Please Select the feature"
            print(f"[{bot_username}] Waiting for task submission confirmation or feature selection...")
            while True:
                response = await conv.get_response()
                if "task submitted successfully" in response.text.lower():
                    print(f"[{bot_username}] Task submitted successfully message received.")
                    break
                elif "please select the feature" in response.text.lower() and response.buttons:
                    print(f"[{bot_username}] Feature selection requested. Clicking 'Fast Image'...")
                    # Find button containing "Fast Image"
                    fast_image_btn = None
                    for row in response.buttons:
                        for btn in row:
                            if "fast image" in btn.text.lower():
                                fast_image_btn = btn
                                break
                        if fast_image_btn:
                            break
                    
                    if fast_image_btn:
                        await asyncio.sleep(random.uniform(2, 4))
                        await fast_image_btn.click()
                        
                        # Wait for "Send an Image" message
                        print(f"[{bot_username}] Waiting for 'Send an Image' prompt...")
                        while True:
                            prompt_resp = await conv.get_response()
                            if "send an image" in prompt_resp.text.lower() or "send a photo" in prompt_resp.text.lower():
                                print(f"[{bot_username}] 'Send an Image' prompt received. Sending photo again...")
                                await conv.send_file(photo_path)
                                break
                            else:
                                print(f"[{bot_username}] Ignored while waiting for prompt: {prompt_resp.text[:20]}...")
                    else:
                        print(f"[{bot_username}] Warning: 'Fast Image' button not found.")
                elif "haven't sent face photo" in response.text.lower() or "face photo has expired" in response.text.lower() or "no face detected" in response.text.lower():
                    print(f"[{bot_username}] Error: No face detected.")
                    await client.send_message(source_chat_id, "Error: Please send a proper full-face close-up photo.", reply_to=message.id)
                    return # Abort
                else:
                    print(f"[{bot_username}] Ignored: {response.text[:20]}...")

            # 3. Wait for Processed Photo
            print(f"[{bot_username}] Waiting for processed photo...")
            while True:
                response = await conv.get_response()
                if response.photo:
                    final_photo_msg = response
                    print(f"[{bot_username}] Processed photo received.")
                    break
                else:
                    print(f"[{bot_username}] Ignored: {response.text[:20]}...")

            # 4. Wait for trailing message containing "success" (so that done can ignore this)
            print(f"[{bot_username}] Waiting for trailing 'success' message...")
            while True:
                response = await conv.get_response()
                if "success" in response.text.lower():
                    print(f"[{bot_username}] Trailing 'success' message received and ignored.")
                    break
                else:
                    print(f"[{bot_username}] Ignored: {response.text[:20]}...")

        # --- STEP 2: Generate Link ---
        if final_photo_msg:
            # Send copy to Log Channel if configured
            if hasattr(config, 'LOG_CHANNEL') and config.LOG_CHANNEL:
                try:
                    log_channel = config.LOG_CHANNEL
                    if isinstance(log_channel, str):
                        log_channel = log_channel.strip()
                        if log_channel.startswith('-100') and log_channel[4:].isdigit():
                            log_channel = int(log_channel)
                        elif log_channel.isdigit():
                            log_channel = int(f"-100{log_channel}")
                        elif log_channel.lstrip('-').isdigit():
                            log_channel = int(log_channel)
                    elif isinstance(log_channel, int):
                        if log_channel > 0:
                            log_channel = int(f"-100{log_channel}")
                    
                    print(f"[{bot_username}] Sending copy to Log Channel {log_channel}...")
                    await client.send_message(log_channel, final_photo_msg)
                except Exception as log_err:
                    print(f"[{bot_username}] Error sending to Log Channel: {log_err}")

            print(f"[{bot_username}] Forwarding to Link Gen Bot...")
            async with client.conversation(config.FILE_STORE_BOT_USERNAME, timeout=120) as conv_store:
                forwarded_msg = await client.forward_messages(config.FILE_STORE_BOT_USERNAME, final_photo_msg)
                await conv_store.send_message('/genlink', reply_to=forwarded_msg.id)
                
                print(f"[{bot_username}] Waiting for link...")
                generated_link = None
                
                try:
                    response = await conv_store.get_response()
                    if "Here is your link" in response.text:
                        generated_link = response.text
                    else:
                        event = await conv_store.wait_event(events.MessageEdited(chats=config.FILE_STORE_BOT_USERNAME), timeout=60)
                        if "Here is your link" in event.message.text:
                            generated_link = event.message.text
                except asyncio.TimeoutError:
                    print(f"[{bot_username}] Timeout waiting for link.")

                if generated_link:
                    urls = re.findall(r'(https?://\S+)', generated_link)
                    if urls:
                        final_url = urls[0]
                        print(f"[{bot_username}] Link: {final_url}")
                        
                        promo_link = random.choice(PROMO_LINKS) if PROMO_LINKS else "https://t.me/Mr_Super_Edits_robot"
                        # caption = f"Your Edited Photo Result is here 👉 {final_url}\n👇👇👇👇\n{promo_link} \n 👆👆 Do You want to Do a Video Edit Like This ?\nMsg to @Mr_Super_Editor"
                        caption = f"Your Edited Photo Result is here 👉 {final_url} \n\n Dm to @Mr_Super_Man And Get Photo to Video Edit Bot at less Price \n msg to https://t.me/Mr_Super_man?text=I%20Need%20Private%20P0rn%20Video%20Edit%20bot%20  Now "
                        
                        await client.send_message(source_chat_id, caption, reply_to=message.id)
                        print(f"[{bot_username}] Done!")

    except Exception as e:
        print(f"[{bot_username}] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if photo_path and os.path.exists(photo_path):
            try:
                os.remove(photo_path)
            except Exception as e:
                print(f"Error removing temp file {photo_path}: {e}")

async def worker(bot_username):
    """Worker that consumes from queue and uses a specific bot."""
    global photo_queue
    if photo_queue is None:
        photo_queue = asyncio.Queue()
        
    print(f"Worker for {bot_username} started.")
    while True:
        source_chat_id, message = await photo_queue.get()
        await process_photo_with_bot(bot_username, source_chat_id, message)
        photo_queue.task_done()

def get_code():
    print("\nIMPORTANT: Check your Telegram app for the login code.")
    code = input("Enter the OTP code (spaces will be removed): ")
    return code.replace(" ", "")

def get_password():
    return input("Enter your 2FA password: ")

def get_phone():
    return input("Enter your phone number (e.g., +1234567890): ")

@client.on(events.NewMessage)
async def handler(event):
    global photo_queue, processed_grouped_ids
    if photo_queue is None:
        photo_queue = asyncio.Queue()

    chat = await event.get_chat()
    sender = await event.get_sender()
    user_id = sender.id if sender else 0
    
    if event.is_group and event.photo:
        if config.MAIN_BOT_GROUPS and chat.id not in config.MAIN_BOT_GROUPS:
            return

        # Album Handling: only process the first photo of an album
        if event.grouped_id:
            if event.grouped_id in processed_grouped_ids:
                print(f"Album photo with grouped_id {event.grouped_id} already processed/ignored.")
                return
            processed_grouped_ids.append(event.grouped_id)
            if len(processed_grouped_ids) > MAX_GROUPED_IDS:
                processed_grouped_ids.pop(0)

        print(f"\n[+] Photo received in group: {chat.title} (ID: {chat.id}) from User {user_id}")
        
        # Rate Limit
        current_time = time.time()
        if user_id in user_last_seen:
            elapsed = current_time - user_last_seen[user_id]
            if elapsed < RATE_LIMIT_SECONDS:
                print(f"Rate Limit: User {user_id} ignored.")
                return

        # Spam Check
        print("Waiting 5s for spam check...")
        await asyncio.sleep(5)
        try:
            msg = await client.get_messages(chat.id, ids=event.id)
            if not msg:
                print("Message deleted. Ignoring.")
                return
        except:
            return

        user_last_seen[user_id] = current_time

        if photo_queue.qsize() < MAX_QUEUE_SIZE:
            print("Adding to queue...")
            photo_queue.put_nowait((chat.id, event.message))
        else:
            print("Queue full. Ignoring.")

if __name__ == '__main__':
    print("--------------------------------------------------")
    print("Starting Main Bot (Dual Worker)...")
    print("--------------------------------------------------")
    
    client.start(
        phone=config.PHONE_NUMBER if config.PHONE_NUMBER else get_phone,
        code_callback=get_code,
        password=get_password
    )
    
    print("\n[SUCCESS] Logged in successfully!")
    print(f"Monitoring Group ID: {config.MAIN_BOT_GROUPS}")
    
    # Start two workers: one for Primary bot, one for Backup bot
    client.loop.create_task(worker(config.TARGET_BOT_USERNAME))
    client.loop.create_task(worker(config.BACKUP_BOT_USERNAME))
    
    client.run_until_disconnected()
