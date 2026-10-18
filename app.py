from flask import Flask, jsonify
from flask_cors import CORS
import requests
import pandas as pd
import numpy as np
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ==========================================
# TELEGRAM SETTINGS (Ekhane apnar details din)
# ==========================================
TELEGRAM_TOKEN = "8223149909:AAE8hQlu-coYVlrdd5v810D4HcOmPiZBOP8"
CHAT_ID = "7188544429"

STOCKS = ["RELIANCE.NS", "TATAMOTORS.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "SBIN.NS"]

# Alert spam atkanor jonno record (jate bar bar eki message na ase)
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
    df['ATR'] = np.max(ranges, axis=1).rolling(14).mean()
    
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    return df

# UI-er jonno data pathanor route (Spck Editor-er jonno)
@app.route('/get_best_trades')
def get_best_trades():
    trades = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for stock in STOCKS:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock}?interval=1d&range=1y"
            res = requests.get(url, headers=headers).json()
            quote = res['chart']['result'][0]['indicators']['quote'][0]
            
            df = pd.DataFrame({
                'close': quote['close'],
                'high': quote['high'],
                'low': quote['low']
            }).dropna()
            
            df = calculate_advanced_indicators(df)
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            current_price = round(latest['close'], 2)
            rsi = round(latest['RSI'], 2)
            atr = round(latest['ATR'], 2)
            change_percent = round(((current_price - prev['close']) / prev['close']) * 100, 2)
            
            trend = "Bullish" if latest['EMA_50'] > latest['EMA_200'] else "Bearish"
            signal = "WAIT / HOLD"
            confidence = 0
            
            if trend == "Bullish" and rsi < 60 and latest['MACD'] > latest['Signal_Line']:
                signal = "BUY"
                confidence = 65
                if rsi < 40:
                    signal = "STRONG BUY"
                    confidence = 85
            elif trend == "Bearish" and rsi > 40 and latest['MACD'] < latest['Signal_Line']:
                signal = "SELL"
                confidence = 65
                if rsi > 70:
                    signal = "STRONG SELL"
                    confidence = 85
                    
            trades.append({
                "stock": stock.replace(".NS", ""),
                "price": current_price,
                "change": change_percent,
                "signal": signal,
                "confidence": confidence,
                "target": round(current_price + (atr * 3), 2) if "BUY" in signal else "--",
                "stop_loss": round(current_price - (atr * 1.5), 2) if "BUY" in signal else "--"
            })
        except Exception as e:
            pass
            
    trades.sort(key=lambda x: x['confidence'], reverse=True)
    return jsonify({"status": "success", "data": trades})

# TELEGRAM AUTO SCANNER ROUTE (Eta background e cholbe)
@app.route('/auto_scan')
def auto_scan():
    global last_alert
    headers = {'User-Agent': 'Mozilla/5.0'}
    alerts_sent = 0
    
    for stock in STOCKS:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock}?interval=1d&range=1y"
            res = requests.get(url, headers=headers).json()
            quote = res['chart']['result'][0]['indicators']['quote'][0]
            df = pd.DataFrame({'close': quote['close'], 'high': quote['high'], 'low': quote['low']}).dropna()
            df = calculate_advanced_indicators(df)
            latest = df.iloc[-1]
            
            current_price = round(latest['close'], 2)
            rsi = round(latest['RSI'], 2)
            atr = round(latest['ATR'], 2)
            
            # Smart Alert Logic
            message = ""
            if rsi < 35 and latest['MACD'] > latest['Signal_Line']:
                target = round(current_price + (atr * 3), 2)
                stop_loss = round(current_price - (atr * 1.5), 2)
                message = f"🚀 <b>STRONG BUY ALERT</b>\nStock: {stock}\nPrice: ₹{current_price}\nRSI: {rsi}\nTarget: ₹{target}\nStop Loss: ₹{stop_loss}"
                
            elif rsi > 75:
                message = f"⚠️ <b>DANGER / SELL ALERT</b>\nStock: {stock}\nPrice: ₹{current_price}\nMarket Overbought (Greed). Take Profit!"
            
            # Spam protection (Ekdine ekta stock er jnno barbar msg jabe na)
            today = datetime.now().strftime("%Y-%m-%d")
            alert_key = f"{stock}_{today}_{'BUY' if 'BUY' in message else 'SELL'}"
            
            if message and (alert_key not in last_alert):
                send_telegram_alert(message)
                last_alert[alert_key] = True
                alerts_sent += 1
                
        except Exception as e:
            pass
            
    return jsonify({"status": "Scanner executed", "alerts_sent": alerts_sent})
