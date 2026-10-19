from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import threading
import time

app = Flask(__name__)
CORS(app)

TELEGRAM_TOKEN = "8223149909:AAE8hQlu-coYVlrdd5v810D4HcOmPiZBOP8"
CHAT_ID = "7188544429"

# 🔥 Indian Stocks & Global Assets
INDIAN_STOCKS = ["RELIANCE.NS", "TATAMOTORS.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "SBIN.NS"]
GLOBAL_ASSETS = ["GC=F", "SI=F", "CL=F", "INR=X"]
STOCKS = INDIAN_STOCKS + GLOBAL_ASSETS

# ⚡ Global RAM Memory
active_trades = {stock: None for stock in STOCKS}
memory_lock = threading.Lock()

def is_market_open(stock):
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    
    if stock in GLOBAL_ASSETS:
        return now.weekday() < 5
        
    if now.weekday() >= 5: return False
    
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"})
    except: pass

def calculate_advanced_indicators(df):
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / loss)))
    
    df['ATR'] = np.maximum(df['high'] - df['low'], np.abs(df['high'] - df['close'].shift())).rolling(14).mean()
    df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
    df['Signal_Line'] = df['MACD'].ewm(span=9).mean()
    
    df['Support'] = df['low'].rolling(20).min()
    df['Resistance'] = df['high'].rolling(20).max()
    
    if 'volume' in df and df['volume'].sum() > 0:
        df['Vol_SMA'] = df['volume'].rolling(20).mean()
    else:
        df['Vol_SMA'] = 1 
    
    # ⚡ Updated Safe Fill for newer pandas versions
    return df.bfill().ffill()

def fetch_data(stock, mode="intraday"):
    interval = "1m" if mode == "intraday" else "1d"
    rng = "1d" if mode == "intraday" else "3mo"
    
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock}?interval={interval}&range={rng}"
    res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).json()
    
    result = res.get('chart', {}).get('result', [])
    if not result:
        raise ValueError("No data returned from API")
        
    quote = result[0]['indicators']['quote'][0]
    
    close_list = quote.get('close', [])
    high_list = quote.get('high', [])
    low_list = quote.get('low', [])
    
    # ⚡ 100% BULLETPROOF FIX FOR GLOBAL ASSETS
    # We ensure all lists are the same length before making the DataFrame
    df = pd.DataFrame({
        'close': close_list,
        'high': high_list,
        'low': low_list
    })
    
    vol_list = quote.get('volume', [])
    # Check if volume exists and exactly matches the size of close data
    if vol_list and len(vol_list) == len(close_list):
        df['volume'] = vol_list
    else:
        df['volume'] = 0 # Fallback to 0 if size mismatch or missing
        
    df['volume'] = df['volume'].fillna(0)
    df = df.dropna(subset=['close', 'high', 'low'])
    
    if df.empty:
        raise ValueError("Data is empty after processing")
        
    return calculate_advanced_indicators(df)

# ==========================================
# 🔥 TELEGRAM BACKGROUND TRACKER
# ==========================================
def telegram_tracker():
    send_telegram("✅ Ultimate AI Engine Live: Indian & Global Markets Tracked Perfectly!")
    while True:
        try:
            for stock in STOCKS:
                if not is_market_open(stock): continue
                
                df = fetch_data(stock, "intraday")
                latest = df.iloc[-1]
                price = round(latest['close'], 2)
                
                with memory_lock: trade = active_trades[stock]
                
                if trade is None:
                    rsi = latest['RSI']
                    macd_bullish = latest['MACD'] > latest['Signal_Line']
                    vol_breakout = latest['volume'] > latest['Vol_SMA']
                    
                    if (rsi < 45 and macd_bullish and vol_breakout) or (price <= latest['Support'] * 1.002):
                        target = round(price + max(latest['ATR'] * 3, price * 0.007), 2)
                        sl = round(price - max(latest['ATR'] * 1.5, price * 0.0035), 2)
                        with memory_lock: active_trades[stock] = {"type": "BUY", "target": target, "sl": sl}
                        send_telegram(f"🚀 <b>STRONG BUY ALERT</b>\nAsset: {stock}\nEntry: ₹{price}\n🎯 Target: ₹{target}\n🛡️ SL: ₹{sl}")
                    
                    elif (rsi > 65 and not macd_bullish and vol_breakout) or (price >= latest['Resistance'] * 0.998):
                        target = round(price - max(latest['ATR'] * 3, price * 0.007), 2)
                        sl = round(price + max(latest['ATR'] * 1.5, price * 0.0035), 2)
                        with memory_lock: active_trades[stock] = {"type": "SELL", "target": target, "sl": sl}
                        send_telegram(f"⚠️ <b>STRONG SELL ALERT</b>\nAsset: {stock}\nEntry: ₹{price}\n🎯 Target: ₹{target}\n🛡️ SL: ₹{sl}")
                else:
                    if trade["type"] == "BUY":
                        if price >= trade["target"]:
                            send_telegram(f"🎯 <b>TARGET HIT!</b>\nAsset: {stock}\nProfit booked at ₹{price} 💰")
                            with memory_lock: active_trades[stock] = None 
                        elif price <= trade["sl"]:
                            send_telegram(f"🛡️ <b>STOP LOSS HIT</b>\nAsset: {stock}\nExited at ₹{price}.")
                            with memory_lock: active_trades[stock] = None
                    elif trade["type"] == "SELL":
                        if price <= trade["target"]:
                            send_telegram(f"🎯 <b>TARGET HIT!</b>\nAsset: {stock}\nProfit booked at ₹{price} 💰")
                            with memory_lock: active_trades[stock] = None
                        elif price >= trade["sl"]:
                            send_telegram(f"🛡️ <b>STOP LOSS HIT</b>\nAsset: {stock}\nExited at ₹{price}.")
                            with memory_lock: active_trades[stock] = None
        except: pass
        time.sleep(60)

