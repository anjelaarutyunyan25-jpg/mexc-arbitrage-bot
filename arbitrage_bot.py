import ccxt
import time
from datetime import datetime
import requests
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

# ========== ДЛЯ RENDER (HEALTH CHECK) ==========
PORT = int(os.environ.get('PORT', 10000))

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot is running')
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_health_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    print(f"✅ HTTP сервер запущен на порту {PORT}")
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

# ==================================================
# НАСТРОЙКИ TELEGRAM (ТОКЕН ИЗ ПЕРЕМЕННОЙ ОКРУЖЕНИЯ)
# ==================================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("❌ Переменная окружения TELEGRAM_TOKEN не установлена. Добавьте её на Render.")

TELEGRAM_CHAT_ID = "1540385721"  # Ваш личный ID
ENABLE_TELEGRAM = True

# ==================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ==================================================
bot1_mexc_running = True
bot1_bybit_running = True
bot2_mexc_running = True
bot2_bybit_running = True

exchange_mexc = None
exchange_bybit = None

# MEXC первый бот
mexc_spot = "BTC/USDT"
mexc_future = "BTC/USDT:USDT"
mexc_target = 5.0
mexc_interval = 120
mexc_last_alert = None
mexc_spread_history = []
mexc_current_data = None

# ByBit первый бот
bybit_spot = "BTC/USDT"
bybit_future = "BTC/USDT:USDT"
bybit_target = 0.5
bybit_interval = 120
bybit_last_alert = None
bybit_spread_history = []
bybit_current_data = None

# MEXC сканер
mexc_min_spread = 2.0
mexc_scan_interval = 10
mexc_last_signals = []

# ByBit сканер
bybit_min_spread = 0.5
bybit_scan_interval = 10
bybit_last_signals = []

# ==================================================
# ФУНКЦИИ TELEGRAM
# ==================================================
def send_telegram(message):
    if not ENABLE_TELEGRAM:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={'chat_id': TELEGRAM_CHAT_ID, 'text': message}, timeout=10)
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

# ==================================================
# ЛОГИКА MEXC (первый бот)
# ==================================================
def mexc_get_spread():
    global exchange_mexc, mexc_spot, mexc_future, mexc_current_data
    try:
        spot = exchange_mexc.fetch_order_book(mexc_spot)
        future = exchange_mexc.fetch_order_book(mexc_future)
        spot_ask = spot['asks'][0][0]
        spot_bid = spot['bids'][0][0]
        future_bid = future['bids'][0][0]
        future_ask = future['asks'][0][0]
        spread_long = ((future_bid - spot_ask) / spot_ask) * 100
        spread_short = ((spot_bid - future_ask) / future_ask) * 100
        if spread_long > spread_short:
            data = {
                'spread': spread_long,
                'action': 'Купить СПОТ → Продать ФЬЮЧЕРС'
            }
        else:
            data = {
                'spread': spread_short,
                'action': 'Купить ФЬЮЧЕРС → Продать СПОТ'
            }
        mexc_current_data = data
        return data
    except Exception as e:
        print(f"MEXC ошибка спреда: {e}")
        return None

def bot1_mexc_loop():
    global bot1_mexc_running, mexc_target, mexc_interval, mexc_last_alert, mexc_spread_history, mexc_current_data, exchange_mexc
    print("🚀 Запуск первого бота MEXC")
    send_telegram("✅ Первый бот MEXC запущен")
    exchange_mexc = ccxt.mexc({'enableRateLimit': True})
    exchange_mexc.load_markets()
    while True:
        if not bot1_mexc_running:
            time.sleep(2)
            continue
        try:
            data = mexc_get_spread()
            if data:
                spread = data['spread']
                mexc_spread_history.append(spread)
                if len(mexc_spread_history) > 20:
                    mexc_spread_history.pop(0)
                print(f"MEXC | {mexc_spot} | Спред: {spread:.2f}%")
                if spread <= mexc_target:
                    if mexc_last_alert != "target":
                        profit = spread - 0.15
                        msg = f"🎯 MEXC ЦЕЛЬ!\n{mexc_spot}\nСпред: {spread:.2f}%\nПрибыль: {profit:.2f}%"
                        send_telegram(msg)
                        mexc_last_alert = "target"
                else:
                    if spread <= mexc_target + 1.0 and mexc_last_alert != "close":
                        send_telegram(f"🔔 MEXC близко: {spread:.2f}%")
                        mexc_last_alert = "close"
                    elif spread > mexc_target + 2.0:
                        mexc_last_alert = None
            time.sleep(mexc_interval)
        except Exception as e:
            print(f"MEXC бот1 ошибка: {e}")
            time.sleep(mexc_interval)

