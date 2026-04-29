import ccxt
import time
from datetime import datetime
import requests
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

# ========== ДЛЯ RENDER / UPTIMEROBOT (HEALTH CHECK) ==========
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
# НАСТРОЙКИ ТЕЛЕГРАМ (ОБЩИЕ)
# ==================================================
TELEGRAM_TOKEN = "8751313465:AAEKdudEaxKwNcwpB2FSThSRkut7L4KRvSI"
TELEGRAM_CHAT_ID = "1540385721"  # Ваш личный ID (для уведомлений)
ENABLE_TELEGRAM = True

# ========== ЗАЩИТА ПАРОЛЕМ ==========
SECRET_PASSWORD = "MySecretPass123"   # Смените на свой пароль
authorized_users = set()
pending_password = {}

def is_authorized(chat_id):
    return chat_id in authorized_users

def start_password_flow(chat_id):
    pending_password[chat_id] = True
    send_telegram_to_chat(chat_id, "🔐 Введите пароль для доступа к боту:")

def check_password(chat_id, text):
    if text == SECRET_PASSWORD:
        authorized_users.add(chat_id)
        pending_password.pop(chat_id, None)
        send_telegram_to_chat(chat_id, "✅ Доступ разрешён! Теперь вы можете пользоваться ботом.\nОтправьте /start1 для первого бота или /help2 для второго.")
        return True
    else:
        send_telegram_to_chat(chat_id, "❌ Неверный пароль. Доступ запрещён.\nПопробуйте снова командой /register")
        pending_password.pop(chat_id, None)
        return False

# ==================================================
# ПЕРВЫЙ БОТ (АРБИТРАЖ ПО ОДНОЙ ПАРЕ) – ByBit
# ==================================================
spot_symbol = "BTC/USDT"
futures_symbol = "BTC/USDT:USDT"
target_spread_percent = 0.5
check_interval = 120
alert_levels = [0.4, 0.3, 0.2, 0.1]

last_alert = None
current_spread_data = None
bot1_running = True
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

