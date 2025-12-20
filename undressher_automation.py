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
MAX_QUEUE_SIZE = 2

# Rate Limiting
user_last_seen = {}
RATE_LIMIT_SECONDS = 3600 # 1 Hour

# Load Promo Links
PROMO_LINKS = []
try:
    with open("promo_links.txt", "r") as f:
        PROMO_LINKS = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    print("Warning: promo_links.txt not found. Promo links will be empty.")

async def process_queue():
    """Worker function to process photos from the queue sequentially."""
    global photo_queue
    if photo_queue is None:
        photo_queue = asyncio.Queue()

    print("Worker started. Waiting for photos...")
    while True:
        # Get a "work item" from the queue
        source_chat_id, message = await photo_queue.get()
        
        try:
            print(f"Processing photo from chat {source_chat_id}...")
            
            # --- STEP 1: Process with UndressHerBot ---
            final_photo_msg = None
            
            async with client.conversation(config.UNDRESSHER_BOT_USERNAME, timeout=1000) as conv:
                
                # 1. Download and Send Photo
                print("Downloading photo...")
                photo_path = await client.download_media(message, file="temp_input.jpg")
                
                print(f"Sending photo to {config.UNDRESSHER_BOT_USERNAME}...")
                await conv.send_file(photo_path)
                
                if os.path.exists(photo_path):
                    os.remove(photo_path)

                # 2. Wait for Menu with Buttons
                print("Waiting for Menu...")
                menu_msg = None
                while True:
                    response = await conv.get_response()
                    if response.buttons:
                        menu_msg = response
                        break
                    else:
                        print(f"Ignored message: {response.text[:20]}... (Waiting for Menu)")
                
                # Select Random Button (Exclude "VIP")
                print("Received Menu. Selecting random button (excluding VIP)...")
                valid_buttons = []
                
                if menu_msg.buttons:
                    for row in menu_msg.buttons:
                        for btn in row:
                            if "VIP" not in btn.text:
                                valid_buttons.append(btn)
                
                if valid_buttons:
                    selected = random.choice(valid_buttons)
                    print(f"Clicking: {selected.text}")
                    await asyncio.sleep(random.uniform(2, 4))
                    await selected.click()
                else:
                    print("No valid buttons found!")
                    continue

                # 3. Wait for "Request accepted"
                print("Waiting for 'Request accepted'...")
                while True:
                    response = await conv.get_response()
                    if "Request accepted" in response.text:
                        break
                    elif "You haven't sent face photo" in response.text: # Handle potential error
                         print("Error: No face detected.")
                         await client.send_message(source_chat_id, "Error: Please send a proper full-face close-up photo.", reply_to=message.id)
                         raise Exception("No face detected")
                    else:
                         print(f"Ignored message: {response.text[:20]}...")

                # 4. Wait for Final Result (Photo)
                print("Waiting for Final Result (Photo)... This may take up to 10 mins.")
                while True:
                    response = await conv.get_response()
                    if response.photo:
                        final_photo_msg = response
                        break
                    elif "done" in response.text.lower():
                        # Sometimes "done" comes after or before, just ignore text messages unless they are errors
                        pass
                    else:
                        print(f"Ignored message: {response.text[:20]}... (Waiting for Photo)")

                print("Received Final Result.")

            # --- STEP 2: Generate Link with File Store Bot ---
            print(f"Starting interaction with {config.FILE_STORE_BOT_USERNAME}...")
            generated_link = None
            
            async with client.conversation(config.FILE_STORE_BOT_USERNAME, timeout=120) as conv_store:
                # Forward the processed photo directly
                print("Forwarding processed photo to File Store Bot...")
                
                forwarded_msg = await client.forward_messages(config.FILE_STORE_BOT_USERNAME, final_photo_msg)
                
                print("Sending /genlink command...")
                await conv_store.send_message('/genlink', reply_to=forwarded_msg.id)
                
                # Wait for response "Here is your link:"
                print("Waiting for link generation...")
                
                response = await conv_store.get_response()
                
                if "Here is your link" in response.text:
                    generated_link = response.text
                else:
                    # Wait for edit
                    print("Waiting for edit...")
                    try:
                        event = await conv_store.wait_event(events.MessageEdited(chats=config.FILE_STORE_BOT_USERNAME), timeout=60)
                        if "Here is your link" in event.message.text:
                            generated_link = event.message.text
                    except asyncio.TimeoutError:
                        print("Timeout waiting for link generation.")
            
            # Extract URL from text
            final_url = None
            if generated_link:
                urls = re.findall(r'(https?://\S+)', generated_link)
                if urls:
                    final_url = urls[0]
            
            if final_url:
                print(f"Link generated: {final_url}")
                print("Sending reply to source group...")
                
                # Pick random promo link
                promo_link = random.choice(PROMO_LINKS) if PROMO_LINKS else "https://t.me/Mr_Super_Edits_robot"
                
                caption = f"Your Edited Photo Result is here 👉 {final_url}\n👇👇👇👇\n{promo_link} \n 👆👆 Do You want to Do a Video Edit Like This ?\nMsg to @Mr_Super_Editor"
                
                await client.send_message(source_chat_id, caption, reply_to=message.id)
                print("Process Complete!")
            else:
                print("Failed to extract link.")

        except asyncio.TimeoutError:
            print("Timeout occurred.")
        except Exception as e:
            print(f"Error processing photo: {e}")
            import traceback
            traceback.print_exc()
        finally:
            photo_queue.task_done()

