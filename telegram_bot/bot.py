import os
import logging
import requests
import io
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Получение переменных окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_HOST = os.getenv("API_HOST", "cambridge-api")
API_PORT = os.getenv("API_PORT", "8000")

API_URL = f"http://{API_HOST}:{API_PORT}"

# Максимальная длина сообщения в Telegram
MAX_MESSAGE_LENGTH = 4000  # Оставляем запас для безопасности (фактический лимит 4096)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет приветственное сообщение при команде /start."""
    await update.message.reply_text(
        "Привет! Я бот для поиска определений слов в Cambridge Dictionary. "
        "Просто отправь мне английское слово."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет помощь при команде /help."""
    await update.message.reply_text(
        "Отправьте мне английское слово, и я найду его определение в Cambridge Dictionary."
    )

def split_message(text, max_length=MAX_MESSAGE_LENGTH):
    """Разделяет длинный текст на части подходящего размера."""
    if len(text) <= max_length:
        return [text]
    
    parts = []
    current_part = ""
    
    # Разбиваем текст по абзацам для более естественного деления
    paragraphs = text.split('\n\n')
    
    for paragraph in paragraphs:
        # Если абзац сам по себе слишком длинный, разбиваем его по строкам
        if len(paragraph) > max_length:
            lines = paragraph.split('\n')
            for line in lines:
                # Если даже одна строка слишком длинная, разбиваем ее по частям
                if len(line) > max_length:
                    for i in range(0, len(line), max_length):
                        chunk = line[i:i+max_length]
                        if len(current_part + chunk) > max_length:
                            parts.append(current_part)
                            current_part = chunk
                        else:
                            current_part += chunk
                else:
                    if len(current_part + '\n' + line) > max_length:
                        parts.append(current_part)
                        current_part = line
                    else:
                        current_part = current_part + '\n' + line if current_part else line
        else:
            if len(current_part + '\n\n' + paragraph) > max_length:
                parts.append(current_part)
                current_part = paragraph
            else:
                current_part = current_part + '\n\n' + paragraph if current_part else paragraph
    
    if current_part:
        parts.append(current_part)
    
    return parts

async def download_and_send_audio(update, audio_url, caption="", voice_type="US"):
    """Скачивает аудио по URL и отправляет его в чат."""
    try:
        response = requests.get(
            audio_url, 
            stream=True,
            headers={"User-Agent": "Mozilla/5.0"},  # Добавляем заголовок
            verify=False  # Отключаем проверку SSL
        )
        response.raise_for_status()
        
        audio_data = io.BytesIO(response.content)
        audio_data.name = f"pronunciation_{voice_type}.mp3"
        
        # Отправляем аудио
        await update.message.reply_voice(
            voice=audio_data, 
            caption=caption,
            filename=audio_data.name
        )
        return True
    except Exception as e:
        logger.error(f"Ошибка при скачивании/отправке аудио: {e}")
        return False

async def search_word(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Поиск определения слова через API сервис."""
    word = update.message.text.strip().lower()
    
    if not word:
        await update.message.reply_text("Пожалуйста, введите слово для поиска.")
        return
    
    await update.message.reply_text(f"Ищу определение для слова '{word}'...")
    
    try:
        response = requests.get(f"{API_URL}/search/{word}", timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "error" in data:
            await update.message.reply_text(f"Ошибка: {data['error']}")
            return
        
        # Форматируем основное сообщение
        result = f"📚 *{data['word'].capitalize()}*\n\n"
        
        # Форматируем части речи
        if "pos" in data and data["pos"]:
            result += f"🔤 *Часть речи:* {', '.join(data['pos'])}\n\n"
        
        # Произношение
        if "pronunciation" in data and data["pronunciation"]:
            result += "*Произношение:*\n"
            unique_prons = {}
            for pron in data["pronunciation"]:
                key = f"{pron['lang']}-{pron['pron']}"
                if key not in unique_prons:
                    unique_prons[key] = pron
            
            for key, pron in unique_prons.items():
                lang_label = "🇬🇧 UK" if pron['lang'] == 'uk' else "🇺🇸 US" if pron['lang'] == 'us' else pron['lang'].upper()
                result += f"{lang_label}: {pron['pron']}\n"
            result += "\n"
        
        # Определения
        if "definition" in data and data["definition"]:
            result += "*Определения:*\n"
            for i, definition in enumerate(data["definition"], 1):
                pos = f" ({definition['pos']})" if 'pos' in definition and definition['pos'] else ""
                result += f"{i}.{pos} {definition['text']}\n"
                
                # Если есть перевод
                if "translation" in definition and definition["translation"]:
                    result += f"   _Перевод:_ {definition['translation']}\n"
                
                # Если есть примеры
                if "example" in definition and definition["example"]:
                    result += "   _Примеры:_\n"
                    for ex in definition["example"][:3]:
                        result += f"   • {ex['text']}\n"
                        if 'translation' in ex and ex['translation']:
                            result += f"     {ex['translation']}\n"
                    result += "\n"
        else:
            result += "Определения не найдены.\n"
        
        # Разделяем итоговое сообщение на части и отправляем
        message_parts = split_message(result)
        
        for i, part in enumerate(message_parts):
            if i == 0:
                # Первая часть без дополнительной информации
                await update.message.reply_text(part, parse_mode="Markdown")
            else:
                # Последующие части с указанием, что это продолжение
                await update.message.reply_text(f"(Продолжение {i+1}/{len(message_parts)})\n\n{part}", parse_mode="Markdown")
        
        # Отправляем аудио, если есть
        if "pronunciation" in data and data["pronunciation"]:
            # Отправляем UK и US произношения, если они доступны
            uk_pron = next((p for p in data["pronunciation"] if p["lang"] == "uk"), None)
            us_pron = next((p for p in data["pronunciation"] if p["lang"] == "us"), None)
            
            if uk_pron:
                await download_and_send_audio(
                    update, 
                    uk_pron["url"], 
                    f"🇬🇧 Британское произношение слова '{data['word']}'",
                    "UK"
                )
            
            if us_pron and (not uk_pron or us_pron["url"] != uk_pron["url"]):
                await download_and_send_audio(
                    update, 
                    us_pron["url"], 
                    f"🇺🇸 Американское произношение слова '{data['word']}'",
                    "US"
                )
    
    except requests.RequestException as e:
        logger.error(f"Ошибка при запросе к API: {e}")
        await update.message.reply_text("Ошибка при обращении к сервису словаря. Пожалуйста, попробуйте позже.")

def main() -> None:
    """Запуск бота."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_word))

    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()