def handle_command_bot1(text, chat_id):
    global spot_symbol, futures_symbol, target_spread_percent, check_interval, last_alert, spread_history, bot1_running

    text = text.strip().lower()
    print(f"📩 БОТ1 команда: {text}")

    # Клавиатура
    main_keyboard = {
        "keyboard": [
            ["/status1", "/check1"],
            ["/set1 BTC", "/set1 ETH", "/set1 SOL"],
            ["/target1", "/interval1", "/pairs1"],
            ["/reset1", "/clean1", "/help1"]
        ],
        "resize_keyboard": True
    }
    hide_keyboard = {"remove_keyboard": True}

    if text == '/start':
        # Запуск цикла бота #1
        bot1_running = True
        send_telegram_to_chat(chat_id, "✅ Бот #1 запущен (мониторинг возобновлён)")
        return True

    elif text == '/stop':
        # Остановка цикла бота #1
        bot1_running = False
        send_telegram_to_chat(chat_id, "⏸ Бот #1 остановлен. /start1 - возобновить")
        return True

    elif text == '/help':
        message = """
📚 <b>Помощь (бот #1 - арбитраж по одной паре ByBit)</b>

/start1 – запустить мониторинг (если остановлен)
/stop1 – остановить мониторинг
/set1 BTC – сменить пару
/status1 – текущий спред
/check1 – проверить статус пары
/target1 0.5 – установить цель (%)
/interval1 30 – интервал проверки (сек)
/pairs1 – список популярных пар
/reset1 – сбросить историю
/clean1 – очистить бота
/hide1 – скрыть клавиатуру
"""
        send_telegram_to_chat(chat_id, message, reply_markup=main_keyboard)
        return True

    elif text == '/hide':
        send_telegram_to_chat(chat_id, "⌨️ Клавиатура скрыта. /help1 – показать.", reply_markup=hide_keyboard)
        return True

    elif text == '/pairs':
        message = """
📋 <b>ПОПУЛЯРНЫЕ ПАРЫ НА ByBit</b>

Основные: BTC, ETH, SOL, XRP, DOGE, ADA
Альткоины: MATIC, DOT, AVAX, LINK, LTC, UNI
Мемкоины: PEPE, SHIB, DOGE, WIF, FLOKI
Новые: WLD, SUI, TON, APT, ARB, OP, VANRY

💡 Используйте: /set1 НАЗВАНИЕ (например /set1 VANRY)
"""
        send_telegram_to_chat(chat_id, message)
        return True

    elif text == '/status':
        if current_spread_data:
            spread = current_spread_data.get('spread', 0)
            need = spread - target_spread_percent
            if spread <= target_spread_percent:
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
            state = "✅ РАБОТАЕТ" if bot1_running else "⏸ ОСТАНОВЛЕН"
            message = f"""
📊 <b>СТАТУС БОТА #1</b>

<b>Пара:</b> {spot_symbol}
<b>Текущий спред:</b> {spread:+.2f}%
<b>Цель:</b> {target_spread_percent}%
<b>Статус:</b> {status}
<b>Тренд:</b> {trend_text}
<b>Интервал:</b> {check_interval} сек
<b>Действие:</b> {current_spread_data.get('action', '-')}
<b>Состояние:</b> {state}
"""
        else:
            message = "⏳ Данные еще не получены, подождите..."
        send_telegram_to_chat(chat_id, message)
        return True

    elif text == '/check':
        send_telegram_to_chat(chat_id, "🔍 Проверка статуса пары...")
        try:
            exchange.load_markets(reload=True)
            spot_ok = spot_symbol in exchange.markets and exchange.markets[spot_symbol].get('active')
            fut_ok = futures_symbol in exchange.markets and exchange.markets[futures_symbol].get('active')
            coin = spot_symbol.replace('/USDT', '')
            if spot_ok and fut_ok:
                spot_book = exchange.fetch_order_book(spot_symbol)
                fut_book = exchange.fetch_order_book(futures_symbol)
                spread = ((fut_book['bids'][0][0] - spot_book['asks'][0][0]) / spot_book['asks'][0][0]) * 100
                message = f"✅ Пара {coin} активна\nСпред: {spread:+.2f}%\nЦель: {target_spread_percent}%"
                if spread <= target_spread_percent:
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
        send_telegram_to_chat(chat_id, "✅ История спреда сброшена!")
        return True

    elif text == '/clean':
        spread_history = []
        last_alert = None
        send_telegram_to_chat(chat_id, "🧹 Бот #1 очищен!")
        return True

    elif text.startswith('/set '):
        coin = text.replace('/set ', '').upper().strip()
        send_telegram_to_chat(chat_id, f"🔍 Проверяю {coin}...")
        is_valid, spot_pair, future_pair = is_valid_pair(coin)
        if is_valid:
            old_pair = spot_symbol
            spot_symbol = spot_pair
            futures_symbol = future_pair
            last_alert = None
            spread_history = []
            message = f"""
✅ <b>ПАРА ИЗМЕНЕНА (бот #1)</b>

<b>Было:</b> {old_pair}
<b>Стало:</b> {spot_symbol}
🎯 <b>Цель:</b> {target_spread_percent}%
⏰ <b>Интервал:</b> {check_interval} сек

<i>Отслеживание начато...</i>
"""
            send_telegram_to_chat(chat_id, message)
        else:
            message = f"❌ ПАРА {coin} НЕ НАЙДЕНА\n💡 /pairs1 - список популярных пар"
            send_telegram_to_chat(chat_id, message)
        return True

    elif text.startswith('/target '):
        try:
            new_target = float(text.replace('/target ', ''))
            if 0.3 <= new_target <= 9.0:
                target_spread_percent = new_target
                message = f"✅ Цель изменена: {target_spread_percent}%"
                send_telegram_to_chat(chat_id, message)
            else:
                message = "❌ Значение должно быть от 0.3 до 9.0"
                send_telegram_to_chat(chat_id, message)
        except:
            message = "❌ Неверный формат. Пример: /target1 0.8"
            send_telegram_to_chat(chat_id, message)
        return True

    elif text.startswith('/interval '):
        try:
            new_interval = int(text.replace('/interval ', ''))
            if 5 <= new_interval <= 600:
                check_interval = new_interval
                message = f"✅ Интервал изменен: {check_interval} сек"
                send_telegram_to_chat(chat_id, message)
            else:
                message = "❌ Значение должно быть от 5 до 600"
                send_telegram_to_chat(chat_id, message)
        except:
            message = "❌ Неверный формат. Пример: /interval1 30"
            send_telegram_to_chat(chat_id, message)
        return True

    else:
        if text.startswith('/'):
            send_telegram_to_chat(chat_id, f"❌ Неизвестная команда для бота #1: {text}\n/help1", reply_markup=main_keyboard)
        return False

