import ccxt
import time
from datetime import datetime
import requests
import threading
import re
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

# ========== ДЛЯ RENDER / UPTIMEROBOT (HEALTH CHECK) ==========
PORT = int(os.environ.get('PORT', 10000))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running')
    
    def do_HEAD(self):
        # Просто отвечаем 200 без тела – всё, что нужно UptimeRobot
        self.send_response(200)
        self.end_headers()

def run_health_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    print(f"✅ HTTP сервер запущен на порту {PORT}")
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()
# ================================================================

# ==================================================
# НАСТРОЙКИ (БЕЗ ИЗМЕНЕНИЙ, КАК БЫЛО)
# ==================================================

TELEGRAM_TOKEN = "8751313465:AAEKdudEaxKwNcwpB2FSThSRkut7L4KRvSI"
TELEGRAM_CHAT_ID = "1540385721"
ENABLE_TELEGRAM = True

SPOT_SYMBOL = "BTC/USDT"
FUTURES_SYMBOL = "BTC/USDT:USDT"

TARGET_SPREAD_PERCENT = 5
CHECK_INTERVAL = 120
ALERT_LEVELS = [1.0, 0.8, 0.6, 0.5]

# ==================================================

last_alert = None
current_spread_data = None
bot_running = True
spread_history = []
exchange = None

def send_telegram(message):
    if not ENABLE_TELEGRAM:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={'chat_id': TELEGRAM_CHAT_ID, 'text': message}, timeout=10)
        print("✅ Telegram отправлен")
    except Exception as e:
        print(f"❌ Telegram error: {e}")

