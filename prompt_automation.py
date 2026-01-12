import asyncio
import logging
import os
import re
import time
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

# Bot Client (Interacts with Group Users - UI)
bot = TelegramClient('bot_session_prompt', config.API_ID, config.API_HASH, loop=loop)

# User Client (Interacts with Master/Result Bots)
user = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH, loop=loop)

# Album Check
if event.grouped_id:
    await event.reply("⚠️ Please send only one photo at a time.")
    return

# Rate Limiting
user_last_edit = {}
RATE_LIMIT_SECONDS = 7200 # 2 Hours

# Load Promo Links
PROMO_LINKS = []
try:
    with open("promo_links.txt", "r") as f:
        PROMO_LINKS = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    print("Warning: promo_links.txt not found. Promo links will be empty.")

# --- PROMPTS DATA ---
PROMPTS = {
    "1": {
        "title": "Micro Bikini",
        "prompt": "Woman in tiny string micro bikini, thin straps barely covering nipples and pussy lips, side ties digging into hips"
    },
    "2": {
        "title": "Shibari Bondage",
        "prompt": "Woman wearing intricate red shibari rope bondage, ropes tightly wrapped around bare breasts, waist and thighs, nipples and pussy exposed between ropes"
    },
    "3": {
        "title": "Sheer Lingerie",
        "prompt": "Woman in ultra-sheer transparent lingerie set, completely see-through black lace bra and thong, hard nipples and shaved pussy fully visible"
    },
    "4": {
        "title": "X-Ray Dress",
        "prompt": "Woman in extremely transparent x-ray style dress, almost invisible sheer white fabric, entire naked body clearly visible underneath, breasts and pussy perfectly outlined"
    },
    "5": {
        "title": "Neon Pink Bikini",
        "prompt": "Woman in tiny neon pink bikini, micro triangles only covering nipples, thin bottom barely covering pussy, lots of bare skin"
    },
    "6": {
        "title": "BDSM Harness",
        "prompt": "Woman in black leather BDSM harness, thin straps crossing bare breasts and around hips, pussy and nipples completely exposed"
    },
    "7": {
        "title": "Fishnet Body",
        "prompt": "Woman wearing full-body fishnet bodystocking with large open crotch and chest holes, nipples and shaved pussy fully bare"
    },
    "8": {
        "title": "Wet Micro Dress",
        "prompt": "Woman in wet see-through white micro dress, fabric completely transparent when wet, hard nipples and pussy clearly visible"
    },
    "9": {
        "title": "Sexy Nurse",
        "prompt": "Woman in sexy nurse micro dress, ultra-short white fabric, deep cleavage, no bra, thong pulled aside exposing pussy"
    },
    "10": {
        "title": "Latex Catsuit",
        "prompt": "Woman in glossy black latex catsuit with open crotch zipper, pussy and breasts fully exposed through open zipper"
    },
    "11": {
        "title": "Gold Thong",
        "prompt": "Woman wearing only tiny metallic gold thong bikini bottom, completely topless, bare breasts, thin string barely covering pussy"
    },
    "12": {
        "title": "Pink Babydoll",
        "prompt": "Woman in sheer babydoll chemise, extremely transparent pink mesh, nipples and entire pussy visible through fabric"
    },
    "13": {
        "title": "Strappy Bondage",
        "prompt": "Woman in strappy black bondage lingerie, thin leather straps and chains, breasts and pussy completely bare between straps"
    },
    "14": {
        "title": "Red Satin Thong",
        "prompt": "Woman wearing red satin micro thong and pasties, tiny heart-shaped nipple covers, pussy barely hidden by thin fabric"
    },
    "15": {
        "title": "Wedding Lingerie",
        "prompt": "Woman in completely sheer white wedding lingerie, transparent veil and garter set, full naked body visible underneath"
    }
}

ITEMS_PER_PAGE = 6

