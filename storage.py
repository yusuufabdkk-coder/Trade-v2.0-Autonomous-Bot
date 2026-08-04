import json
import os
import logging

logger = logging.getLogger(__name__)

AI_HISTORY_FILE = "data_ai_history.json"
CHAT_HISTORY_FILE = "data_chat_history.json"
INITIAL_BALANCE_FILE = "data_initial_balance.json"

def load_json(filepath, default_value):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filepath}: {e}")
    return default_value

def save_json(filepath, data):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Error saving {filepath}: {e}")

def load_ai_history():
    return load_json(AI_HISTORY_FILE, [])

def save_ai_history(history):
    save_json(AI_HISTORY_FILE, history)

def load_chat_history():
    return load_json(CHAT_HISTORY_FILE, [])

def save_chat_history(history):
    save_json(CHAT_HISTORY_FILE, history)

def load_initial_balance():
    return load_json(INITIAL_BALANCE_FILE, None)

def save_initial_balance(balance: float):
    save_json(INITIAL_BALANCE_FILE, balance)