def send_telegram_to_chat(chat_id, message, reply_markup=None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}
        if reply_markup:
            payload['reply_markup'] = reply_markup
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def get_updates(offset=None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        params = {'timeout': 30, 'offset': offset}
        response = requests.get(url, params=params, timeout=35)
        return response.json().get('result', [])
    except Exception as e:
        print(f"❌ Ошибка получения обновлений: {e}")
        return []

def is_valid_pair(coin_symbol):
    global exchange
    try:
        exchange.load_markets(reload=True)
        spot_pair = f"{coin_symbol}/USDT"
        future_pair = f"{coin_symbol}/USDT:USDT"
        if spot_pair in exchange.markets and future_pair in exchange.markets:
            return True, spot_pair, future_pair
        return False, None, None
    except Exception as e:
        print(f"Ошибка проверки пары: {e}")
        return False, None, None

def handle_command(text, chat_id):
    global SPOT_SYMBOL, FUTURES_SYMBOL, TARGET_SPREAD_PERCENT, CHECK_INTERVAL, last_alert, spread_history

    text = text.strip().lower()
    print(f"📩 Получена команда: {text}")

    # Клавиатура
    main_keyboard = {
        "keyboard": [
            ["/status", "/check"],
            ["/set BTC", "/set ETH", "/set SOL"],
            ["/target", "/interval", "/pairs"],
            ["/reset", "/clean", "/help"]
        ],
        "resize_keyboard": True
    }
    hide_keyboard = {"remove_keyboard": True}

    if text == '/start':
        message = f"""
🤖 <b>АРБИТРАЖНЫЙ БОТ MEXC</b>

📊 <b>Текущая пара:</b> {SPOT_SYMBOL}
🎯 <b>Цель:</b> {TARGET_SPREAD_PERCENT}%
⏰ <b>Интервал:</b> {CHECK_INTERVAL} сек

<b>Команды доступны по кнопкам ↓</b>
"""
        send_telegram_to_chat(chat_id, message, reply_markup=main_keyboard)
        return True

    elif text == '/help':
        message = """
📚 <b>Помощь</b>

/set BTC – сменить пару (Bitcoin)
/set ETH – Ethereum  
/set SOL – Solana
/set VANRY – Vanry
/status – текущий спред
/check – проверить статус пары
/target 5 – установить цель (%)
/interval 30 – интервал проверки
/pairs – список популярных пар
/reset – сбросить историю
/clean – очистить бота
/hide – скрыть клавиатуру
"""
        send_telegram_to_chat(chat_id, message, reply_markup=main_keyboard)
        return True

    elif text == '/hide':
        send_telegram_to_chat(chat_id, "⌨️ Клавиатура скрыта. /start – показать.", reply_markup=hide_keyboard)
        return True

    elif text == '/pairs':
        message = """
📋 <b>ПОПУЛЯРНЫЕ ПАРЫ НА MEXC</b>

Основные: BTC, ETH, SOL, XRP, DOGE, ADA
Альткоины: MATIC, DOT, AVAX, LINK, LTC, UNI
Мемкоины: PEPE, SHIB, DOGE, WIF, FLOKI
Новые: WLD, SUI, TON, APT, ARB, OP, VANRY

💡 Используйте: /set НАЗВАНИЕ (например /set VANRY)
"""
        send_telegram_to_chat(chat_id, message)
        return True

    elif text == '/status':
        if current_spread_data:
            spread = current_spread_data.get('spread', 0)
            need = spread - TARGET_SPREAD_PERCENT
            if spread <= TARGET_SPREAD_PERCENT:
                status = "✅ ЦЕЛЬ ДОСТИГНУТА!"
            else:
                status = f"📉 Нужно снижение: {need:.2f}%"

            trend_text = ""
            if len(spread_history) >= 2:
                trend = spread_history[-1] - spread_history[-2]
                if trend < -0.05:
                    trend_text = "📉 Спред снижается"
                elif trend > 0.05:
                    trend_text = "📈 Спред растет"
                else:
                    trend_text = "➡️ Спред стабилен"

            message = f"""
📊 <b>СТАТУС БОТА</b>

<b>Пара:</b> {SPOT_SYMBOL}
<b>Текущий спред:</b> {spread:+.2f}%
<b>Цель:</b> {TARGET_SPREAD_PERCENT}%
<b>Статус:</b> {status}
<b>Тренд:</b> {trend_text}
<b>Интервал:</b> {CHECK_INTERVAL} сек
<b>Действие:</b> {current_spread_data.get('action', '-')}
"""
        else:
            message = "⏳ Данные еще не получены, подождите..."
        send_telegram_to_chat(chat_id, message)
        return True

    elif text == '/check':
        send_telegram_to_chat(chat_id, "🔍 Проверка статуса пары...")
        try:
            exchange.load_markets(reload=True)
            spot_ok = SPOT_SYMBOL in exchange.markets and exchange.markets[SPOT_SYMBOL].get('active')
            fut_ok = FUTURES_SYMBOL in exchange.markets and exchange.markets[FUTURES_SYMBOL].get('active')
            coin = SPOT_SYMBOL.replace('/USDT', '')
            if spot_ok and fut_ok:
                spot = exchange.fetch_order_book(SPOT_SYMBOL)
                fut = exchange.fetch_order_book(FUTURES_SYMBOL)
                spread = ((fut['bids'][0][0] - spot['asks'][0][0]) / spot['asks'][0][0]) * 100
                message = f"✅ Пара {coin} активна\nСпред: {spread:+.2f}%\nЦель: {TARGET_SPREAD_PERCENT}%"
                if spread <= TARGET_SPREAD_PERCENT:
                    profit = spread - 0.15
                    message += f"\n💰 ЦЕЛЬ! Прибыль: {profit:.2f}%"
            else:
                message = f"⚠️ Пара {coin} неактивна\nСпот: {'✅' if spot_ok else '❌'}\nФьючерс: {'✅' if fut_ok else '❌'}"
        except Exception as e:
            message = f"❌ Ошибка: {e}"
        send_telegram_to_chat(chat_id, message)
        return True

    elif text == '/reset':
        spread_history = []
        message = "✅ История спреда сброшена!"
        send_telegram_to_chat(chat_id, message)
        return True

    elif text == '/clean':
        spread_history = []
        last_alert = None
        message = "🧹 Бот очищен!"
        send_telegram_to_chat(chat_id, message)
        return True

    elif text.startswith('/set '):
        coin = text.replace('/set ', '').upper().strip()
        send_telegram_to_chat(chat_id, f"🔍 Проверяю {coin}...")
        is_valid, spot_pair, future_pair = is_valid_pair(coin)
        if is_valid:
            old_pair = SPOT_SYMBOL
            SPOT_SYMBOL = spot_pair
            FUTURES_SYMBOL = future_pair
            last_alert = None
            spread_history = []
            message = f"""
✅ <b>ПАРА ИЗМЕНЕНА!</b>

<b>Было:</b> {old_pair}
<b>Стало:</b> {SPOT_SYMBOL}
🎯 <b>Цель:</b> {TARGET_SPREAD_PERCENT}%
⏰ <b>Интервал:</b> {CHECK_INTERVAL} сек

<i>Отслеживание начато...</i>
"""
            send_telegram_to_chat(chat_id, message)
        else:
            message = f"❌ ПАРА {coin} НЕ НАЙДЕНА\n💡 /pairs - список популярных пар"
            send_telegram_to_chat(chat_id, message)
        return True

    elif text.startswith('/target '):
        try:
            new_target = float(text.replace('/target ', ''))
            if 0.3 <= new_target <= 9.0:
                TARGET_SPREAD_PERCENT = new_target
                message = f"✅ Цель изменена: {TARGET_SPREAD_PERCENT}%"
                send_telegram_to_chat(chat_id, message)
            else:
                message = "❌ Значение должно быть от 0.3 до 5.0"
                send_telegram_to_chat(chat_id, message)
        except:
            message = "❌ Неверный формат. Пример: /target 5"
            send_telegram_to_chat(chat_id, message)
        return True

    elif text.startswith('/interval '):
        try:
            new_interval = int(text.replace('/interval ', ''))
            if 5 <= new_interval <= 300:
                CHECK_INTERVAL = new_interval
                message = f"✅ Интервал изменен: {CHECK_INTERVAL} сек"
                send_telegram_to_chat(chat_id, message)
            else:
                message = "❌ Значение должно быть от 5 до 300"
                send_telegram_to_chat(chat_id, message)
        except:
            message = "❌ Неверный формат. Пример: /interval 30"
            send_telegram_to_chat(chat_id, message)
        return True

    else:
        if text.startswith('/'):
            send_telegram_to_chat(chat_id, f"❌ Неизвестная команда: {text}\n/help", reply_markup=main_keyboard)
        return False

def telegram_polling():
    update_id = None
    while bot_running:
        try:
            updates = get_updates(update_id)
            for update in updates:
                update_id = update.get('update_id', 0) + 1
                if 'message' in update:
                    message = update['message']
                    chat_id = message['chat']['id']
                    text = message.get('text', '')
                    if text.startswith('/'):
                        handle_command(text, chat_id)
            time.sleep(1)
        except Exception as e:
            print(f"❌ Ошибка в polling: {e}")
            time.sleep(5)

# ==================================================
# ПОДКЛЮЧЕНИЕ К БИРЖЕ И ОСНОВНОЙ КОД
# ==================================================

print("🚀 ЗАПУСК АРБИТРАЖНОГО БОТА MEXC")
print("="*50)
print("📡 Подключение к MEXC...")

exchange = ccxt.mexc({'enableRateLimit': True})
print("📡 Загрузка рынков...")
exchange.load_markets()
print("✅ Биржа подключена!")

def get_spread():
    try:
        spot = exchange.fetch_order_book(SPOT_SYMBOL)
        future = exchange.fetch_order_book(FUTURES_SYMBOL)
        spot_ask = spot['asks'][0][0]
        spot_bid = spot['bids'][0][0]
        future_bid = future['bids'][0][0]
        future_ask = future['asks'][0][0]
        spread_long = ((future_bid - spot_ask) / spot_ask) * 100
        spread_short = ((spot_bid - future_ask) / future_ask) * 100
        if spread_long > spread_short:
            return {
                'spread': spread_long,
                'action': 'Купить СПОТ → Продать ФЬЮЧЕРС',
                'buy_price': spot_ask,
                'sell_price': future_bid
            }
        else:
            return {
                'spread': spread_short,
                'action': 'Купить ФЬЮЧЕРС → Продать СПОТ',
                'buy_price': future_ask,
                'sell_price': spot_bid
            }
    except Exception as e:
        print(f"❌ Ошибка получения спреда: {e}")
        return None

# Запускаем Telegram polling
telegram_thread = threading.Thread(target=telegram_polling, daemon=True)
telegram_thread.start()

send_telegram(f"✅ АРБИТРАЖНЫЙ БОТ ЗАПУЩЕН!\n\n📊 Слежу за {SPOT_SYMBOL}\n🎯 Цель: {TARGET_SPREAD_PERCENT}%\n\n💡 /set ЛЮБАЯ_МОНЕТА - сменить пару\n📋 /help - все команды")

print(f"\n📊 Текущая пара: {SPOT_SYMBOL}")
print(f"🎯 Цель: {TARGET_SPREAD_PERCENT}%")
print(f"⏰ Интервал: {CHECK_INTERVAL} сек")
print("="*50)
print(f"\n📊 Начинаю отслеживание...")
print("="*50)

# ==================================================
# ОСНОВНОЙ ЦИКЛ
# ==================================================

while True:
    try:
        data = get_spread()
        if data:
            current_spread_data = data
            spread = data['spread']
            now = datetime.now().strftime('%H:%M:%S')
            spread_history.append(spread)
            if len(spread_history) > 20:
                spread_history.pop(0)
            print(f"🕐 {now} | {SPOT_SYMBOL} | Спред: {spread:+.2f}%", end="")
            if spread <= TARGET_SPREAD_PERCENT:
                print(" 🎯 ЦЕЛЬ ДОСТИГНУТА!")
                if last_alert != "target":
                    profit = spread - 0.15
                    msg = f"""
🎯 <b>ЦЕЛЬ ДОСТИГНУТА!</b> 🎯
━━━━━━━━━━━━━━━━━━━━━
📊 {SPOT_SYMBOL}
📈 <b>Спред:</b> {spread:+.2f}%
💰 <b>Чистая прибыль:</b> {profit:.2f}%
⚡ {data['action']}
━━━━━━━━━━━━━━━━━━━━━
⚡ ДЕЙСТВУЙТЕ БЫСТРО!
"""
                    send_telegram(msg)
                    last_alert = "target"
            else:
                need = spread - TARGET_SPREAD_PERCENT
                print(f" | Нужно снижение: {need:.2f}%")
                for level in ALERT_LEVELS:
                    if spread <= level and last_alert != level:
                        msg = f"🔔 {SPOT_SYMBOL}\nСпред снизился до {level}%\nТекущий: {spread:+.2f}%\nОсталось до цели: {need:.2f}%"
                        send_telegram(msg)
                        last_alert = level
                        break
                if spread > max(ALERT_LEVELS) + 0.3:
                    last_alert = None
        time.sleep(CHECK_INTERVAL)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        time.sleep(CHECK_INTERVAL)