def bot1_loop():
    global exchange, current_spread_data, last_alert, spread_history, bot1_running
    global spot_symbol, futures_symbol, target_spread_percent, check_interval, alert_levels

    print("🚀 ЗАПУСК АРБИТРАЖНОГО БОТА ByBit (БОТ №1)")
    print("="*50)
    print("📡 Подключение к ByBit...")
    
    exchange = ccxt.bybit({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'swap',
            'defaultSubType': 'linear',
            'defaultSettle': 'USDT'
        }
    })
    print("🔗 API ByBit public URL:", exchange.urls['api']['public'])
    
    print("📡 Загрузка рынков...")
    exchange.load_markets()
    print("✅ Биржа ByBit подключена!")

    send_telegram(f"✅ АРБИТРАЖНЫЙ БОТ #1 (ByBit) ЗАПУЩЕН!\n\n📊 Слежу за {spot_symbol}\n🎯 Цель: {target_spread_percent}%\n\n💡 /set1 ЛЮБАЯ_МОНЕТА - сменить пару\n📋 /help1 - все команды")

    print(f"\n📊 Текущая пара: {spot_symbol}")
    print(f"🎯 Цель: {target_spread_percent}%")
    print(f"⏰ Интервал: {check_interval} сек")
    print("="*50)
    print(f"\n📊 Начинаю отслеживание...")
    print("="*50)

    def get_spread():
        try:
            spot = exchange.fetch_order_book(spot_symbol)
            future = exchange.fetch_order_book(futures_symbol)
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

    while True:
        if not bot1_running:
            time.sleep(2)
            continue
        try:
            data = get_spread()
            if data:
                current_spread_data = data
                spread = data['spread']
                now = datetime.now().strftime('%H:%M:%S')
                spread_history.append(spread)
                if len(spread_history) > 20:
                    spread_history.pop(0)
                print(f"🕐 {now} | {spot_symbol} | Спред: {spread:+.2f}%", end="")
                if spread <= target_spread_percent:
                    print(" 🎯 ЦЕЛЬ ДОСТИГНУТА!")
                    if last_alert != "target":
                        profit = spread - 0.15
                        msg = f"""
🎯 <b>ЦЕЛЬ ДОСТИГНУТА (бот #1)!</b> 🎯
━━━━━━━━━━━━━━━━━━━━━
📊 {spot_symbol}
📈 <b>Спред:</b> {spread:+.2f}%
💰 <b>Чистая прибыль:</b> {profit:.2f}%
⚡ {data['action']}
━━━━━━━━━━━━━━━━━━━━━
⚡ ДЕЙСТВУЙТЕ БЫСТРО!
"""
                        send_telegram(msg)
                        last_alert = "target"
                else:
                    need = spread - target_spread_percent
                    print(f" | Нужно снижение: {need:.2f}%")
                    for level in alert_levels:
                        if spread <= level and last_alert != level:
                            msg = f"🔔 {spot_symbol}\nСпред снизился до {level}%\nТекущий: {spread:+.2f}%\nОсталось до цели: {need:.2f}%"
                            send_telegram(msg)
                            last_alert = level
                            break
                    if spread > max(alert_levels) + 0.3:
                        last_alert = None
            time.sleep(check_interval)
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            time.sleep(check_interval)

