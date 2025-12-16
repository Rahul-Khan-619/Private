import asyncio
import random
import logging
import os
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
            
            # Use a conversation to ensure linear flow
            async with client.conversation(config.TARGET_BOT_USERNAME, timeout=1000) as conv:
                
                # 1. Download and Send Photo
                print("Downloading photo...")
                photo_path = await client.download_media(message, file="temp_input.jpg")
                
                print("Sending photo to bot...")
                await conv.send_file(photo_path)
                
                if os.path.exists(photo_path):
                    os.remove(photo_path)

                # 2. Wait for Style Menu ("Please select advanced undress type")
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
                    
                    # Filter buttons
                    if style_msg.buttons:
                        for row in style_msg.buttons:
                            for btn in row:
                                # Exclude pagination labels and Cancel
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

                    # Check if Navigation Button was clicked
                    if selected.text in ["▶️", "◀️"]:
                        print("Navigation clicked. Waiting for menu update...")
                        try:
                            # Wait for the message to be edited with new buttons
                            # events.MessageEdited doesn't take 'id' filter, so we filter manually
                            event = await conv.wait_event(events.MessageEdited(chats=config.TARGET_BOT_USERNAME), timeout=30)
                            
                            if event.message.id == style_msg.id:
                                style_msg = event.message
                                continue # Loop back to select from new buttons
                            else:
                                print("Warning: Edited message ID mismatch. Refreshing...")
                                style_msg = await client.get_messages(config.TARGET_BOT_USERNAME, ids=style_msg.id)
                                continue

                        except asyncio.TimeoutError:
                            print("Timeout waiting for menu update. Fetching latest message state.")
                            style_msg = await client.get_messages(config.TARGET_BOT_USERNAME, ids=style_msg.id)
                            continue
                    else:
                        # A style was selected
                        break

                # 3. Wait for Confirm Menu ("Confirm")
                print("Waiting for Confirm Menu...")
                confirm_msg = None
                while True:
                    response = await conv.get_response()
                    # Check if buttons exist and one of them is "Confirm"
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

                # 4. Wait for Final Result (Photo)
                print("Waiting for Final Result...")
                final_photo_msg = None
                while True:
                    response = await conv.get_response()
                    if response.photo:
                        final_photo_msg = response
                        break
                    else:
                        print(f"Ignored message: {response.text[:20]}... (Waiting for Photo)")

                # 5. Download and Upload back to Group
                print("Received Final Result. Downloading...")
                output_path = await client.download_media(final_photo_msg, file="temp_output.jpg")
                
                print("Uploading to source group...")
                await asyncio.sleep(random.uniform(1, 2))
                await client.send_file(
                    source_chat_id, 
                    output_path, 
                    caption="Msg to @Mr_Super_editor for real Edits",
                    reply_to=message.id # Reply to the original message
                )
                print("Process Complete!")
                
                if os.path.exists(output_path):
                    os.remove(output_path)

        except asyncio.TimeoutError:
            print("Timeout waiting for bot response.")
        except Exception as e:
            print(f"Error processing photo: {e}")
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
    
    # Listen for Photos in Groups
    if event.is_group and event.photo:
        # Filter by Group ID
        if config.SOURCE_GROUP_ID != 0 and chat.id != config.SOURCE_GROUP_ID:
            return

        print(f"\n[+] Photo received in group: {chat.title} (ID: {chat.id})")
        
        if config.SOURCE_GROUP_ID == 0:
            print(f"NOTE: To restrict to this group, set SOURCE_GROUP_ID = {chat.id} in config.py")

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
    
    # Start the client (Sync call, handles auth)
    client.start(
        phone=config.PHONE_NUMBER if config.PHONE_NUMBER else get_phone,
        code_callback=get_code,
        password=get_password
    )
    
    print("\n[SUCCESS] Logged in successfully!")
    print(f"Monitoring Group ID: {config.SOURCE_GROUP_ID if config.SOURCE_GROUP_ID != 0 else 'ALL GROUPS'}")
    
    # Schedule the worker on the client's event loop
    client.loop.create_task(process_queue())
    
    # Run the loop
    client.run_until_disconnected()