# ==================================================
# ЛОГИКА BYBIT (первый бот)
# ==================================================
def bybit_get_spread():
    global exchange_bybit, bybit_spot, bybit_future, bybit_current_data
    try:
        spot = exchange_bybit.fetch_order_book(bybit_spot)
        future = exchange_bybit.fetch_order_book(bybit_future)
        spot_ask = spot['asks'][0][0]
        spot_bid = spot['bids'][0][0]
        future_bid = future['bids'][0][0]
        future_ask = future['asks'][0][0]
        spread_long = ((future_bid - spot_ask) / spot_ask) * 100
        spread_short = ((spot_bid - future_ask) / future_ask) * 100
        if spread_long > spread_short:
            data = {
                'spread': spread_long,
                'action': 'Купить СПОТ → Продать ФЬЮЧЕРС'
            }
        else:
            data = {
                'spread': spread_short,
                'action': 'Купить ФЬЮЧЕРС → Продать СПОТ'
            }
        bybit_current_data = data
        return data
    except Exception as e:
        print(f"ByBit ошибка спреда: {e}")
        return None

def bot1_bybit_loop():
    global bot1_bybit_running, bybit_target, bybit_interval, bybit_last_alert, bybit_spread_history, bybit_current_data, exchange_bybit
    print("🚀 Запуск первого бота ByBit")
    send_telegram("✅ Первый бот ByBit запущен")
    exchange_bybit = ccxt.bybit({
        'enableRateLimit': True,
        'options': {'defaultType': 'swap', 'defaultSubType': 'linear', 'defaultSettle': 'USDT'}
    })
    exchange_bybit.load_markets()
    while True:
        if not bot1_bybit_running:
            time.sleep(2)
            continue
        try:
            data = bybit_get_spread()
            if data:
                spread = data['spread']
                bybit_spread_history.append(spread)
                if len(bybit_spread_history) > 20:
                    bybit_spread_history.pop(0)
                print(f"ByBit | {bybit_spot} | Спред: {spread:.2f}%")
                if spread <= bybit_target:
                    if bybit_last_alert != "target":
                        profit = spread - 0.1
                        msg = f"🎯 ByBit ЦЕЛЬ!\n{bybit_spot}\nСпред: {spread:.2f}%\nПрибыль: {profit:.2f}%"
                        send_telegram(msg)
                        bybit_last_alert = "target"
                else:
                    if spread <= bybit_target + 0.5 and bybit_last_alert != "close":
                        send_telegram(f"🔔 ByBit близко: {spread:.2f}%")
                        bybit_last_alert = "close"
                    elif spread > bybit_target + 1.0:
                        bybit_last_alert = None
            time.sleep(bybit_interval)
        except Exception as e:
            print(f"ByBit бот1 ошибка: {e}")
            time.sleep(bybit_interval)

# ==================================================
# СКАНЕР MEXC
# ==================================================
def load_mexc_pairs():
    global exchange_mexc
    exchange_mexc.load_markets()
    spot_pairs = [s for s in exchange_mexc.markets if s.endswith('/USDT') and exchange_mexc.markets[s].get('spot') and exchange_mexc.markets[s].get('active')]
    trading_pairs = []
    for spot in spot_pairs:
        base = spot.replace('/USDT', '')
        future = f"{base}/USDT:USDT"
        if future in exchange_mexc.markets:
            trading_pairs.append({'spot': spot, 'future': future})
    return trading_pairs

