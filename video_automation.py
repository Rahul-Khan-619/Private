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

# Configuration for this specific script
VIDEO_BOT_USERNAME = "@Xyz_vid_bot"

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
            
            # --- STEP 1: Process with Video Bot ---
            final_video_msg = None
            
            async with client.conversation(VIDEO_BOT_USERNAME, timeout=1200) as conv: # 20 mins timeout
                
                # 1. Download and Send Photo
                print("Downloading photo...")
                photo_path = await client.download_media(message, file="temp_input.jpg")
                
                print(f"Sending photo to {VIDEO_BOT_USERNAME}...")
                await conv.send_file(photo_path)
                
                if os.path.exists(photo_path):
                    os.remove(photo_path)

                # 2. Wait for Effect Menu ("Please select the effect")
                print("Waiting for Effect Menu...")
                effect_msg = None
                while True:
                    response = await conv.get_response()
                    if "Please select the effect" in response.text and response.buttons:
                        effect_msg = response
                        break
                    else:
                        print(f"Ignored message: {response.text[:20]}... (Waiting for Effect Menu)")
                
                # Select Random Effect
                # Filter out "Preview" button and handle navigation
                print("Received Effect Menu. Selecting random effect...")
                
                while True:
                    valid_buttons = []
                    if effect_msg.buttons:
                        for row in effect_msg.buttons:
                            for btn in row:
                                if "Preview" not in btn.text and btn.text not in ["1/2", "2/2", "Cancel", "Back"]:
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
                            # Wait for the message to be edited (pagination)
                            event = await conv.wait_event(events.MessageEdited(chats=VIDEO_BOT_USERNAME), timeout=30)
                            effect_msg = event.message
                            continue
                        except asyncio.TimeoutError:
                            print("Timeout waiting for menu update. Re-fetching message...")
                            effect_msg = await client.get_messages(VIDEO_BOT_USERNAME, ids=effect_msg.id)
                            continue
                    else:
                        break

                # Check for "No Face" Error immediately after selection
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

                # 4. Wait for Final Result (Video)
                print("Waiting for Final Result (Video)... This may take 10-15 mins.")
                while True:
                    response = await conv.get_response()
                    # Check for video or document (sometimes videos are sent as documents)
                    if response.video or (response.document and response.document.mime_type.startswith('video/')):
                        final_video_msg = response
                        break
                    elif "Task submitted successfully" in response.text:
                        print("Task submitted. Waiting...")
                    else:
                        print(f"Ignored message: {response.text[:20]}... (Waiting for Video)")

                print("Received Final Result.")

            # --- STEP 2: Generate Link with File Store Bot ---
            print(f"Starting interaction with {config.FILE_STORE_BOT_USERNAME}...")
            generated_link = None
            
            async with client.conversation(config.FILE_STORE_BOT_USERNAME, timeout=120) as conv_store:
                # Forward the processed video directly
                print("Forwarding processed video to File Store Bot...")
                # We use client.forward_messages but we need to capture the result to reply to it.
                # Also, we are inside a conversation context. 
                # To ensure conv_store tracks it, we can use conv_store.send_message with file=final_video_msg (which acts as forward/upload)
                # OR we just forward and then send the command via conv_store.
                
                forwarded_msg = await client.forward_messages(config.FILE_STORE_BOT_USERNAME, final_video_msg)
                
                print("Sending /genlink command...")
                # WE MUST USE conv_store.send_message HERE to avoid "No message was sent previously" error
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
                        # We use conv_store.wait_event to ensure we catch the edit in this chat
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
                
                sender = await message.get_sender()
                mention = f"@{sender.username}" if sender.username else sender.first_name
                
                # caption = f"Here is your Super Edit (Video) - see by opening this link - {final_url}\n{mention}"
                caption = f"Your Edited Video Result is here 👉 {final_url} \n\n Dm to @Mr_Super_Man And Get Photo to Video Edit Bot at less Price \n Demo Edits to 👉 https://t.me/Mr_Super_Man_FilesBot?start=BQADAQADEwgAAqELUUfleEPZZcx5-RYE  DON'T MISS "

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
    
    # Filter by Group IDs
    if config.VIDEO_BOT_GROUPS and chat.id not in config.VIDEO_BOT_GROUPS:
        return

    # Ignore Albums
    if event.grouped_id:
        await event.reply("⚠️ Please send only one photo at a time.")
        return

    sender = await event.get_sender()
    user_id = sender.id if sender else 0
    
    # Listen for Photos in Groups
    if event.is_group and event.photo:
        print(f"\n[+] Photo received in group: {chat.title} (ID: {chat.id}) from User {user_id}")
        
        if not config.VIDEO_BOT_GROUPS:
            print(f"NOTE: To restrict to this group, add {chat.id} to VIDEO_BOT_GROUPS in config.py")

        # 1. Rate Limit Check
        current_time = time.time()
        if user_id in user_last_seen:
            elapsed = current_time - user_last_seen[user_id]
            if elapsed < RATE_LIMIT_SECONDS:
                print(f"Rate Limit: User {user_id} ignored (Wait {int(RATE_LIMIT_SECONDS - elapsed)}s)")
                return

        # 2. Spam Check (Delay & Existence)
        print("Waiting 5s to check for spam deletion...")
        await asyncio.sleep(6)
        
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
    print("Starting Video Automation Bot...")
    print("Please follow the prompts to log in.")
    print("--------------------------------------------------")
    
    client.start(
        phone=config.PHONE_NUMBER if config.PHONE_NUMBER else get_phone,
        code_callback=get_code,
        password=get_password
    )
    
    print("\n[SUCCESS] Logged in successfully!")
    print(f"Monitoring Group IDs: {config.VIDEO_BOT_GROUPS if config.VIDEO_BOT_GROUPS else 'ALL GROUPS'}")
    
    client.loop.create_task(process_queue())
    
    client.run_until_disconnected()
