from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import pandas as pd
import numpy as np
import threading
import time

app = Flask(__name__)
CORS(app)

TELEGRAM_TOKEN = "8223149909:AAE8hQlu-coYVlrdd5v810D4HcOmPiZBOP8"
CHAT_ID = "7188544429"
STOCKS = ["RELIANCE.NS", "TATAMOTORS.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "SBIN.NS"]

active_trades = {stock: None for stock in STOCKS}
memory_lock = threading.Lock()

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"})
    except: pass

def calculate_advanced_indicators(df):
    # ⚡ 10,000x Pro Indicators
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / loss)))
    
    df['ATR'] = np.maximum(df['high'] - df['low'], np.abs(df['high'] - df['close'].shift())).rolling(14).mean()
    
    df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
    df['Signal_Line'] = df['MACD'].ewm(span=9).mean()
    
    # 🔥 New: Support, Resistance & Volume
    df['Support'] = df['low'].rolling(20).min()
    df['Resistance'] = df['high'].rolling(20).max()
    df['Vol_SMA'] = df['volume'].rolling(20).mean()
    
    return df.bfill()

def fetch_data(stock, mode="intraday"):
    # ⚡ Fix: Day Trade now uses 1 Day ('1d') candles for Tomorrow's predictions!
    interval = "1m" if mode == "intraday" else "1d"
    rng = "1d" if mode == "intraday" else "3mo"
    
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock}?interval={interval}&range={rng}"
    res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).json()
    quote = res['chart']['result'][0]['indicators']['quote'][0]
    
    df = pd.DataFrame({
        'close': quote['close'], 
        'high': quote['high'], 
        'low': quote['low'],
        'volume': quote.get('volume', np.zeros(len(quote['close'])))
    }).dropna()
    return calculate_advanced_indicators(df)

# ==========================================
# 🔥 SMART BACKGROUND TRACKER
# ==========================================
def telegram_tracker():
    send_telegram("✅ 10,000x Pro System Live: High-Profit AI Engine running!")
    while True:
        try:
            for stock in STOCKS:
                df = fetch_data(stock, "intraday") # Tracking is always fast (1m)
                latest = df.iloc[-1]
                price = round(latest['close'], 2)
                
                with memory_lock: trade = active_trades[stock]
                
                if trade is None:
                    rsi = latest['RSI']
                    macd_bullish = latest['MACD'] > latest['Signal_Line']
                    vol_breakout = latest['volume'] > latest['Vol_SMA']
                    
                    # 🚀 BIG PROFIT LOGIC
                    if (rsi < 45 and macd_bullish and vol_breakout) or (price <= latest['Support'] * 1.002):
                        target = round(price + max(latest['ATR'] * 3, price * 0.007), 2) # Min 0.7% Profit
                        sl = round(price - max(latest['ATR'] * 1.5, price * 0.0035), 2)
                        
                        with memory_lock:
                            active_trades[stock] = {"type": "BUY", "target": target, "sl": sl}
                        send_telegram(f"🚀 <b>STRONG BUY ALERT</b>\nStock: {stock}\nEntry: ₹{price}\n🎯 Target: ₹{target} (Big Move)\n🛡️ SL: ₹{sl}\nReason: Volume Breakout / Support Bounce.")
                    
                    elif (rsi > 65 and not macd_bullish and vol_breakout) or (price >= latest['Resistance'] * 0.998):
                        target = round(price - max(latest['ATR'] * 3, price * 0.007), 2)
                        sl = round(price + max(latest['ATR'] * 1.5, price * 0.0035), 2)
                        
                        with memory_lock:
                            active_trades[stock] = {"type": "SELL", "target": target, "sl": sl}
                        send_telegram(f"⚠️ <b>STRONG SELL ALERT</b>\nStock: {stock}\nEntry: ₹{price}\n🎯 Target: ₹{target}\n🛡️ SL: ₹{sl}\nReason: Resistance Rejection.")
                else:
                    # Live Profit/Loss Tracking
                    if trade["type"] == "BUY":
                        if price >= trade["target"]:
                            send_telegram(f"🎯 <b>MASSIVE TARGET HIT!</b>\nStock: {stock}\nProfit booked at ₹{price} 💰💰")
                            with memory_lock: active_trades[stock] = None 
                        elif price <= trade["sl"]:
                            send_telegram(f"🛡️ <b>STOP LOSS HIT</b>\nStock: {stock}\nExited at ₹{price}.")
                            with memory_lock: active_trades[stock] = None
                            
                    elif trade["type"] == "SELL":
                        if price <= trade["target"]:
                            send_telegram(f"🎯 <b>MASSIVE TARGET HIT!</b>\nStock: {stock}\nProfit booked at ₹{price} 💰💰")
                            with memory_lock: active_trades[stock] = None
                        elif price >= trade["sl"]:
                            send_telegram(f"🛡️ <b>STOP LOSS HIT</b>\nStock: {stock}\nExited at ₹{price}.")
                            with memory_lock: active_trades[stock] = None
                            
        except: pass
        time.sleep(60)