# ==================================================
# ВТОРОЙ БОТ (СКАНЕР ВСЕХ ПАР) – ByBit, С СУФФИКСОМ 2
# ==================================================
class ScannerBot:
    def __init__(self, token, default_chat_id):
        self.token = token
        self.default_chat_id = default_chat_id
        self.exchange = ccxt.bybit({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',
                'defaultSubType': 'linear'
            }
        })
        print("📡 Бот #2: загрузка рынков ByBit...")
        print("🔗 API ByBit public URL:", self.exchange.urls['api']['public'])
        self.exchange.load_markets()
        
        self.min_spread_percent = 0.5
        self.sleep_between_cycles = 10
        self.is_scanning = True
        self.last_signals = []
        
        print("📋 Бот #2: формирую список пар...")
        spot_pairs = []
        for symbol in self.exchange.markets:
            market = self.exchange.markets[symbol]
            if symbol.endswith('/USDT') and market.get('spot') and market.get('active'):
                spot_pairs.append(symbol)
        print(f"📈 Спотовых пар: {len(spot_pairs)}")
        
        self.trading_pairs = []
        for spot in spot_pairs:
            base = spot.replace('/USDT', '')
            future = f"{base}/USDT:USDT"
            if future in self.exchange.markets:
                self.trading_pairs.append({'spot': spot, 'future': future, 'base': base})
        print(f"🔄 Пар для сканирования: {len(self.trading_pairs)}")
        
    def get_spread(self, spot_symbol, futures_symbol):
        try:
            orderbook_spot = self.exchange.fetch_order_book(spot_symbol)
            orderbook_futures = self.exchange.fetch_order_book(futures_symbol)
            spot_bid = orderbook_spot['bids'][0][0]
            spot_ask = orderbook_spot['asks'][0][0]
            futures_bid = orderbook_futures['bids'][0][0]
            futures_ask = orderbook_futures['asks'][0][0]
            
            if spot_ask < futures_bid:
                spread_pct = ((futures_bid - spot_ask) / spot_ask) * 100
                if spread_pct > self.min_spread_percent:
                    net_profit = spread_pct - 0.15
                    print(f"\n{'='*60}")
                    print(f"🚨 АРБИТРАЖ (бот #2)! {spot_symbol}")
                    print(f"📈 Спред: {spread_pct:+.2f}% | 💵 ПРИБЫЛЬ: {net_profit:.2f}%")
                    print(f"💰 ПОКУПАЙ спот: {spot_ask:.8f}")
                    print(f"💰 ПРОДАВАЙ фьюч: {futures_bid:.8f}")
                    print(f"{'='*60}")
                    
                    msg = f"""
🚨 АРБИТРАЖ НАЙДЕН (бот #2)!
━━━━━━━━━━━━━━━━━━━
{spot_symbol}
Спред: {spread_pct:+.2f}%
Чистая прибыль: {net_profit:.2f}%
Покупай спот: {spot_ask:.8f}
Продавай фьюч: {futures_bid:.8f}
"""
                    send_telegram(msg)
                    self.last_signals.append({
                        'pair': spot_symbol,
                        'spread': spread_pct,
                        'profit': net_profit,
                        'time': datetime.now().strftime('%H:%M:%S')
                    })
                    if len(self.last_signals) > 10:
                        self.last_signals.pop(0)
                return spread_pct
                
            elif futures_ask < spot_bid:
                spread_pct = ((spot_bid - futures_ask) / futures_ask) * 100
                if spread_pct > self.min_spread_percent:
                    net_profit = spread_pct - 0.15
                    print(f"\n{'='*60}")
                    print(f"🚨 АРБИТРАЖ (бот #2)! {spot_symbol}")
                    print(f"📈 Спред: {spread_pct:+.2f}% | 💵 ПРИБЫЛЬ: {net_profit:.2f}%")
                    print(f"💰 ПОКУПАЙ фьюч: {futures_ask:.8f}")
                    print(f"💰 ПРОДАВАЙ спот: {spot_bid:.8f}")
                    print(f"{'='*60}")
                    
                    msg = f"""
🚨 АРБИТРАЖ НАЙДЕН (бот #2)!
━━━━━━━━━━━━━━━━━━━
{spot_symbol}
Спред: {spread_pct:+.2f}%
Чистая прибыль: {net_profit:.2f}%
Покупай фьюч: {futures_ask:.8f}
Продавай спот: {spot_bid:.8f}
"""
                    send_telegram(msg)
                    self.last_signals.append({
                        'pair': spot_symbol,
                        'spread': spread_pct,
                        'profit': net_profit,
                        'time': datetime.now().strftime('%H:%M:%S')
                    })
                    if len(self.last_signals) > 10:
                        self.last_signals.pop(0)
                return spread_pct
            else:
                return 0
        except Exception as e:
            return None
    
    def handle_command(self, text, chat_id):
        text = text.strip().lower()
        print(f"📩 БОТ2 команда: {text}")
        
        if text == '/help':
            message = f"""
📚 <b>ПОМОЩЬ (бот #2 - сканер ByBit)</b>

/start2 - Запустить сканирование
/stop2 - Остановить сканирование
/status2 - Текущий статус
/last2 - Последние 5 сигналов
/threshold2 0.5 - Изменить мин. спред
/interval2 60 - Изменить интервал между циклами

Текущие настройки:
Спред > {self.min_spread_percent}%
Интервал: {self.sleep_between_cycles} сек
"""
            send_telegram_to_chat(chat_id, message)
            return True
        
        elif text == '/start':
            self.is_scanning = True
            send_telegram_to_chat(chat_id, "✅ СКАНИРОВАНИЕ (бот #2) ВОЗОБНОВЛЕНО!")
            return True
        
        elif text == '/stop':
            self.is_scanning = False
            send_telegram_to_chat(chat_id, "⏸ СКАНИРОВАНИЕ (бот #2) ОСТАНОВЛЕНО! /start2 - возобновить")
            return True
        
        elif text == '/status':
            status_text = "РАБОТАЕТ ✅" if self.is_scanning else "ОСТАНОВЛЕН ⏸"
            message = f"""
📊 СТАТУС СКАНЕРА (бот #2)

Состояние: {status_text}
Мин. спред: {self.min_spread_percent}%
Интервал: {self.sleep_between_cycles} сек
Найдено сигналов: {len(self.last_signals)}
"""
            send_telegram_to_chat(chat_id, message)
            return True
        
        elif text == '/last':
            if self.last_signals:
                message = "🔄 ПОСЛЕДНИЕ СИГНАЛЫ (бот #2):\n"
                for sig in self.last_signals[-5:]:
                    message += f"\n{sig['pair']}: {sig['spread']:.2f}% | {sig['profit']:.2f}% | {sig['time']}"
                send_telegram_to_chat(chat_id, message)
            else:
                send_telegram_to_chat(chat_id, "📭 Пока нет сигналов")
            return True
        
        elif text.startswith('/threshold '):
            try:
                val = float(text.replace('/threshold ', ''))
                if 0.2 <= val <= 9.0:
                    self.min_spread_percent = val
                    send_telegram_to_chat(chat_id, f"✅ Мин. спред: {val}% | Чистая прибыль: {val - 0.15:.2f}%")
                else:
                    send_telegram_to_chat(chat_id, "❌ Значение от 0.2 до 9.0")
            except:
                send_telegram_to_chat(chat_id, "❌ Пример: /threshold2 0.5")
            return True
        
        elif text.startswith('/interval '):
            try:
                val = int(text.replace('/interval ', ''))
                if 5 <= val <= 300:
                    self.sleep_between_cycles = val
                    send_telegram_to_chat(chat_id, f"✅ Интервал: {val} сек")
                else:
                    send_telegram_to_chat(chat_id, "❌ Значение от 5 до 300")
            except:
                send_telegram_to_chat(chat_id, "❌ Пример: /interval2 30")
            return True
        
        else:
            if text.startswith('/'):
                send_telegram_to_chat(chat_id, f"❌ Неизвестная команда для бота #2: {text}\n/help2")
            return False
    
    def run(self):
        send_telegram(f"✅ АРБИТРАЖНЫЙ СКАНЕР ByBit (бот #2) ЗАПУЩЕН!\nСпред > {self.min_spread_percent}%")
        print(f"\n🚀 Бот #2 запущен | Мин. спред: {self.min_spread_percent}% | Интервал: {self.sleep_between_cycles} сек | Пар: {len(self.trading_pairs)}")
        
        cycle = 0
        while True:
            if not self.is_scanning:
                time.sleep(2)
                continue
            try:
                cycle += 1
                print(f"\n🔄 Бот #2 цикл #{cycle} | {datetime.now().strftime('%H:%M:%S')}")
                print(f"🔎 Сканирую {len(self.trading_pairs)} пар...")
                
                profitable_count = 0
                for i, pair in enumerate(self.trading_pairs):
                    if not self.is_scanning:
                        break
                    result = self.get_spread(pair['spot'], pair['future'])
                    if result and result > self.min_spread_percent:
                        profitable_count += 1
                    if (i + 1) % 100 == 0:
                        print(f"📊 Прогресс: {i+1}/{len(self.trading_pairs)} | Найдено: {profitable_count}", end="\r")
                    time.sleep(0.03)
                
                print(f"\n✅ Цикл #{cycle} завершён. Найдено: {profitable_count}")
                print(f"⏰ Следующий цикл через {self.sleep_between_cycles} сек...")
                time.sleep(self.sleep_between_cycles)
                
            except Exception as e:
                print(f"❌ Бот #2 ошибка: {e}")
                time.sleep(10)