def bot2_mexc_loop():
    global bot2_mexc_running, mexc_min_spread, mexc_scan_interval, mexc_last_signals, exchange_mexc
    print("🚀 Запуск сканера MEXC")
    send_telegram("✅ Сканер MEXC запущен")
    exchange_mexc = exchange_mexc or ccxt.mexc({'enableRateLimit': True})
    trading_pairs = load_mexc_pairs()
    cycle = 0
    while True:
        if not bot2_mexc_running:
            time.sleep(2)
            continue
        try:
            cycle += 1
            print(f"MEXC сканер цикл {cycle}, пар: {len(trading_pairs)}")
            for pair in trading_pairs:
                try:
                    spot = exchange_mexc.fetch_order_book(pair['spot'])
                    future = exchange_mexc.fetch_order_book(pair['future'])
                    spot_ask = spot['asks'][0][0]
                    spot_bid = spot['bids'][0][0]
                    future_bid = future['bids'][0][0]
                    future_ask = future['asks'][0][0]
                    if spot_ask < future_bid:
                        spread = ((future_bid - spot_ask) / spot_ask) * 100
                        if spread > mexc_min_spread:
                            net = spread - 0.15
                            msg = f"🚨 MEXC АРБИТРАЖ! {pair['spot']}\nСпред: {spread:.2f}%\nПрибыль: {net:.2f}%"
                            send_telegram(msg)
                            mexc_last_signals.append({'pair': pair['spot'], 'spread': spread, 'time': datetime.now().strftime('%H:%M:%S')})
                            if len(mexc_last_signals) > 10: mexc_last_signals.pop(0)
                    elif future_ask < spot_bid:
                        spread = ((spot_bid - future_ask) / future_ask) * 100
                        if spread > mexc_min_spread:
                            net = spread - 0.15
                            msg = f"🚨 MEXC АРБИТРАЖ! {pair['spot']}\nСпред: {spread:.2f}%\nПрибыль: {net:.2f}%"
                            send_telegram(msg)
                            mexc_last_signals.append({'pair': pair['spot'], 'spread': spread, 'time': datetime.now().strftime('%H:%M:%S')})
                            if len(mexc_last_signals) > 10: mexc_last_signals.pop(0)
                except:
                    pass
                time.sleep(0.03)
            time.sleep(mexc_scan_interval)
        except Exception as e:
            print(f"MEXC сканер ошибка: {e}")
            time.sleep(10)

# ==================================================
# СКАНЕР BYBIT
# ==================================================
def load_bybit_pairs():
    global exchange_bybit
    exchange_bybit.load_markets()
    spot_pairs = [s for s in exchange_bybit.markets if s.endswith('/USDT') and exchange_bybit.markets[s].get('spot') and exchange_bybit.markets[s].get('active')]
    trading_pairs = []
    for spot in spot_pairs:
        base = spot.replace('/USDT', '')
        future = f"{base}/USDT:USDT"
        if future in exchange_bybit.markets:
            trading_pairs.append({'spot': spot, 'future': future})
    return trading_pairs

