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

# Load Promo Links
PROMO_LINKS = []
try:
    with open("promo_links.txt", "r") as f:
        PROMO_LINKS = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    print("Warning: promo_links.txt not found. Promo links will be empty.")

async def process_photo_with_bot(bot_username, source_chat_id, message):
    """Processes a single photo with the specified bot."""
    try:
        print(f"[{bot_username}] Processing photo from chat {source_chat_id}...")
        
        final_photo_msg = None
        
        async with client.conversation(bot_username, timeout=1200) as conv:
            # 1. Download and Send Photo
            print(f"[{bot_username}] Downloading photo...")
            photo_path = await client.download_media(message, file=f"temp_input_{random.randint(1000,9999)}.jpg")
            
            print(f"[{bot_username}] Sending photo to bot...")
            await conv.send_file(photo_path)
            
            if os.path.exists(photo_path):
                os.remove(photo_path)

            # 2. Wait for Style Menu
            print(f"[{bot_username}] Waiting for Style Menu...")
            style_msg = None
            while True:
                response = await conv.get_response()
                if response.buttons and ("undress type" in response.text.lower() or "select" in response.text.lower()):
                    style_msg = response
                    break
                else:
                    print(f"[{bot_username}] Ignored: {response.text[:20]}...")

            # Select Random Style
            while True:
                print(f"[{bot_username}] Selecting random style...")
                valid_buttons = []
                if style_msg.buttons:
                    for row in style_msg.buttons:
                        for btn in row:
                            if btn.text not in ["1/2", "2/2", "Cancel", "Back"]:
                                valid_buttons.append(btn)
                
                if not valid_buttons:
                    print(f"[{bot_username}] No valid buttons. Retrying...")
                    await asyncio.sleep(2)
                    continue

                selected = random.choice(valid_buttons)
                print(f"[{bot_username}] Clicking: {selected.text}")
                await asyncio.sleep(random.uniform(2, 4))
                await selected.click()

                if selected.text in ["▶️", "◀️"]:
                    print(f"[{bot_username}] Navigation clicked. Waiting...")
                    try:
                        event = await conv.wait_event(events.MessageEdited(chats=bot_username), timeout=30)
                        style_msg = event.message
                        continue
                    except asyncio.TimeoutError:
                        style_msg = await client.get_messages(bot_username, ids=style_msg.id)
                        continue
                else:
                    break
            
            # 3. Check for Confirm or Error
            print(f"[{bot_username}] Waiting for Confirm or Error...")
            confirm_msg = None
            
            while True:
                response = await conv.get_response()
                
                # Error Check
                if "You haven't sent face photo" in response.text or "face photo has expired" in response.text:
                    print(f"[{bot_username}] Error: No face detected.")
                    if response.buttons:
                        for row in response.buttons:
                            for btn in row:
                                if "Cancel" in btn.text:
                                    await btn.click()
                    await client.send_message(source_chat_id, "Error: Please send a proper full-face close-up photo.", reply_to=message.id)
                    return # Abort

                # Check for Confirm Button
                has_confirm = False
                if response.buttons:
                    for row in response.buttons:
                        for btn in row:
                            if "Confirm" in btn.text:
                                has_confirm = True
                                break
                
                if has_confirm:
                    confirm_msg = response
                    break
                else:
                    print(f"[{bot_username}] Ignored: {response.text[:20]}...")

            # Click Confirm
            print(f"[{bot_username}] Clicking Confirm...")
            confirm_btn = None
            for row in confirm_msg.buttons:
                for btn in row:
                    if "Confirm" in btn.text:
                        confirm_btn = btn
                        break
            
            if confirm_btn:
                await asyncio.sleep(random.uniform(2, 4))
                await confirm_btn.click()

            # 4. Wait for "Task submitted" and then Final Result
            print(f"[{bot_username}] Waiting for Final Result (upto 15m)...")
            while True:
                response = await conv.get_response()
                if "Task submitted successfully" in response.text:
                    print(f"[{bot_username}] Task submitted. Waiting for photo...")
                    continue
                
                if response.photo:
                    final_photo_msg = response
                    break
                else:
                    print(f"[{bot_username}] Ignored: {response.text[:20]}...")

        # --- STEP 2: Generate Link ---
        if final_photo_msg:
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
                        caption = f"Your Edited Photo Result is here 👉 {final_url} \n \n Dm to @Mr_Super_Human And Get Photo to Video Edit Bot at less Price \n \n msg to @Mr_Super_Human Now "
                        
                        await client.send_message(source_chat_id, caption, reply_to=message.id)
                        print(f"[{bot_username}] Done!")

    except Exception as e:
        print(f"[{bot_username}] Error: {e}")
        import traceback
        traceback.print_exc()

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
    global photo_queue
    if photo_queue is None:
        photo_queue = asyncio.Queue()

    chat = await event.get_chat()
    sender = await event.get_sender()
    user_id = sender.id if sender else 0
    
    if event.is_group and event.photo:
        if config.MAIN_BOT_GROUPS and chat.id not in config.MAIN_BOT_GROUPS:
            return

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

