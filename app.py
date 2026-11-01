import os
import json
import time
import requests
from flask import Flask, request

# --- НАСТРОЙКИ (лучше вынести в переменные окружения Render) ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8899237597:AAHiRm411lCpen9wfZV37XWL6OHY6tqBp4Y")
MY_CHAT_ID = int(os.environ.get("MY_CHAT_ID", 8943150715))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "") # Render подставит сам

app = Flask(__name__)

# Хранилище в памяти (при перезапуске Render сбросится — для продакшена лучше БД)
selected_chat_id = None
pending_reply_to = None
pending_reply_chat = None

# --- Bot API хелперы ---
def api_call(method, params=None):
    if params is None: params = {}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        resp = requests.post(url, json=params, timeout=35)
        return resp.json()
    except Exception as e:
        print(f"API error {method}: {e}")
        return None

def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    params = {"chat_id": chat_id, "text": text}
    if parse_mode: params["parse_mode"] = parse_mode
    if reply_markup: params["reply_markup"] = reply_markup
    return api_call("sendMessage", params)

# --- Инициализация вебхука при старте ---
@app.before_request
def setup_webhook_once():
    global _webhook_set
    if not _webhook_set and RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}"
        api_call("setWebhook", {"url": webhook_url})
        _webhook_set = True

_webhook_set = False

# --- Эндпоинт для проверки работоспособности (важно для Render) ---
@app.route("/health")
def health():
    return "OK", 200

# --- Основной эндпоинт для вебхука Telegram ---
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    global selected_chat_id, pending_reply_to, pending_reply_chat

    update = request.get_json(force=True)
    if not update:
        return "Bad Request", 400

    # 1. Callback-кнопки
    if "callback_query" in update:
        cb = update["callback_query"]
        cb_id = cb["id"]
        data = cb.get("data", "")
        api_call("answerCallbackQuery", {"callback_query_id": cb_id})

        if data.startswith("reply_") and selected_chat_id:
            orig_msg_id = int(data.split("_")[1])
            pending_reply_to = orig_msg_id
            pending_reply_chat = selected_chat_id
            send_message(MY_CHAT_ID, "✏️ Введите текст ответа.")
        elif data.startswith("react_") and selected_chat_id:
            orig_msg_id = int(data.split("_")[1])
            api_call("setMessageReaction", {
                "chat_id": selected_chat_id,
                "message_id": orig_msg_id,
                "reaction": [{"type": "emoji", "emoji": "👍"}]
            })
            send_message(MY_CHAT_ID, "👍 Реакция поставлена.")
        return "OK", 200

    # 2. Обычные сообщения
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return "OK", 200

    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    message_id = msg["message_id"]

    # Команда /setchat
    if text.strip() == "/setchat":
        selected_chat_id = chat_id
        send_message(MY_CHAT_ID, f"✅ Чат `{chat_id}` выбран.", parse_mode="Markdown")
        send_message(chat_id, "✅ Этот чат под наблюдением.")
        return "OK", 200

    # Сообщение из выбранного чата -> вам в личку
    if selected_chat_id and chat_id == selected_chat_id:
        sender = msg.get("from", {}).get("first_name", "Кто-то")
        keyboard = {
            "inline_keyboard": [[
                {"text": "💬 Ответить", "callback_data": f"reply_{message_id}"},
                {"text": "👍 Реакция", "callback_data": f"react_{message_id}"}
            ]]
        }
        send_message(MY_CHAT_ID, f"💬 **{sender}**:\n\n{text}", parse_mode="Markdown", reply_markup=keyboard)
        return "OK", 200

    # Сообщение от вас в личку боту -> пересылка в выбранный чат
    if chat_id == MY_CHAT_ID:
        if pending_reply_to and pending_reply_chat:
            target_chat, target_msg = pending_reply_chat, pending_reply_to
            pending_reply_to = None
            pending_reply_chat = None
            api_call("sendMessage", {"chat_id": target_chat, "text": text, "reply_to_message_id": target_msg})
            send_message(MY_CHAT_ID, "✅ Ответ отправлен.")
        elif selected_chat_id:
            api_call("sendMessage", {"chat_id": selected_chat_id, "text": text})
            send_message(MY_CHAT_ID, "✅ Переслано в чат.")
        else:
            send_message(MY_CHAT_ID, "⚠️ Сначала выберите чат командой /setchat.")
        return "OK", 200

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
