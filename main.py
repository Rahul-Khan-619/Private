import asyncio
import random
import logging
import os
import re
from telethon import TelegramClient, events
import config

import time

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
            
            # --- STEP 1: Process with FreeUndreBot ---
            final_photo_path = "temp_output.jpg"
            
            async with client.conversation(config.TARGET_BOT_USERNAME, timeout=1000) as conv:
                
                # 1. Download and Send Photo
                print("Downloading photo...")
                photo_path = await client.download_media(message, file="temp_input.jpg")
                
                print("Sending photo to bot...")
                await conv.send_file(photo_path)
                
                if os.path.exists(photo_path):
                    os.remove(photo_path)

                # 2. Wait for Style Menu
                print("Waiting for Style Menu...")
                style_msg = None
                while True:
                    response = await conv.get_response()
                    if "Please select advanced undress type" in response.text and response.buttons:
                        style_msg = response
                        break
                    else:
                        print(f"Ignored message: {response.text[:20]}... (Waiting for Style Menu)")
                
                # Select Random Style (Loop for Pagination)
                while True:
                    print("Received Style Menu. Selecting random style...")
                    valid_buttons = []
                    
                    if style_msg.buttons:
                        for row in style_msg.buttons:
                            for btn in row:
                                if btn.text not in ["1/2", "2/2", "Cancel"]:
                                    valid_buttons.append(btn)
                    
                    if not valid_buttons:
                        print("No valid buttons found! Retrying...")
                        await asyncio.sleep(2)
                        continue

                    selected = random.choice(valid_buttons)
                    print(f"Clicking: {selected.text}")
                    await asyncio.sleep(random.uniform(2, 4))
                    await selected.click()

                    if selected.text in ["▶️", "◀️"]:
                        print("Navigation clicked. Waiting for menu update...")
                        try:
                            event = await conv.wait_event(events.MessageEdited(chats=config.TARGET_BOT_USERNAME), timeout=30)
                            if event.message.id == style_msg.id:
                                style_msg = event.message
                                continue 
                            else:
                                print("Warning: Edited message ID mismatch. Refreshing...")
                                style_msg = await client.get_messages(config.TARGET_BOT_USERNAME, ids=style_msg.id)
                                continue
                        except asyncio.TimeoutError:
                            print("Timeout waiting for menu update. Fetching latest message state.")
                            style_msg = await client.get_messages(config.TARGET_BOT_USERNAME, ids=style_msg.id)
                            continue
                    else:
                        break
                
                # Check for "No Face" Error immediately after selection
                # The bot might reply with an error instead of the Confirm menu
                print("Checking for response (Confirm or Error)...")
                confirm_msg = None
                is_error = False
                
                while True:
                    response = await conv.get_response()
                    
                    # Error Check
                    if "You haven't sent face photo" in response.text or "face photo has expired" in response.text:
                        print("Error: No face detected.")
                        is_error = True
                        # Click Cancel if available
                        if response.buttons:
                            for row in response.buttons:
                                for btn in row:
                                    if "Cancel" in btn.text:
                                        await btn.click()
                                        break
                        break

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
                        print(f"Ignored message: {response.text[:20]}... (Waiting for Confirm)")

                if is_error:
                    print("Aborting process due to No Face error.")
                    await client.send_message(source_chat_id, "Error: Please send a proper full-face close-up photo.", reply_to=message.id)
                    continue # Skip to next item in queue

                # Click Confirm
                print("Received Confirm Menu. Clicking Confirm...")
                confirm_btn = None
                for row in confirm_msg.buttons:
                    for btn in row:
                        if "Confirm" in btn.text:
                            confirm_btn = btn
                            break
                
                if confirm_btn:
                    await asyncio.sleep(random.uniform(2, 4))
                    await confirm_btn.click()

                # 4. Wait for Final Result
                print("Waiting for Final Result...")
                final_photo_msg = None
                while True:
                    response = await conv.get_response()
                    print("Waiting for edit...")
                    try:
                        event = await conv_store.wait_event(events.MessageEdited(chats=config.FILE_STORE_BOT_USERNAME), timeout=60)
                        if "Here is your link" in event.message.text:
                            generated_link = event.message.text
                    except asyncio.TimeoutError:
                        print("Timeout waiting for link generation.")
            
            # Extract URL from text
            # Text format: "Here is your link:\n\nhttps://t.me/..."
            final_url = None
            if generated_link:
                urls = re.findall(r'(https?://\S+)', generated_link)
                if urls:
                    final_url = urls[0]
            
            if final_url:
                print(f"Link generated: {final_url}")
                print("Sending reply to source group...")
                
                # Construct the mention
                # We have the original 'message' object. We can reply to it.
                # The user wants to @mention the user.
                # If we reply, Telegram automatically notifies the user usually.
                # But to explicitly mention:
                sender = await message.get_sender()
                mention = f"@{sender.username}" if sender.username else sender.first_name
                
                caption = f"Here is your Super Edit - see by opening this link - {final_url}\n{mention}"
                
                await client.send_message(source_chat_id, caption, reply_to=message.id)
                print("Process Complete!")
            else:
                print("Failed to extract link.")

            # Cleanup
            if os.path.exists(final_photo_path):
                os.remove(final_photo_path)

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

    # LOOP PREVENTION: Removed because we now output text links, so no photo loop risk.
    # We want to process the user's own photos.
    # if event.out:
    #    return

    chat = await event.get_chat()
    sender = await event.get_sender()
    user_id = sender.id if sender else 0
    
    # Listen for Photos in Groups
    if event.is_group and event.photo:
        # Filter by Group IDs
        if config.SOURCE_GROUP_IDS and chat.id not in config.SOURCE_GROUP_IDS:
            return

        print(f"\n[+] Photo received in group: {chat.title} (ID: {chat.id}) from User {user_id}")
        
        if not config.SOURCE_GROUP_IDS:
            print(f"NOTE: To restrict to this group, add {chat.id} to SOURCE_GROUP_IDS in config.py")

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
    print("Starting UserBot...")
    print("Please follow the prompts to log in.")
    print("--------------------------------------------------")
    
    client.start(
        phone=config.PHONE_NUMBER if config.PHONE_NUMBER else get_phone,
        code_callback=get_code,
        password=get_password
    )
    
    print("\n[SUCCESS] Logged in successfully!")
    print(f"Monitoring Group ID: {config.SOURCE_GROUP_IDS if config.SOURCE_GROUP_IDS != 0 else 'ALL GROUPS'}")
    
    client.loop.create_task(process_queue())
    
    client.run_until_disconnected()
