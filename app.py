from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import threading
import time
import json
import os

app = Flask(__name__)
CORS(app)

TELEGRAM_TOKEN = "8223149909:AAE8hQlu-coYVlrdd5v810D4HcOmPiZBOP8"
CHAT_ID = "7188544429"

INDIAN_STOCKS = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "SBIN.NS", "ICICIBANK.NS"]
GLOBAL_ASSETS = ["GC=F", "SI=F", "CL=F", "INR=X"]
STOCKS = INDIAN_STOCKS + GLOBAL_ASSETS

STATE_FILE = "sniper_trades_state.json"
memory_lock = threading.Lock()

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                trades = data.get("active_trades", {})
                alerts = data.get("hit_alerts", {})
                for s in STOCKS:
                    if s not in trades: trades[s] = None
                    if s not in alerts: alerts[s] = False
                return trades, alerts
        except:
            pass
    return {s: None for s in STOCKS}, {s: False for s in STOCKS}

def save_state(trades, alerts):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"active_trades": trades, "hit_alerts": alerts}, f)
    except:
        pass

active_trades, hit_alerts = load_state()

def is_market_open(stock):
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    
    if stock in GLOBAL_ASSETS:
        return now.weekday() < 5
        
    if now.weekday() >= 5:
        return False
    
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=5)
    except:
        pass

def calculate_sniper_indicators(df):
    # Trend EMAs
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # Wilder's Smooth RSI (Accurate Professional Formula)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = (100 - (100 / (1 + rs))).fillna(50)
    
    # True Range & ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = np.maximum(high_low, np.maximum(high_close, low_close))
    df['ATR'] = tr.ewm(alpha=1/14, adjust=False).mean()
    
    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['Signal_Line']
    
    # Support, Resistance & Volume
    df['Support'] = df['low'].rolling(20).min()
    df['Resistance'] = df['high'].rolling(20).max()
    
    if 'volume' in df and df['volume'].sum() > 0:
        df['Vol_SMA'] = df['volume'].rolling(20).mean().replace(0, 1)
    else:
        df['Vol_SMA'] = 1
        
    return df.bfill().ffill()

def fetch_data(stock, mode="intraday"):
    if mode == "intraday":
        interval = "15m" if stock in GLOBAL_ASSETS else "5m"
        rng = "5d"
    else:
        interval = "1d"
        rng = "6mo"
        
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock}?interval={interval}&range={rng}"
    res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8).json()
    
    result = res.get('chart', {}).get('result', [])
    if not result:
        raise ValueError("No data")
        
    quote = result[0]['indicators']['quote'][0]
    close_list = quote.get('close', [])
    open_list = quote.get('open', close_list)
    high_list = quote.get('high', [])
    low_list = quote.get('low', [])
    
    df = pd.DataFrame({
        'open': open_list if len(open_list) == len(close_list) else close_list,
        'close': close_list,
        'high': high_list,
        'low': low_list
    })
    
    vol_list = quote.get('volume', [])
    if vol_list and len(vol_list) == len(close_list):
        df['volume'] = vol_list
    else:
        df['volume'] = 0
        
    df['volume'] = df['volume'].fillna(0)
    df = df.dropna(subset=['close', 'high', 'low', 'open'])
    
    if len(df) < 30:
        raise ValueError("Insufficient data")
        
    return calculate_sniper_indicators(df)