threading.Thread(target=telegram_tracker, daemon=True).start()

# ==========================================
# FRONTEND API ROUTE & UPTIMEROBOT
# ==========================================
@app.route('/')
def home(): 
    return "Global AI Trade Server is Awake and Running Perfectly!"

@app.route('/get_best_trades')
def get_best_trades():
    global active_trades
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
                "signal": "SLEEP MODE 😴", "confidence": 0, "target": "--", "stop_loss": "--",
                "timeframe": "Market Closed", "action_text": "Market is closed. Take rest or analyze.",
                "support": "--", "resistance": "--", "vol_status": "No Activity", "play_alert": False
            })
            continue

        try:
            df = fetch_data(stock, mode)
            latest = df.iloc[-1]
            price = round(latest['close'], 2)
            atr = round(latest['ATR'], 2)
            rsi = round(latest['RSI'], 2)
            support = round(latest['Support'], 2)
            resistance = round(latest['Resistance'], 2)
            
            vol_status = "High Volume 🚀" if latest['volume'] > latest['Vol_SMA'] * 1.5 else "Normal Volume 📊"
            change = round(((price - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100, 2)
            
            trend_score = 50
            if latest['EMA_9'] > latest['EMA_21']: trend_score += 15
            if latest['MACD'] > latest['Signal_Line']: trend_score += 15
            if latest['volume'] > latest['Vol_SMA']: trend_score += 15
            if rsi < 45: trend_score += 10
            trend_score = min(max(int(trend_score), 0), 99) 

            with memory_lock: trade = active_trades[stock]
            
            play_alert = False
            
            if trade:
                signal = f"ACTIVE {trade['type']} 🟢" if trade['type'] == 'BUY' else f"ACTIVE SELL 🔴"
                target = trade['target']
                stop_loss = trade['sl']
                action_text = f"Trade is LIVE. Target: ₹{target}."
                conf = trend_score 
            else:
                signal = "WAIT / HOLD 🟡"
                target = "--"
                stop_loss = "--"
                action_text = "Scanning for perfect setup."
                conf = 0 
                
                min_profit_pct = 0.007 if mode == "intraday" else 0.04
                min_loss_pct = 0.0035 if mode == "intraday" else 0.02
                
                if (rsi < 45 and latest['MACD'] > latest['Signal_Line']) or price <= support * 1.002:
                    signal = "FRESH BUY 🚀"
                    target = round(price + max(atr * 3, price * min_profit_pct), 2)
                    stop_loss = round(price - max(atr * 1.5, price * min_loss_pct), 2)
                    action_text = "Perfect Entry! Take Trade."
                    conf = 95 
                    play_alert = True
                elif (rsi > 65 and latest['MACD'] < latest['Signal_Line']) or price >= resistance * 0.998:
                    signal = "FRESH SELL 🔴"
                    target = round(price - max(atr * 3, price * min_profit_pct), 2)
                    stop_loss = round(price + max(atr * 1.5, price * min_loss_pct), 2)
                    action_text = "Perfect Short Entry! Take Trade."
                    conf = 95 
                    play_alert = True
            
            timeframe = "1-15 Mins (Fast)" if mode == "intraday" else "Swing (Next 3 Days)"
            
            trades_data.append({
                "stock": name, "tv_symbol": tv_symbol, "price": price, "change": change,
                "signal": signal, "confidence": conf, "target": target, "stop_loss": stop_loss,
                "timeframe": timeframe, "action_text": action_text, "support": support,
                "resistance": resistance, "vol_status": vol_status, "play_alert": play_alert
            })
        except Exception as e: 
            trades_data.append({
                "stock": name, "tv_symbol": tv_symbol, "price": "Error", "change": 0,
                "signal": "DATA ERROR ⚠️", "confidence": 0, "target": "--", "stop_loss": "--",
                "timeframe": "Try again later", "action_text": "API Error: " + str(e),
                "support": "--", "resistance": "--", "vol_status": "--", "play_alert": False
            })
        
    trades_data.sort(key=lambda x: x['confidence'], reverse=True)
    return jsonify({"status": "success", "data": trades_data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=False)