# ==================================================
# ГЛАВНЫЙ ОБРАБОТЧИК ТЕЛЕГРАМ
# ==================================================
def telegram_polling(bot2):
    global bot1_running
    update_id = None
    while True:
        try:
            updates = get_updates(update_id)
            for update in updates:
                update_id = update.get('update_id', 0) + 1
                if 'message' in update:
                    message = update['message']
                    chat_id = message['chat']['id']
                    text = message.get('text', '')
                    
                    if chat_id in pending_password:
                        check_password(chat_id, text)
                        continue
                    
                    if not is_authorized(chat_id):
                        if text.startswith('/register'):
                            start_password_flow(chat_id)
                        else:
                            send_telegram_to_chat(chat_id, "🔐 Доступ запрещён. Для использования бота отправьте команду /register и введите пароль.")
                        continue
                    
                    if text.startswith('/'):
                        # Глобальные команды (управляют обоими ботами)
                        if text == '/start':
                            bot1_running = True
                            bot2.is_scanning = True
                            send_telegram_to_chat(chat_id, "✅ ОБА БОТА ЗАПУЩЕНЫ")
                            continue
                        elif text == '/stop':
                            bot1_running = False
                            bot2.is_scanning = False
                            send_telegram_to_chat(chat_id, "⏸ ОБА БОТА ОСТАНОВЛЕНЫ")
                            continue
                        
                        # Разделяем команду на имя и аргументы
                        parts = text.split()
                        cmd_name = parts[0]
                        args = ' '.join(parts[1:]) if len(parts) > 1 else ''
                        
                        if cmd_name.endswith('2'):
                            base_cmd = cmd_name[:-1]
                            full_cmd = f"{base_cmd} {args}".strip()
                            bot2.handle_command(full_cmd, chat_id)
                        elif cmd_name.endswith('1'):
                            base_cmd = cmd_name[:-1]
                            full_cmd = f"{base_cmd} {args}".strip()
                            handle_command_bot1(full_cmd, chat_id)
                        else:
                            # Команда без суффикса – первому боту (для обратной совместимости)
                            handle_command_bot1(text, chat_id)
            time.sleep(1)
        except Exception as e:
            print(f"❌ Ошибка в polling: {e}")
            time.sleep(5)

# ==================================================
# ЗАПУСК
# ==================================================
if __name__ == "__main__":
    # Запускаем поток первого бота
    threading.Thread(target=bot1_loop, daemon=True).start()
    # Создаём и запускаем второго бота
    bot2 = ScannerBot(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
    threading.Thread(target=bot2.run, daemon=True).start()
    # Запускаем обработчик команд
    telegram_polling(bot2)
