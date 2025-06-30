import os
import cryptg
from dotenv import load_dotenv, set_key
from telethon import TelegramClient

# Getting user api with input from user
def get_user_api():
    print("\n" + "="*50)
    print("To work with the Telegram API, you need api_id and api_hash.")
    print("You can get them at https://my.telegram.org / in the 'API Development Tools' section")
    print("="*50 + "\n")
    
    api_id = input('Enter API ID:\n>>> ')
    api_hash = input('Enter API Hash:\n>>> ')
    
    return api_id, api_hash

# Initializing Telegram Client
def init_telegram_client(session_name='session_name', env_file='.env'):
    #Double checking for cryptg
    try:
        import cryptg
        print("[+] cryptg activated for speed boost")
    except ImportError:
        print("[!] cryptg not installed. Install with: pip install cryptg")

    #Loading dotenv with api
    load_dotenv(env_file)
    
    api_id = os.getenv('API_ID')
    api_hash = os.getenv('API_HASH')
    
    #If there's no api or dotenv asking for them again
    if not api_id or not api_hash:
        api_id, api_hash = get_user_api()
        
        set_key(env_file, 'API_ID', api_id)
        set_key(env_file, 'API_HASH', api_hash)
        print(f"[+] API data is saved to a file {env_file}")

    try:
        api_id = int(api_id)
    except ValueError:
        print("[!] Error: API ID must be a number")
        exit(1)

    try:
        client = TelegramClient(session_name, api_id, api_hash)
        print("[+] The Telegram client has been successfully initialized")
        return client
    except Exception as e:
        print(f"[!] Critical client initialization error: {e}")
        exit(1)