def bot2_bybit_loop():
    global bot2_bybit_running, bybit_min_spread, bybit_scan_interval, bybit_last_signals, exchange_bybit
    print("🚀 Запуск сканера ByBit")
    send_telegram("✅ Сканер ByBit запущен")
    exchange_bybit = exchange_bybit or ccxt.bybit({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    trading_pairs = load_bybit_pairs()
    cycle = 0
    while True:
        if not bot2_bybit_running:
            time.sleep(2)
            continue
        try:
            cycle += 1
            print(f"ByBit сканер цикл {cycle}, пар: {len(trading_pairs)}")
            for pair in trading_pairs:
                try:
                    spot = exchange_bybit.fetch_order_book(pair['spot'])
                    future = exchange_bybit.fetch_order_book(pair['future'])
                    spot_ask = spot['asks'][0][0]
                    spot_bid = spot['bids'][0][0]
                    future_bid = future['bids'][0][0]
                    future_ask = future['asks'][0][0]
                    if spot_ask < future_bid:
                        spread = ((future_bid - spot_ask) / spot_ask) * 100
                        if spread > bybit_min_spread:
                            net = spread - 0.1
                            msg = f"🚨 ByBit АРБИТРАЖ! {pair['spot']}\nСпред: {spread:.2f}%\nПрибыль: {net:.2f}%"
                            send_telegram(msg)
                            bybit_last_signals.append({'pair': pair['spot'], 'spread': spread, 'time': datetime.now().strftime('%H:%M:%S')})
                            if len(bybit_last_signals) > 10: bybit_last_signals.pop(0)
                    elif future_ask < spot_bid:
                        spread = ((spot_bid - future_ask) / future_ask) * 100
                        if spread > bybit_min_spread:
                            net = spread - 0.1
                            msg = f"🚨 ByBit АРБИТРАЖ! {pair['spot']}\nСпред: {spread:.2f}%\nПрибыль: {net:.2f}%"
                            send_telegram(msg)
                            bybit_last_signals.append({'pair': pair['spot'], 'spread': spread, 'time': datetime.now().strftime('%H:%M:%S')})
                            if len(bybit_last_signals) > 10: bybit_last_signals.pop(0)
                except:
                    pass
                time.sleep(0.03)
            time.sleep(bybit_scan_interval)
        except Exception as e:
            print(f"ByBit сканер ошибка: {e}")
            time.sleep(10)

# ==================================================
# ОБРАБОТЧИК КОМАНД
# ==================================================
def handle_commands():
    global bot1_mexc_running, bot1_bybit_running, bot2_mexc_running, bot2_bybit_running
    global mexc_spot, mexc_future, mexc_target, mexc_interval
    global bybit_spot, bybit_future, bybit_target, bybit_interval
    global mexc_min_spread, mexc_scan_interval, bybit_min_spread, bybit_scan_interval
    global mexc_current_data, bybit_current_data

    update_id = None
    while True:
        try:
            updates = get_updates(update_id)
            for upd in updates:
                update_id = upd.get('update_id', 0) + 1
                msg = upd.get('message')
                if not msg:
                    continue
                chat_id = msg['chat']['id']
                text = msg.get('text', '').strip().lower()
                if not text.startswith('/'):
                    continue

                if text == '/start':
                    bot1_mexc_running = bot1_bybit_running = bot2_mexc_running = bot2_bybit_running = True
                    send_telegram_to_chat(chat_id, "✅ Все боты запущены")
                    continue
                if text == '/stop':
                    bot1_mexc_running = bot1_bybit_running = bot2_mexc_running = bot2_bybit_running = False
                    send_telegram_to_chat(chat_id, "⏸ Все боты остановлены")
                    continue

                # MEXC первый бот
                if text == '/start1m':
                    bot1_mexc_running = True
                    send_telegram_to_chat(chat_id, "✅ Первый бот MEXC запущен")
                    continue
                if text == '/stop1m':
                    bot1_mexc_running = False
                    send_telegram_to_chat(chat_id, "⏸ Первый бот MEXC остановлен")
                    continue
                if text.startswith('/set1m '):
                    coin = text.replace('/set1m ', '').upper()
                    spot = f"{coin}/USDT"
                    future = f"{coin}/USDT:USDT"
                    try:
                        exchange_mexc.load_markets(reload=True)
                        if spot in exchange_mexc.markets and future in exchange_mexc.markets:
                            mexc_spot = spot
                            mexc_future = future
                            send_telegram_to_chat(chat_id, f"✅ MEXC пара изменена на {mexc_spot}")
                        else:
                            send_telegram_to_chat(chat_id, f"❌ Пара {coin} не найдена на MEXC")
                    except:
                        send_telegram_to_chat(chat_id, "❌ Ошибка проверки пары")
                    continue
                if text.startswith('/target1m '):
                    try:
                        val = float(text.split()[1])
                        if 0.3 <= val <= 9:
                            mexc_target = val
                            send_telegram_to_chat(chat_id, f"✅ MEXC цель: {mexc_target}%")
                        else:
                            send_telegram_to_chat(chat_id, "❌ От 0.3 до 9")
                    except:
                        send_telegram_to_chat(chat_id, "❌ Пример: /target1m 5")
                    continue
                if text.startswith('/interval1m '):
                    try:
                        val = int(text.split()[1])
                        if 10 <= val <= 600:
                            mexc_interval = val
                            send_telegram_to_chat(chat_id, f"✅ MEXC интервал: {mexc_interval} сек")
                        else:
                            send_telegram_to_chat(chat_id, "❌ От 10 до 600")
                    except:
                        send_telegram_to_chat(chat_id, "❌ Пример: /interval1m 120")
                    continue
                if text == '/status1m':
                    status = "✅ работает" if bot1_mexc_running else "⏸ остановлен"
                    try:
                        if mexc_current_data:
                            spread = mexc_current_data['spread']
                            action = mexc_current_data['action']
                        else:
                            data = mexc_get_spread()
                            if data:
                                spread = data['spread']
                                action = data['action']
                            else:
                                spread = "нет данных"
                                action = "нет данных"
                        msg = f"""
📊 <b>СТАТУС MEXC (бот #1)</b>
━━━━━━━━━━━━━━━━━━━━━
<b>Состояние:</b> {status}
<b>Пара спот:</b> {mexc_spot}
<b>Пара фьюч:</b> {mexc_future}
<b>Цель (спред):</b> {mexc_target}%
<b>Интервал:</b> {mexc_interval} сек

🔄 <b>Арбитраж:</b>
Текущий спред: {spread}%
Направление: {action}
"""
                        if spread != 'нет данных' and spread <= mexc_target:
                            msg += "🎯 <b>ЦЕЛЬ ДОСТИГНУТА!</b>"
                        elif spread != 'нет данных':
                            need = spread - mexc_target
                            msg += f"📉 До цели: {need:.2f}%"
                        else:
                            msg += "⏳ Данные ещё не получены"
                    except Exception as e:
                        msg = f"❌ Ошибка: {e}"
                    send_telegram_to_chat(chat_id, msg)
                    continue

                # ByBit первый бот
                if text == '/start1b':
                    bot1_bybit_running = True
                    send_telegram_to_chat(chat_id, "✅ Первый бот ByBit запущен")
                    continue
                if text == '/stop1b':
                    bot1_bybit_running = False
                    send_telegram_to_chat(chat_id, "⏸ Первый бот ByBit остановлен")
                    continue
                if text.startswith('/set1b '):
                    coin = text.replace('/set1b ', '').upper()
                    spot = f"{coin}/USDT"
                    future = f"{coin}/USDT:USDT"
                    try:
                        exchange_bybit.load_markets(reload=True)
                        if spot in exchange_bybit.markets and future in exchange_bybit.markets:
                            bybit_spot = spot
                            bybit_future = future
                            send_telegram_to_chat(chat_id, f"✅ ByBit пара изменена на {bybit_spot}")
                        else:
                            send_telegram_to_chat(chat_id, f"❌ Пара {coin} не найдена на ByBit")
                    except:
                        send_telegram_to_chat(chat_id, "❌ Ошибка проверки пары")
                    continue
                if text.startswith('/target1b '):
                    try:
                        val = float(text.split()[1])
                        if 0.1 <= val <= 9:
                            bybit_target = val
                            send_telegram_to_chat(chat_id, f"✅ ByBit цель: {bybit_target}%")
                        else:
                            send_telegram_to_chat(chat_id, "❌ От 0.1 до 9")
                    except:
                        send_telegram_to_chat(chat_id, "❌ Пример: /target1b 0.5")
                    continue
                if text.startswith('/interval1b '):
                    try:
                        val = int(text.split()[1])
                        if 10 <= val <= 600:
                            bybit_interval = val
                            send_telegram_to_chat(chat_id, f"✅ ByBit интервал: {bybit_interval} сек")
                        else:
                            send_telegram_to_chat(chat_id, "❌ От 10 до 600")
                    except:
                        send_telegram_to_chat(chat_id, "❌ Пример: /interval1b 120")
                    continue
                if text == '/status1b':
                    status = "✅ работает" if bot1_bybit_running else "⏸ остановлен"
                    try:
                        if bybit_current_data:
                            spread = bybit_current_data['spread']
                            action = bybit_current_data['action']
                        else:
                            data = bybit_get_spread()
                            if data:
                                spread = data['spread']
                                action = data['action']
                            else:
                                spread = "нет данных"
                                action = "нет данных"
                        msg = f"""
📊 <b>СТАТУС ByBit (бот #1)</b>
━━━━━━━━━━━━━━━━━━━━━
<b>Состояние:</b> {status}
<b>Пара спот:</b> {bybit_spot}
<b>Пара фьюч:</b> {bybit_future}
<b>Цель (спред):</b> {bybit_target}%
<b>Интервал:</b> {bybit_interval} сек

🔄 <b>Арбитраж:</b>
Текущий спред: {spread}%
Направление: {action}
"""
                        if spread != 'нет данных' and spread <= bybit_target:
                            msg += "🎯 <b>ЦЕЛЬ ДОСТИГНУТА!</b>"
                        elif spread != 'нет данных':
                            need = spread - bybit_target
                            msg += f"📉 До цели: {need:.2f}%"
                        else:
                            msg += "⏳ Данные ещё не получены"
                    except Exception as e:
                        msg = f"❌ Ошибка: {e}"
                    send_telegram_to_chat(chat_id, msg)
                    continue

                # Сканеры
                if text == '/start2m':
                    bot2_mexc_running = True
                    send_telegram_to_chat(chat_id, "✅ Сканер MEXC запущен")
                    continue
                if text == '/stop2m':
                    bot2_mexc_running = False
                    send_telegram_to_chat(chat_id, "⏸ Сканер MEXC остановлен")
                    continue
                if text.startswith('/threshold2m '):
                    try:
                        val = float(text.split()[1])
                        if 0.5 <= val <= 10:
                            mexc_min_spread = val
                            send_telegram_to_chat(chat_id, f"✅ MEXC мин. спред: {mexc_min_spread}%")
                        else:
                            send_telegram_to_chat(chat_id, "❌ От 0.5 до 10")
                    except:
                        send_telegram_to_chat(chat_id, "❌ Пример: /threshold2m 2.0")
                    continue
                if text.startswith('/interval2m '):
                    try:
                        val = int(text.split()[1])
                        if 10 <= val <= 300:
                            mexc_scan_interval = val
                            send_telegram_to_chat(chat_id, f"✅ MEXC интервал сканирования: {mexc_scan_interval} сек")
                        else:
                            send_telegram_to_chat(chat_id, "❌ От 10 до 300")
                    except:
                        send_telegram_to_chat(chat_id, "❌ Пример: /interval2m 60")
                    continue
                if text == '/status2m':
                    status = "✅ работает" if bot2_mexc_running else "⏸ остановлен"
                    msg = f"📊 Сканер MEXC: {status}\nМин. спред: {mexc_min_spread}%\nИнтервал: {mexc_scan_interval} сек\nСигналов: {len(mexc_last_signals)}"
                    if mexc_last_signals:
                        msg += "\n🔔 Последние сигналы:\n"
                        for s in mexc_last_signals[-5:]:
                            msg += f"{s['pair']}: {s['spread']:.2f}% в {s['time']}\n"
                    else:
                        msg += "\n📭 Нет сигналов"
                    send_telegram_to_chat(chat_id, msg)
                    continue
                if text == '/last2m':
                    if not mexc_last_signals:
                        send_telegram_to_chat(chat_id, "📭 Нет сигналов MEXC")
                    else:
                        msg = "🔔 Последние сигналы MEXC:\n"
                        for s in mexc_last_signals[-5:]:
                            msg += f"{s['pair']}: {s['spread']:.2f}% в {s['time']}\n"
                        send_telegram_to_chat(chat_id, msg)
                    continue

                if text == '/start2b':
                    bot2_bybit_running = True
                    send_telegram_to_chat(chat_id, "✅ Сканер ByBit запущен")
                    continue
                if text == '/stop2b':
                    bot2_bybit_running = False
                    send_telegram_to_chat(chat_id, "⏸ Сканер ByBit остановлен")
                    continue
                if text.startswith('/threshold2b '):
                    try:
                        val = float(text.split()[1])
                        if 0.2 <= val <= 10:
                            bybit_min_spread = val
                            send_telegram_to_chat(chat_id, f"✅ ByBit мин. спред: {bybit_min_spread}%")
                        else:
                            send_telegram_to_chat(chat_id, "❌ От 0.2 до 10")
                    except:
                        send_telegram_to_chat(chat_id, "❌ Пример: /threshold2b 0.5")
                    continue
                if text.startswith('/interval2b '):
                    try:
                        val = int(text.split()[1])
                        if 10 <= val <= 300:
                            bybit_scan_interval = val
                            send_telegram_to_chat(chat_id, f"✅ ByBit интервал сканирования: {bybit_scan_interval} сек")
                        else:
                            send_telegram_to_chat(chat_id, "❌ От 10 до 300")
                    except:
                        send_telegram_to_chat(chat_id, "❌ Пример: /interval2b 60")
                    continue
                if text == '/status2b':
                    status = "✅ работает" if bot2_bybit_running else "⏸ остановлен"
                    msg = f"📊 Сканер ByBit: {status}\nМин. спред: {bybit_min_spread}%\nИнтервал: {bybit_scan_interval} сек\nСигналов: {len(bybit_last_signals)}"
                    if bybit_last_signals:
                        msg += "\n🔔 Последние сигналы:\n"
                        for s in bybit_last_signals[-5:]:
                            msg += f"{s['pair']}: {s['spread']:.2f}% в {s['time']}\n"
                    else:
                        msg += "\n📭 Нет сигналов"
                    send_telegram_to_chat(chat_id, msg)
                    continue
                if text == '/last2b':
                    if not bybit_last_signals:
                        send_telegram_to_chat(chat_id, "📭 Нет сигналов ByBit")
                    else:
                        msg = "🔔 Последние сигналы ByBit:\n"
                        for s in bybit_last_signals[-5:]:
                            msg += f"{s['pair']}: {s['spread']:.2f}% в {s['time']}\n"
                        send_telegram_to_chat(chat_id, msg)
                    continue

                if text == '/help':
                    help_txt = """
<b>🤖 Управление объединённым ботом (MEXC + ByBit)</b>

<b>Глобальные:</b>
/start – запустить все боты
/stop – остановить все

<b>Первый бот (одна пара) MEXC:</b>
/start1m, /stop1m
/set1m BTC, /target1m 5, /interval1m 120, /status1m

<b>Первый бот (одна пара) ByBit:</b>
/start1b, /stop1b
/set1b BTC, /target1b 0.5, /interval1b 120, /status1b

<b>Сканер MEXC:</b>
/start2m, /stop2m, /status2m, /threshold2m 2.0, /interval2m 60, /last2m

<b>Сканер ByBit:</b>
/start2b, /stop2b, /status2b, /threshold2b 0.5, /interval2b 60, /last2b
"""
                    send_telegram_to_chat(chat_id, help_txt)
                    continue

                send_telegram_to_chat(chat_id, "❌ Неизвестная команда. /help")
            time.sleep(1)
        except Exception as e:
            print(f"Ошибка в обработчике: {e}")
            time.sleep(5)

# ==================================================
# ЗАПУСК
# ==================================================
if __name__ == "__main__":
    print("="*60)
    print("ОБЪЕДИНЁННЫЙ АРБИТРАЖНЫЙ БОТ (MEXC + ByBit) – БЕЗ ПАРОЛЯ, СТАТУСЫ УПРОЩЕНЫ")
    print("="*60)
    exchange_mexc = ccxt.mexc({'enableRateLimit': True})
    exchange_bybit = ccxt.bybit({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
    def load_markets_async():
        global exchange_mexc, exchange_bybit
        exchange_mexc.load_markets()
        exchange_bybit.load_markets()
    threading.Thread(target=load_markets_async, daemon=True).start()
    threading.Thread(target=bot1_mexc_loop, daemon=True).start()
    threading.Thread(target=bot1_bybit_loop, daemon=True).start()
    threading.Thread(target=bot2_mexc_loop, daemon=True).start()
    threading.Thread(target=bot2_bybit_loop, daemon=True).start()
    handle_commands()