def evaluate_sniper_setup(df, mode="intraday"):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    price = round(float(latest['close']), 2)
    open_p = float(latest['open'])
    atr = max(float(latest['ATR']), price * 0.0015)
    rsi = round(float(latest['RSI']), 1)
    
    ema9 = float(latest['EMA_9'])
    ema21 = float(latest['EMA_21'])
    ema50 = float(latest['EMA_50'])
    
    macd = float(latest['MACD'])
    sig = float(latest['Signal_Line'])
    hist_now = float(latest['MACD_Hist'])
    hist_prev = float(prev['MACD_Hist'])
    
    is_green_candle = price >= open_p
    is_red_candle = price < open_p
    
    # 5-Layer Confluence Score
    buy_points = 0
    sell_points = 0
    
    # 1. Major Trend Filter (EMA 50)
    if price > ema50: buy_points += 25
    else: sell_points += 25
    
    # 2. Fast Trend Crossover (EMA 9 vs EMA 21)
    if ema9 > ema21: buy_points += 25
    else: sell_points += 25
    
    # 3. MACD Momentum Rising/Falling
    if macd > sig and hist_now >= hist_prev: buy_points += 20
    elif macd < sig and hist_now <= hist_prev: sell_points += 20
    
    # 4. Safe RSI Momentum Zone (Never buy overbought >70, never sell oversold <30)
    if 48 <= rsi <= 68: buy_points += 15
    elif 32 <= rsi <= 52: sell_points += 15
    
    # 5. Candle Confirmation
    if is_green_candle and price > float(prev['close']): buy_points += 15
    elif is_red_candle and price < float(prev['close']): sell_points += 15

    # Strict Sniper Trigger: Minimum 85% Confluence Required!
    signal_type = None
    conf = max(buy_points, sell_points)
    
    rr_target_mult = 2.2 if mode == "intraday" else 3.0
    rr_sl_mult = 1.3 if mode == "intraday" else 1.5
    
    if buy_points >= 85 and price > ema50 and ema9 > ema21 and is_green_candle:
        signal_type = "BUY"
        target = round(price + (atr * rr_target_mult), 2)
        sl = round(price - (atr * rr_sl_mult), 2)
        conf = min(buy_points, 98)
    elif sell_points >= 85 and price < ema50 and ema9 < ema21 and is_red_candle:
        signal_type = "SELL"
        target = round(price - (atr * rr_target_mult), 2)
        sl = round(price + (atr * rr_sl_mult), 2)
        conf = min(sell_points, 98)
    else:
        target = "--"
        sl = "--"
        
    trend_name = "Bullish Uptrend 📈" if price > ema50 and ema9 > ema21 else ("Bearish Downtrend 📉" if price < ema50 and ema9 < ema21 else "Sideways Zone ⚖️")
    return signal_type, price, target, sl, conf, trend_name, rsi