def get_menu_keyboard(page=0):
    """Generates pagination keyboard."""
    keys = list(PROMPTS.keys())
    total_pages = (len(keys) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    current_keys = keys[start_idx:end_idx]
    
    buttons = []
    # Add Prompt Buttons (2 per row)
    row = []
    for k in current_keys:
        row.append(Button.inline(f"{k}. {PROMPTS[k]['title']}", data=f"sel_{k}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    # Navigation
    nav_row = []
    if page > 0:
        nav_row.append(Button.inline("⬅️ Back", data=f"page_{page-1}"))
    if page < total_pages - 1:
        nav_row.append(Button.inline("Next ➡️", data=f"page_{page+1}"))
    
    if nav_row:
        buttons.append(nav_row)
        
    # Cancel
    buttons.append([Button.inline("❌ Cancel", data="cancel_process")])
    
    # Fixed Link Button
    buttons.append([Button.url("Photo to Video H0t Edit ?", "https://t.me/Mr_Super_Human_SafeBot?start=BQADAQADsAcAArdCGUcmMLiK5duPGBYE")])
    
    return buttons

async def process_with_user_client(photo_path, prompt_id):
    """Handles the interaction with Master Bot and Result Bot using User Client."""
    try:
        prompt_text = PROMPTS[prompt_id]['prompt']
        
        # 1. Send Photo to Master Bot
        print(f"Sending photo to {config.MASTER_BOT_USERNAME}...")
        async with user.conversation(config.MASTER_BOT_USERNAME, timeout=120) as conv_master:
            await conv_master.send_file(photo_path)
            
            # Wait for "Send positive prompt."
            print("Waiting for prompt request...")
            response = await conv_master.get_response()
            if "positive prompt" not in response.text.lower():
                print(f"Unexpected response: {response.text}")
                # Try to proceed anyway or return? Let's assume we can send prompt.
            
            print(f"Sending prompt: {prompt_text[:20]}...")
            await conv_master.send_message(prompt_text)
            
        # 2. Wait for Result from Result Bot
        # The result comes to the user's private chat from RESULT_BOT_USERNAME
        print(f"Waiting for result from {config.RESULT_BOT_USERNAME}...")
        
        # We need to listen for a NEW message from RESULT_BOT_USERNAME
        # We can't use 'conversation' easily if the bot initiates the message or if it's async.
        # But usually, after sending prompt to Master, Result bot sends message shortly.
        # We'll use a temporary event listener.
        
        future_result = loop.create_future()
        
        def result_handler(event):
            if event.chat_id and event.sender_id:
                # Check if sender is the Result Bot
                # We need to resolve the entity to check ID or username
                # For simplicity, we check if the event chat corresponds to the bot
                # But event.chat_id for incoming private message is the User ID (our ID) or the Bot ID?
                # In Telethon, event.chat_id in DM is the peer (the bot).
                pass
            
            # We will filter in the event decorator
            if event.photo:
                future_result.set_result(event.message)
        
        # Create a specific listener for the Result Bot
        # We need the InputPeer for the bot to filter efficiently, or just filter by username string if possible (less efficient)
        # Let's resolve the entity first
        try:
            result_bot_entity = await user.get_input_entity(config.RESULT_BOT_USERNAME)
        except:
            print("Could not resolve Result Bot entity.")
            return None

        @user.on(events.NewMessage(from_users=result_bot_entity))
        async def _internal_handler(event):
            if not future_result.done() and event.photo:
                future_result.set_result(event.message)

        try:
            final_photo_msg = await asyncio.wait_for(future_result, timeout=300) # 5 mins timeout
        except asyncio.TimeoutError:
            print("Timeout waiting for result photo.")
            return None
        finally:
            user.remove_event_handler(_internal_handler)

        if not final_photo_msg:
            return None
            
        print("Received result photo.")

        # 3. Generate Link
        print(f"Forwarding to {config.FILE_STORE_BOT_USERNAME}...")
        async with user.conversation(config.FILE_STORE_BOT_USERNAME, timeout=120) as conv_store:
            forwarded_msg = await user.forward_messages(config.FILE_STORE_BOT_USERNAME, final_photo_msg)
            await conv_store.send_message('/genlink', reply_to=forwarded_msg.id)
            
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
                pass
        
        if generated_link:
            urls = re.findall(r'(https?://\S+)', generated_link)
            if urls:
                return urls[0]
                
        return None

    except Exception as e:
        print(f"Error in user client process: {e}")
        import traceback
        traceback.print_exc()
        return None

@bot.on(events.NewMessage)
async def bot_handler(event):
    if not event.is_group or not event.photo:
        return

    chat = await event.get_chat()
    if config.PROMPT_BOT_GROUPS and chat.id not in config.PROMPT_BOT_GROUPS:
        return
        
    sender = await event.get_sender()
    user_id = sender.id
    
    # Rate Limit
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
            return
    except:
        return

    # Send Menu
    await event.reply(
        "🎨 **Select a Style for your Edit:**",
        buttons=get_menu_keyboard(0)
    )

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode('utf-8')
    
    if data == "cancel_process":
        await event.delete()
        return

    if data.startswith("page_"):
        page = int(data.split("_")[1])
        await event.edit(buttons=get_menu_keyboard(page))
        return
        
    if data.startswith("sel_"):
        prompt_id = data.split("_")[1]
        
        await event.edit("⏳ Processing... Please wait. This may take a few minutes.", buttons=None)
        
        # Get Original Message
        msg = await event.get_message()
        reply_msg = await msg.get_reply_message()
        
        if not reply_msg or not reply_msg.photo:
            await event.edit("❌ Error: Original photo not found.")
            return

        # Download
        photo_path = await bot.download_media(reply_msg, file=f"temp_prompt_{user_id}.jpg")
        
        # Process
        final_link = await process_with_user_client(photo_path, prompt_id)
        
        if os.path.exists(photo_path):
            os.remove(photo_path)
            
        if final_link:
            promo_link = random.choice(PROMO_LINKS) if PROMO_LINKS else "https://t.me/Mr_Super_Edits_robot"
            # caption = f"Your Edited Photo Result is here 👉 {final_link}\n👇👇👇👇\n{promo_link} \n 👆👆 Do You want to Do a Video Edit Like This ?\nMsg to @Mr_Super_Editor"
            caption = f"Your Edited Photo Result is here 👉 {final_link} \n\n Dm to @Mr_Super_Man And Get Photo to Video Edit Bot at less Price \n msg to https://t.me/Mr_Super_man?text=I%20Need%20Private%20P0rn%20Video%20Edit%20bot%20  Now "
                        

            await event.edit(caption)
            user_last_edit[user_id] = time.time()
        else:
            await event.edit("❌ Processing failed or timed out.")

def get_code():
    print("\nIMPORTANT: Check your Telegram app for the login code.")
    code = input("Enter the OTP code (spaces will be removed): ")
    return code.replace(" ", "")

def get_password():
    return input("Enter your 2FA password: ")

def get_phone():
    return input("Enter your phone number (e.g., +1234567890): ")

async def main():
    print("Starting Prompt Automation Bot...")
    
    print("Logging in User Client...")
    await user.start(
        phone=config.PHONE_NUMBER if config.PHONE_NUMBER else get_phone,
        code_callback=get_code,
        password=get_password
    )
    
    print("Logging in Bot Client...")
    await bot.start(bot_token=config.API_BOT_TOKEN)
    
    print("Both clients running!")
    print(f"Monitoring Group ID: {config.PROMPT_BOT_GROUPS}")
    
    await asyncio.gather(
        bot.run_until_disconnected(),
        user.run_until_disconnected()
    )

if __name__ == '__main__':
    loop.run_until_complete(main())
