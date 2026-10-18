from flask import Flask, jsonify
from flask_cors import CORS
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import threading
import time

app = Flask(__name__)
CORS(app)

# ==========================================
# TELEGRAM SETTINGS
# ==========================================
TELEGRAM_TOKEN = "8223149909:AAE8hQlu-coYVlrdd5v810D4HcOmPiZBOP8"
CHAT_ID = "7188544429"

STOCKS = ["RELIANCE.NS", "TATAMOTORS.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "SBIN.NS"]
last_alert = {}

def send_telegram_alert(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, data=payload)
    except Exception as e:
        pass

def calculate_advanced_indicators(df):
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(com=13, adjust=False).mean()
    avg_loss = loss.ewm(com=13, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.rolling(14).mean()
    
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    return df

def get_market_data(stock):
    headers = {'User-Agent': 'Mozilla/5.0'}
    # ⚡ MAGIC CHANGE: 1d এর বদলে 15m (15 Minute) এবং range 5d করা হয়েছে Intraday এর জন্য
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock}?interval=15m&range=5d"
    res = requests.get(url, headers=headers).json()
    quote = res['chart']['result'][0]['indicators']['quote'][0]
    timestamps = res['chart']['result'][0]['timestamp']
    
    df = pd.DataFrame({
        'date': pd.to_datetime(timestamps, unit='s'),
        'close': quote['close'],
        'high': quote['high'],
        'low': quote['low']
    }).dropna()
    return calculate_advanced_indicators(df)

# ==========================================
# BACKGROUND SCANNER ROBOT
# ==========================================
def background_scanner():
    send_telegram_alert("✅ System Live: FAST INTRADAY Scanner is now running!")
    
    while True:
        try:
            for stock in STOCKS:
                df = get_market_data(stock)
                latest = df.iloc[-1]
                
                current_price = round(latest['close'], 2)
                rsi = round(latest['RSI'], 2)
                atr = round(latest['ATR'], 2)
                
                message = ""
                # Intraday Fast Signals
                if rsi < 35 and latest['MACD'] > latest['Signal_Line']:
                    target = round(current_price + (atr * 3), 2)
                    stop_loss = round(current_price - (atr * 1.5), 2)
                    message = f"🚀 <b>INTRADAY BUY ALERT</b>\nStock: {stock}\nPrice: ₹{current_price}\nRSI: {rsi}\nTarget: ₹{target}\nStop Loss: ₹{stop_loss}\n⏱️ TF: 15 Mins"
                
                elif rsi > 75:
                    message = f"⚠️ <b>INTRADAY SELL ALERT</b>\nStock: {stock}\nPrice: ₹{current_price}\nMarket Overbought. Take Profit/Short!"
                
                # Spam Protection: প্রতি ঘণ্টায় একবারের বেশি একই মেসেজ পাঠাবে না
                today_hour = datetime.now().strftime("%Y-%m-%d_%H")
                alert_key = f"{stock}_{today_hour}_{'BUY' if 'BUY' in message else 'SELL'}"
                
                if message and (alert_key not in last_alert):
                    send_telegram_alert(message)
                    last_alert[alert_key] = True
                    
        except Exception as e:
            pass
            
        time.sleep(900) 

threading.Thread(target=background_scanner, daemon=True).start()

# ==========================================
# MAIN ROUTES
# ==========================================
@app.route('/')
def home():
    return "Server is Awake and Running Intraday Mode!"

@app.route('/get_best_trades')
def get_best_trades():
    trades = []
    for stock in STOCKS:
        try:
            df = get_market_data(stock)
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            current_price = round(latest['close'], 2)
            rsi = round(latest['RSI'], 2)
            atr = round(latest['ATR'], 2)
            change_percent = round(((current_price - prev['close']) / prev['close']) * 100, 2)
            
            volatility_percent = (atr / current_price) * 100
            if volatility_percent > 1.5: # Adjusted for 15m timeframe
                market_condition = "High Momentum 🌪️"
                vol_color = "#0ecb81"
            elif volatility_percent < 0.3:
                market_condition = "Dead / Boring Market 😴"
                vol_color = "#848e9c"
            else:
                market_condition = "Perfect for Intraday 🎯"
                vol_color = "#0ecb81"
                
            sentiment = "Extreme Greed 🤑" if rsi > 75 else ("Extreme Fear 😨" if rsi < 25 else "Neutral ⚖️")
            
            signal = "WAIT / HOLD 🟡"
            confidence = 0
            trend = "Bullish 📈" if latest['EMA_50'] > latest['EMA_200'] else "Bearish 📉"
            
            if trend == "Bullish 📈" and rsi < 60 and latest['MACD'] > latest['Signal_Line']:
                signal = "BUY 🟢"
                confidence = 70
                if rsi < 40: 
                    signal = "STRONG BUY 🚀"
                    confidence = 90
            elif trend == "Bearish 📉" and rsi > 40 and latest['MACD'] < latest['Signal_Line']:
                signal = "SELL 🔴"
                confidence = 70
                if rsi > 70:
                    signal = "STRONG SELL 💥"
                    confidence = 90
                    
            if "BUY" in signal or "SELL" in signal:
                stop_loss_distance = atr * 1.5
                target_distance = stop_loss_distance * 2 
                target = round(current_price + target_distance, 2) if "BUY" in signal else round(current_price - target_distance, 2)
                stop_loss = round(current_price - stop_loss_distance, 2) if "BUY" in signal else round(current_price + stop_loss_distance, 2)
                
                # ⚡ Timeframe text changed for Intraday
                expected_candles = max(1, round(target_distance / atr))
                timeframe = f"Intraday ({expected_candles} to {expected_candles + 4} Candles) ⏳"
                action_text = f"Intraday Buy at ₹{current_price}." if "BUY" in signal else "Intraday Sell/Short."
            else:
                target = "--"
                stop_loss = "--"
                timeframe = "N/A"
                action_text = "Wait for 15m candle breakout."
                
            trades.append({
                "stock": stock.replace(".NS", ""),
                "price": current_price,
                "change": change_percent,
                "signal": signal,
                "confidence": confidence,
                "sentiment": sentiment,
                "market_condition": market_condition,
                "vol_color": vol_color,
                "target": target,
                "stop_loss": stop_loss,
                "timeframe": timeframe,
                "action_text": action_text
            })
        except Exception as e:
            pass
            
    trades.sort(key=lambda x: x['confidence'], reverse=True)
    return jsonify({"status": "success", "data": trades})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