threading.Thread(target=telegram_tracker, daemon=True).start()

# ==========================================
# FRONTEND API ROUTE
# ==========================================
@app.route('/')
def home(): return "10,000x Pro AI Server is Awake!"

@app.route('/get_best_trades')
def get_best_trades():
    global active_trades
    mode = request.args.get('mode', 'intraday') 
    trades_data = []
    
    for stock in STOCKS:
        try:
            df = fetch_data(stock, mode)
            latest = df.iloc[-1]
            price = round(latest['close'], 2)
            atr = round(latest['ATR'], 2)
            rsi = round(latest['RSI'], 2)
            support = round(latest['Support'], 2)
            resistance = round(latest['Resistance'], 2)
            vol_status = "High Volume Breakout 🚀" if latest['volume'] > latest['Vol_SMA'] * 1.5 else "Normal Volume 📊"
            
            change = round(((price - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100, 2)
            
            # Confidence Logic
            trend_score = 50
            if latest['EMA_9'] > latest['EMA_21']: trend_score += 15
            if latest['MACD'] > latest['Signal_Line']: trend_score += 15
            if latest['volume'] > latest['Vol_SMA']: trend_score += 15
            if rsi < 45: trend_score += 10
            trend_score = min(max(int(trend_score), 0), 99) 

            with memory_lock: trade = active_trades[stock]
            
            if trade:
                signal = f"ACTIVE {trade['type']} 🟢" if trade['type'] == 'BUY' else f"ACTIVE SELL 🔴"
                target = trade['target']
                stop_loss = trade['sl']
                action_text = f"Trade is LIVE. Relax & wait for Target ₹{target}."
                conf = trend_score 
            else:
                signal = "WAIT / HOLD 🟡"
                target = "--"
                stop_loss = "--"
                action_text = "Scanning for perfect high-profit setup."
                conf = 0 
                
                # ⚡ Prediction logic for UI
                min_profit_pct = 0.007 if mode == "intraday" else 0.04 # 4% target for swing/day
                min_loss_pct = 0.0035 if mode == "intraday" else 0.02
                
                if (rsi < 45 and latest['MACD'] > latest['Signal_Line']) or price <= support * 1.002:
                    signal = "FRESH BUY 🚀"
                    target = round(price + max(atr * 3, price * min_profit_pct), 2)
                    stop_loss = round(price - max(atr * 1.5, price * min_loss_pct), 2)
                    action_text = "Great Support Level / Breakout!"
                    conf = 95 
                elif (rsi > 65 and latest['MACD'] < latest['Signal_Line']) or price >= resistance * 0.998:
                    signal = "FRESH SELL 🔴"
                    target = round(price - max(atr * 3, price * min_profit_pct), 2)
                    stop_loss = round(price + max(atr * 1.5, price * min_loss_pct), 2)
                    action_text = "Resistance Rejection detected!"
                    conf = 95 
            
            timeframe = "1-15 Mins (Fast)" if mode == "intraday" else "Tomorrow / Next 3 Days 📅"
            
            trades_data.append({
                "stock": stock.replace(".NS", ""),
                "price": price,
                "change": change,
                "signal": signal,
                "confidence": conf,
                "target": target,
                "stop_loss": stop_loss,
                "timeframe": timeframe,
                "action_text": action_text,
                "support": support,
                "resistance": resistance,
                "vol_status": vol_status
            })
        except: pass
        
    trades_data.sort(key=lambda x: x['confidence'], reverse=True)
    return jsonify({"status": "success", "data": trades_data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=False)