def get_code():
    """Callback to get the code and remove spaces."""
    print("\nIMPORTANT: Check your Telegram app for the login code.")
    code = input("Enter the OTP code (spaces will be removed): ")
    return code.replace(" ", "")

def get_password():
    """Callback to get 2FA password."""
    return input("Enter your 2FA password: ")

def get_phone():
    """Callback to get phone number."""
    return input("Enter your phone number (e.g., +1234567890): ")

@client.on(events.NewMessage)
async def handler(event):
    global photo_queue
    if photo_queue is None:
        photo_queue = asyncio.Queue()

    chat = await event.get_chat()
    sender = await event.get_sender()
    user_id = sender.id if sender else 0
    
    # Listen for Photos in Groups
    if event.is_group and event.photo:
        # Filter by Group IDs
        if config.UNDRESSHER_BOT_GROUPS and chat.id not in config.UNDRESSHER_BOT_GROUPS:
            return

        print(f"\n[+] Photo received in group: {chat.title} (ID: {chat.id}) from User {user_id}")
        
        if not config.UNDRESSHER_BOT_GROUPS:
            print(f"NOTE: To restrict to this group, add {chat.id} to UNDRESSHER_BOT_GROUPS in config.py")

        # 1. Rate Limit Check
        current_time = time.time()
        if user_id in user_last_seen:
            elapsed = current_time - user_last_seen[user_id]
            if elapsed < RATE_LIMIT_SECONDS:
                print(f"Rate Limit: User {user_id} ignored (Wait {int(RATE_LIMIT_SECONDS - elapsed)}s)")
                return

        # 2. Spam Check (Delay & Existence)
        print("Waiting 5s to check for spam deletion...")
        await asyncio.sleep(5)
        
        try:
            # Check if message still exists
            msg = await client.get_messages(chat.id, ids=event.id)
            if not msg:
                print("Message was deleted (spam?). Ignoring.")
                return
        except Exception:
            print("Message inaccessible. Ignoring.")
            return

        # Update timestamp only if we proceed
        user_last_seen[user_id] = current_time

        # Queue Logic
        if photo_queue.qsize() < MAX_QUEUE_SIZE:
            print("Adding to queue...")
            photo_queue.put_nowait((chat.id, event.message))
        else:
            print("Queue full (>= 2 items). Ignoring.")

if __name__ == '__main__':
    print("--------------------------------------------------")
    print("Starting UndressHer Automation Bot...")
    print("Please follow the prompts to log in.")
    print("--------------------------------------------------")
    
    client.start(
        phone=config.PHONE_NUMBER if config.PHONE_NUMBER else get_phone,
        code_callback=get_code,
        password=get_password
    )
    
    print("\n[SUCCESS] Logged in successfully!")
    print(f"Monitoring Group ID: {config.UNDRESSHER_BOT_GROUPS if config.UNDRESSHER_BOT_GROUPS else 'ALL GROUPS'}")
    
    client.loop.create_task(process_queue())
    
    client.run_until_disconnected()