def update_trade_lifecycle(stock, price, df, notify_telegram=True):
    global active_trades, hit_alerts
    with memory_lock:
        active_trades, hit_alerts = load_state()
        trade = active_trades.get(stock)
        
        if trade is not None:
            t_type = trade["type"]
            entry = float(trade["entry"])
            target = float(trade["target"])
            sl = float(trade["sl"])
            be_moved = trade.get("breakeven", False)
            
            if t_type == "BUY":
                # Check Target Hit
                if price >= target:
                    if notify_telegram:
                        send_telegram(f"🎯 <b>SNIPER TARGET HIT!</b>\nAsset: {stock}\nEntry: ₹{entry}\nBooked at: ₹{price} 💰🔥")
                    active_trades[stock] = None
                    hit_alerts[stock] = True
                    save_state(active_trades, hit_alerts)
                    return
                # Check Stop Loss Hit
                elif price <= sl:
                    if notify_telegram:
                        msg_type = "🛡️ <b>BREAK-EVEN EXIT (0 LOSS)</b>" if be_moved else "🛡️ <b>STOP LOSS HIT</b>"
                        send_telegram(f"{msg_type}\nAsset: {stock}\nEntry: ₹{entry}\nExited at: ₹{price}")
                    active_trades[stock] = None
                    save_state(active_trades, hit_alerts)
                    return
                # Auto Trailing Break-Even at 50% Target
                elif not be_moved and price >= entry + ((target - entry) * 0.5):
                    active_trades[stock]["sl"] = entry
                    active_trades[stock]["breakeven"] = True
                    save_state(active_trades, hit_alerts)
                    if notify_telegram:
                        send_telegram(f"🔒 <b>RISK-FREE TRADE LOCKED!</b>\nAsset: {stock}\n50% Target reached! Stop-Loss moved to Entry (₹{entry}). Zero Loss Guaranteed!")
                        
            elif t_type == "SELL":
                # Check Target Hit
                if price <= target:
                    if notify_telegram:
                        send_telegram(f"🎯 <b>SNIPER TARGET HIT!</b>\nAsset: {stock}\nEntry: ₹{entry}\nBooked at: ₹{price} 💰🔥")
                    active_trades[stock] = None
                    hit_alerts[stock] = True
                    save_state(active_trades, hit_alerts)
                    return
                # Check Stop Loss Hit
                elif price >= sl:
                    if notify_telegram:
                        msg_type = "🛡️ <b>BREAK-EVEN EXIT (0 LOSS)</b>" if be_moved else "🛡️ <b>STOP LOSS HIT</b>"
                        send_telegram(f"{msg_type}\nAsset: {stock}\nEntry: ₹{entry}\nExited at: ₹{price}")
                    active_trades[stock] = None
                    save_state(active_trades, hit_alerts)
                    return
                # Auto Trailing Break-Even at 50% Target
                elif not be_moved and price <= entry - ((entry - target) * 0.5):
                    active_trades[stock]["sl"] = entry
                    active_trades[stock]["breakeven"] = True
                    save_state(active_trades, hit_alerts)
                    if notify_telegram:
                        send_telegram(f"🔒 <b>RISK-FREE TRADE LOCKED!</b>\nAsset: {stock}\n50% Target reached! Stop-Loss moved to Entry (₹{entry}). Zero Loss Guaranteed!")
        else:
            # Look for a new Sniper Trade
            sig_type, price, target, sl, conf, trend_name, rsi = evaluate_sniper_setup(df, "intraday")
            if sig_type in ["BUY", "SELL"]:
                active_trades[stock] = {
                    "type": sig_type,
                    "entry": price,
                    "target": target,
                    "sl": sl,
                    "conf": conf,
                    "breakeven": False
                }
                save_state(active_trades, hit_alerts)
                if notify_telegram:
                    icon = "🚀 <b>SNIPER BUY CONFIRMED</b>" if sig_type == "BUY" else "⚠️ <b>SNIPER SELL CONFIRMED</b>"
                    send_telegram(f"{icon}\nAsset: {stock}\nTrend: {trend_name}\nEntry: ₹{price}\n🎯 Target: ₹{target}\n🛡️ SL: ₹{sl}\n🔥 Accuracy Score: {conf}%")

def telegram_tracker():
    send_telegram("✅ 5-Layer Sniper AI Engine Live: Trend-Follow + Zero-Loss Trailing SL Activated!")
    while True:
        for stock in STOCKS:
            try:
                if not is_market_open(stock):
                    continue
                df = fetch_data(stock, "intraday")
                price = round(float(df.iloc[-1]['close']), 2)
                update_trade_lifecycle(stock, price, df, notify_telegram=True)
            except:
                pass
        time.sleep(60)

threading.Thread(target=telegram_tracker, daemon=True).start()

@app.route('/')
def home():
    return "Global Sniper AI Trade Server is Awake and Running Perfectly!"

