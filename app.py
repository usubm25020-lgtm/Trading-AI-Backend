from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import threading
import time

app = Flask(__name__)
CORS(app)

TELEGRAM_TOKEN = "8223149909:AAE8hQlu-coYVlrdd5v810D4HcOmPiZBOP8"
CHAT_ID = "7188544429"
STOCKS = ["RELIANCE.NS", "TATAMOTORS.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "SBIN.NS"]

# 🔥 Trade Memory Database (এটা ট্রেড লক করে রাখবে)
active_trades = {stock: None for stock in STOCKS}
last_signal_time = {}

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"})
    except: pass

def calculate_indicators(df):
    df['EMA_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).ewm(com=14).mean()
    loss = -delta.where(delta < 0, 0).ewm(com=14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / loss)))
    df['ATR'] = np.maximum(df['high'] - df['low'], np.abs(df['high'] - df['close'].shift())).rolling(14).mean()
    df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
    df['Signal_Line'] = df['MACD'].ewm(span=9).mean()
    return df

def fetch_data(stock, mode="intraday"):
    interval = "1m" if mode == "intraday" else "15m"
    rng = "1d" if mode == "intraday" else "5d"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock}?interval={interval}&range={rng}"
    res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}).json()
    quote = res['chart']['result'][0]['indicators']['quote'][0]
    df = pd.DataFrame({'close': quote['close'], 'high': quote['high'], 'low': quote['low']}).dropna()
    return calculate_indicators(df)

# ==========================================
# 🔥 SMART BACKGROUND TRACKER (Telegram Engine)
# ==========================================
def telegram_tracker():
    send_telegram("✅ System Live: Advanced Trade Tracker & Auto-Alerts are running!")
    while True:
        try:
            for stock in STOCKS:
                df = fetch_data(stock, "intraday") # Tracking happens on fast 1m data
                latest = df.iloc[-1]
                price = round(latest['close'], 2)
                rsi = round(latest['RSI'], 2)
                atr = round(latest['ATR'], 2)
                
                trade = active_trades[stock]
                
                # 1. NEW SIGNAL GENERATION
                if trade is None:
                    if rsi < 35 and latest['MACD'] > latest['Signal_Line']:
                        target = round(price + (atr * 2.5), 2)
                        stop_loss = round(price - (atr * 1.2), 2)
                        active_trades[stock] = {"type": "BUY", "entry": price, "target": target, "sl": stop_loss}
                        send_telegram(f"🚀 <b>NEW BUY TRADE</b>\nStock: {stock}\nEntry: ₹{price}\nTarget: ₹{target}\nSL: ₹{stop_loss}\nReason: RSI Oversold & MACD Bullish.")
                    
                    elif rsi > 70 and latest['MACD'] < latest['Signal_Line']:
                        target = round(price - (atr * 2.5), 2)
                        stop_loss = round(price + (atr * 1.2), 2)
                        active_trades[stock] = {"type": "SELL", "entry": price, "target": target, "sl": stop_loss}
                        send_telegram(f"⚠️ <b>NEW SELL TRADE</b>\nStock: {stock}\nEntry: ₹{price}\nTarget: ₹{target}\nSL: ₹{stop_loss}\nReason: Market Overbought.")
                
                # 2. TRACKING EXISTING TRADES (Target/SL Hits)
                else:
                    if trade["type"] == "BUY":
                        if price >= trade["target"]:
                            send_telegram(f"🎯 <b>TARGET HIT!</b>\nStock: {stock}\nProfit booked at ₹{price} (Target was ₹{trade['target']}).")
                            active_trades[stock] = None # Clear memory
                        elif price <= trade["sl"]:
                            send_telegram(f"🛡️ <b>STOP LOSS HIT</b>\nStock: {stock}\nExited at ₹{price} to prevent big losses.")
                            active_trades[stock] = None
                            
                    elif trade["type"] == "SELL":
                        if price <= trade["target"]:
                            send_telegram(f"🎯 <b>TARGET HIT!</b>\nStock: {stock}\nProfit booked at ₹{price} (Target was ₹{trade['target']}).")
                            active_trades[stock] = None
                        elif price >= trade["sl"]:
                            send_telegram(f"🛡️ <b>STOP LOSS HIT</b>\nStock: {stock}\nExited at ₹{price} to prevent big losses.")
                            active_trades[stock] = None
        except: pass
        time.sleep(60) # Checks exactly every 1 minute

threading.Thread(target=telegram_tracker, daemon=True).start()

# ==========================================
# FRONTEND API ROUTE (Dual Mode Support)
# ==========================================
@app.route('/get_best_trades')
def get_best_trades():
    mode = request.args.get('mode', 'intraday') # Gets mode from UI
    trades_data = []
    
    for stock in STOCKS:
        try:
            df = fetch_data(stock, mode)
            latest = df.iloc[-1]
            price = round(latest['close'], 2)
            atr = round(latest['ATR'], 2)
            rsi = round(latest['RSI'], 2)
            change = round(((price - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100, 2)
            
            # Dynamic Confidence Calculation (0-100%)
            conf = 50
            if latest['EMA_20'] > latest['EMA_50']: conf += 15
            if latest['MACD'] > latest['Signal_Line']: conf += 15
            if rsi < 40: conf += 20
            elif rsi > 70: conf -= 30
            conf = min(max(int(conf), 0), 100) # Ensure between 0-100

            # 🔥 MEMORY LOCK: If trade exists, show locked Target/SL
            trade = active_trades[stock]
            if trade:
                signal = f"ACTIVE {trade['type']} 🟢" if trade['type'] == 'BUY' else f"ACTIVE SELL 🔴"
                target = trade['target']
                stop_loss = trade['sl']
                action_text = f"Trade running. Waiting for Target ₹{target} or SL ₹{stop_loss}."
            else:
                signal = "WAIT / HOLD 🟡"
                target = "--"
                stop_loss = "--"
                action_text = "No active setup. Market stabilizing."
                
                # Check for new setup if not locked
                if rsi < 35 and latest['MACD'] > latest['Signal_Line']:
                    signal = "FRESH BUY SETUP 🚀"
                    target = round(price + (atr * 2.5), 2)
                    stop_loss = round(price - (atr * 1.2), 2)
                    action_text = "Perfect entry point detected. Check Telegram."
            
            timeframe = "1-10 Mins" if mode == "intraday" else "Current Day/Swing"
            
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
                "sentiment": "Neutral",
                "market_condition": "Live Tracking"
            })
        except: pass
        
    trades_data.sort(key=lambda x: x['confidence'], reverse=True)
    return jsonify({"status": "success", "data": trades_data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
