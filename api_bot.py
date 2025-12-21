import asyncio
import logging
import os
import re
import time
import base64
import random
import httpx
from telethon import TelegramClient, events, Button
import config

# Configure logging
logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
                    level=logging.INFO)

# Initialize Clients with explicit loop
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Bot Client (Interacts with Group Users)
bot = TelegramClient('bot_session', config.API_ID, config.API_HASH, loop=loop)

# User Client (Interacts with Link Gen Bot)
user = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH, loop=loop)

# Rate Limiting
user_last_edit = {}
RATE_LIMIT_SECONDS = 7200 # 2 Hours

# User Settings State: {user_id: {'mode': 'naked', 'body': 'fit', ...}}
user_settings = {}

# Available Settings (from openapi.yaml)
SETTINGS_OPTIONS = {
    'generationMode': ["naked", "swimsuit", "underwear", "latex", "bondage"],
    'bodyType': ["skinny", "fit", "curvy", "muscular"],
    'gender': ["female", "male"]
}

# Load Promo Links
PROMO_LINKS = []
try:
    with open("promo_links.txt", "r") as f:
        PROMO_LINKS = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    print("Warning: promo_links.txt not found. Promo links will be empty.")

async def get_settings_keyboard(user_id):
    """Generates the inline keyboard based on user's current settings."""
    settings = user_settings.get(user_id, {
        'generationMode': 'naked',
        'bodyType': 'fit',
        'gender': 'female'
    })
    
    return [
        [
            Button.inline(f"Mode: {settings['generationMode'].capitalize()}", data="toggle_mode"),
            Button.inline(f"Body: {settings['bodyType'].capitalize()}", data="toggle_body")
        ],
        [
            Button.inline(f"Gender: {settings['gender'].capitalize()}", data="toggle_gender")
        ],
        [
            Button.inline("✅ Start Processing", data="start_process"),
            Button.inline("❌ Cancel", data="cancel_process")
        ]
    ]

async def process_image_api(photo_path, settings):
    """Uploads image to API and waits for result."""
    async with httpx.AsyncClient(timeout=300) as http:
        # 1. Read and Encode Image
        with open(photo_path, "rb") as f:
            encoded_string = base64.b64encode(f.read()).decode('utf-8')
        
        # 2. Create Task
        payload = {
            "base64": encoded_string,
            "settings": settings
        }
        headers = {"x-api-key": config.UNCLOTHY_API_KEY}
        
        print("Creating API task...")
        resp = await http.post(f"{config.UNCLOTHY_API_URL}/v2/task/create", json=payload, headers=headers)
        
        if resp.status_code != 201:
            print(f"API Error: {resp.text}")
            return None
            
        task_id = resp.json()['result']['task_id']
        print(f"Task Created: {task_id}")
        
        # 3. Poll for Result
        while True:
            await asyncio.sleep(10)
            resp = await http.get(f"{config.UNCLOTHY_API_URL}/v2/task/{task_id}", headers=headers)
            
            if resp.status_code != 200:
                print(f"Polling Error: {resp.text}")
                continue
                
            data = resp.json()['result']
            status = data['status']
            
            if status.lower() == 'completed':
                return data['url']
            elif status.lower() == 'failed':
                print("Task Failed.")
                return None
            
            print(f"Task Status: {status}...")