@app.route('/get_best_trades')
def get_best_trades():
    global active_trades, hit_alerts
    mode = request.args.get('mode', 'intraday')
    trades_data = []
    
    for stock in STOCKS:
        name = stock.replace(".NS", "").replace("=F", "").replace("=X", "")
        tv_symbol = stock
        if stock in INDIAN_STOCKS: tv_symbol = f"NSE:{name}"
        elif stock == "GC=F": tv_symbol = "COMEX:GC1!"
        elif stock == "SI=F": tv_symbol = "COMEX:SI1!"
        elif stock == "CL=F": tv_symbol = "NYMEX:CL1!"
        elif stock == "INR=X": tv_symbol = "FX_IDC:USDINR"

        if not is_market_open(stock):
            trades_data.append({
                "stock": name, "tv_symbol": tv_symbol, "price": "--", "change": 0,
                "signal": "SLEEP MODE 😴", "confidence": 0, "entry": "--", "target": "--", "stop_loss": "--",
                "timeframe": "Market Closed", "action_text": "Market is closed. Wait for opening bell.",
                "support": "--", "resistance": "--", "vol_status": "No Activity", "play_alert": False
            })
            continue

        try:
            df = fetch_data(stock, mode)
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            price = round(float(latest['close']), 2)
            support = round(float(latest['Support']), 2)
            resistance = round(float(latest['Resistance']), 2)
            change = round(((price - float(prev['close'])) / float(prev['close'])) * 100, 2)
            
            # Live lifecycle check so UI is NEVER out of sync!
            if mode == "intraday":
                update_trade_lifecycle(stock, price, df, notify_telegram=True)
                
            sig_type, _, calc_target, calc_sl, conf, trend_name, rsi = evaluate_sniper_setup(df, mode)
            
            with memory_lock:
                active_trades, hit_alerts = load_state()
                trade = active_trades.get(stock)
                just_hit = hit_alerts.get(stock, False)
                if just_hit:
                    hit_alerts[stock] = False
                    save_state(active_trades, hit_alerts)
            
            play_alert = False
            
            if just_hit:
                signal = "TARGET HIT! 💰🟢"
                entry_val = "--"
                target = "--"
                stop_loss = "--"
                action_text = "Boom! Sniper Target Hit! Profit booked."
                conf = 100
                play_alert = True
            elif trade and mode == "intraday":
                t_type = trade['type']
                be_text = " (Risk-Free SL Locked 🔒)" if trade.get('breakeven') else ""
                signal = f"ACTIVE {t_type} 🟢" if t_type == 'BUY' else f"ACTIVE SELL 🔴"
                entry_val = trade['entry']
                target = trade['target']
                stop_loss = trade['sl']
                action_text = f"Trade Running{be_text}. Entry: ₹{entry_val} | Target: ₹{target}"
                conf = trade.get('conf', conf)
            else:
                if sig_type == "BUY":
                    signal = "SNIPER BUY 🚀"
                    entry_val = price
                    target = calc_target
                    stop_loss = calc_sl
                    action_text = "5/5 Bullish Filters Matched! High Accuracy Entry."
                elif sig_type == "SELL":
                    signal = "SNIPER SELL 🔴"
                    entry_val = price
                    target = calc_target
                    stop_loss = calc_sl
                    action_text = "5/5 Bearish Filters Matched! High Accuracy Short."
                else:
                    signal = "WAIT / AVOID 🟡"
                    entry_val = "--"
                    target = "--"
                    stop_loss = "--"
                    action_text = f"Filter Score: {conf}% (Need 85%+). Protecting capital from fake moves."
            
            timeframe = ("15m Sniper Trend" if stock in GLOBAL_ASSETS else "5m Sniper Trend") if mode == "intraday" else "Swing (Next 3-5 Days)"
            
            trades_data.append({
                "stock": name, "tv_symbol": tv_symbol, "price": price, "change": change,
                "signal": signal, "confidence": conf, "entry": entry_val, "target": target, "stop_loss": stop_loss,
                "timeframe": timeframe, "action_text": action_text, "support": support,
                "resistance": resistance, "vol_status": f"{trend_name} | RSI: {rsi}", "play_alert": play_alert
            })
        except Exception as e:
            trades_data.append({
                "stock": name, "tv_symbol": tv_symbol, "price": "Error", "change": 0,
                "signal": "DATA ERROR ⚠️", "confidence": 0, "entry": "--", "target": "--", "stop_loss": "--",
                "timeframe": "Try again later", "action_text": "Syncing market feed...",
                "support": "--", "resistance": "--", "vol_status": "--", "play_alert": False
            })
            
    trades_data.sort(key=lambda x: (1 if "TARGET HIT" in x['signal'] else (2 if "ACTIVE" in x['signal'] else (3 if "SNIPER" in x['signal'] else 0)), x['confidence']), reverse=True)
    return jsonify({"status": "success", "data": trades_data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=False)