async def generate_link_via_userbot(image_url):
    """Uses the UserBot to send the image to Link Gen Bot and get a link."""
    try:
        # Download the image from the URL first
        async with httpx.AsyncClient() as http:
            resp = await http.get(image_url)
            if resp.status_code != 200:
                return None
            
            with open("temp_api_result.jpg", "wb") as f:
                f.write(resp.content)
        
        # Interact with File Store Bot
        print(f"UserBot: Sending to {config.FILE_STORE_BOT_USERNAME}...")
        async with user.conversation(config.FILE_STORE_BOT_USERNAME, timeout=120) as conv:
            sent_msg = await user.send_file(config.FILE_STORE_BOT_USERNAME, "temp_api_result.jpg")
            await conv.send_message('/genlink', reply_to=sent_msg.id)
            
            response = await conv.get_response()
            generated_link = None
            
            if "Here is your link" in response.text:
                generated_link = response.text
            else:
                try:
                    event = await conv.wait_event(events.MessageEdited(chats=config.FILE_STORE_BOT_USERNAME), timeout=60)
                    if "Here is your link" in event.message.text:
                        generated_link = event.message.text
                except asyncio.TimeoutError:
                    pass
            
            if generated_link:
                urls = re.findall(r'(https?://\S+)', generated_link)
                if urls:
                    return urls[0]
                    
        return None
    except Exception as e:
        print(f"UserBot Error: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        if os.path.exists("temp_api_result.jpg"):
            os.remove("temp_api_result.jpg")

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    """Responds to /start to verify bot is running."""
    await event.reply("✅ Bot is running! Send a photo to a configured group to start editing.")

@bot.on(events.NewMessage)
async def bot_handler(event):
    # Ignore /start as it's handled above
    if event.text and event.text.startswith('/start'):
        return

    # --- DM Handler ---
    if event.is_private:
        promo_link = random.choice(PROMO_LINKS) if PROMO_LINKS else "https://t.me/Mr_Super_Edits_robot"
        
        msg_text = f"{promo_link}\nthis is the sample Edit If you wnat to do edit like this click the 👇👇👇"
        
        buttons = [
            [Button.url("I Need Video Edit Bot @ Less Price", "https://t.me/Mr_Super_Editor?text=I%20Need%20Private%20Telegram%20Bot%20@%20Best%20Price")],
            [Button.url("Can't Send Dm to Admin ? 👈 Click Here", "https://t.me/Mr_Super_Editor_Bot?text=I%20Need%20Private%20Telegram%20Bot%20@%20Best%20Price")]
        ]
        
        await event.reply(msg_text, buttons=buttons)
        return

    # --- Group Handler ---
    if not event.is_group or not event.photo:
        return

    chat = await event.get_chat()
    
    # Filter Group
    if config.API_BOT_GROUPS:
        if chat.id not in config.API_BOT_GROUPS:
             return
        
    sender = await event.get_sender()
    user_id = sender.id
    
    # Album Check
    if event.grouped_id:
        await event.reply("⚠️ Please send only one photo at a time.")
        return

    # Rate Limit Check
    current_time = time.time()
    if user_id in user_last_edit:
        elapsed = current_time - user_last_edit[user_id]
        if elapsed < RATE_LIMIT_SECONDS:
            remaining = int(RATE_LIMIT_SECONDS - elapsed)
            hours = remaining // 3600
            mins = (remaining % 3600) // 60
            await event.reply(f"⚠️ Limit reached. You can edit again in {hours}h {mins}m.")
            return

    # Spam Check
    await asyncio.sleep(5)
    try:
        msg = await bot.get_messages(chat.id, ids=event.id)
        if not msg:
            return # Deleted
    except:
        return

    # Initialize Settings
    user_settings[user_id] = {
        'generationMode': 'naked',
        'bodyType': 'fit',
        'gender': 'female'
    }
    
    # Send Settings Menu
    await event.reply(
        "⚙️ **Configure your edit:**\nSelect options below and click Start.",
        buttons=await get_settings_keyboard(user_id)
    )

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    if user_id not in user_settings:
        await event.answer("Session expired or not yours.", alert=True)
        return

    settings = user_settings[user_id]
    
    if data == "cancel_process":
        del user_settings[user_id]
        await event.delete()
        return

    if data == "toggle_mode":
        modes = SETTINGS_OPTIONS['generationMode']
        current_idx = modes.index(settings['generationMode'])
        settings['generationMode'] = modes[(current_idx + 1) % len(modes)]
        await event.edit(buttons=await get_settings_keyboard(user_id))
    
    elif data == "toggle_body":
        bodies = SETTINGS_OPTIONS['bodyType']
        current_idx = bodies.index(settings['bodyType'])
        settings['bodyType'] = bodies[(current_idx + 1) % len(bodies)]
        await event.edit(buttons=await get_settings_keyboard(user_id))
        
    elif data == "toggle_gender":
        genders = SETTINGS_OPTIONS['gender']
        current_idx = genders.index(settings['gender'])
        settings['gender'] = genders[(current_idx + 1) % len(genders)]
        await event.edit(buttons=await get_settings_keyboard(user_id))

    elif data == "start_process":
        # Start!
        await event.edit("⏳ Processing... Please wait.", buttons=None)
        
        # Get the original message to download photo
        msg = await event.get_message()
        reply_msg = await msg.get_reply_message()
        
        if not reply_msg or not reply_msg.photo:
            await event.edit("❌ Error: Original photo not found.")
            return

        # Download
        photo_path = await bot.download_media(reply_msg, file="temp_api_input.jpg")
        
        # Call API
        result_url = await process_image_api(photo_path, settings)
        
        if os.path.exists(photo_path):
            os.remove(photo_path)
            
        if not result_url:
            await event.edit("❌ Processing failed. Please try again later.")
            return
            
        await event.edit("✅ Image processed! Generating link...")
        
        # Generate Link (UserBot)
        final_link = await generate_link_via_userbot(result_url)
        
        if final_link:
            # Construct Caption
            promo_link = random.choice(PROMO_LINKS) if PROMO_LINKS else "https://t.me/Mr_Super_Edits_robot"
            caption = f"Your Edited Photo Result is here � {final_link}\n👇👇👇👇\n{promo_link} \n 👆👆 Do You want to Do a Video Edit Like This ?\nMsg to @Mr_Super_Editor"
            
            await event.edit(caption)
            # Update Rate Limit
            user_last_edit[user_id] = time.time()
            del user_settings[user_id]
        else:
            await event.edit("❌ Failed to generate link.")

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

async def main():
    print("Starting API Bot...")
    
    # Start User Client (for link generation)
    print("Logging in User Client...")
    await user.start(
        phone=config.PHONE_NUMBER if config.PHONE_NUMBER else get_phone,
        code_callback=get_code,
        password=get_password
    )
    
    # Start Bot Client (for group interaction)
    print("Logging in Bot Client...")
    await bot.start(bot_token=config.API_BOT_TOKEN)
    
    print("Both clients running!")
    print(f"Monitoring Group ID: {config.API_BOT_GROUPS}")
    
    # Run until disconnected
    await asyncio.gather(
        bot.run_until_disconnected(),
        user.run_until_disconnected()
    )

if __name__ == '__main__':
    loop.run_until_complete(main())
