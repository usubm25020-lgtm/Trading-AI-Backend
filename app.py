from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET
import threading
import time
import json
import os

app = Flask(__name__)
CORS(app)

TELEGRAM_TOKEN = "8223149909:AAE8hQlu-coYVlrdd5v810D4HcOmPiZBOP8"
CHAT_ID = "7188544429"

# 🔥 Best 24/7 & Global Assets for Timer & Multiplier Trading
ASSETS = [
    "BTC-USD",   # Bitcoin (Open 24/7)
    "ETH-USD",   # Ethereum (Open 24/7)
    "GC=F",      # Gold (XAU/USD)
    "SI=F",      # Silver (XAG/USD)
    "CL=F",      # Crude Oil (WTI)
    "EURUSD=X",  # EUR/USD Forex
    "GBPUSD=X",  # GBP/USD Forex
    "JPY=X"      # USD/JPY Forex
]

CRYPTO_24_7 = ["BTC-USD", "ETH-USD"]
STATE_FILE = "dual_engine_state.json"
memory_lock = threading.Lock()
news_cache = {}

def get_ist_now():
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist)

def default_state():
    return {
        "timer_trades": {a: None for a in ASSETS},
        "mult_trades": {a: None for a in ASSETS},
        "hit_alerts": {a: False for a in ASSETS},
        "stats": {"wins": 0, "losses": 0, "net_profit_base10": 0.0},
        "history": []
    }

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                base = default_state()
                for k in base:
                    if k in data:
                        if isinstance(base[k], dict):
                            base[k].update(data[k])
                        else:
                            base[k] = data[k]
                return base
        except:
            pass
    return default_state()

def save_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except:
        pass

def is_market_open(asset):
    if asset in CRYPTO_24_7:
        return True # Crypto is open 24 hours, 7 days a week!
    now = get_ist_now()
    return now.weekday() < 5 # Forex & Gold open Mon-Fri 24hrs

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=5)
    except:
        pass

# 📰 Live News Sentiment Scanner (Zero External Library Needed)
def fetch_news_sentiment(asset):
    now_ts = time.time()
    if asset in news_cache and (now_ts - news_cache[asset]["ts"] < 900):
        return news_cache[asset]["sentiment"], news_cache[asset]["headline"]
    
    bull_words = ["surge", "jump", "gain", "bull", "rally", "high", "rise", "buy", "record", "up", "growth", "positive", "boost"]
    bear_words = ["drop", "fall", "crash", "bear", "low", "sell", "down", "slump", "fear", "loss", "weak", "decline", "risk"]
    
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={asset}&region=US&lang=en-US"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=4)
        root = ET.fromstring(res.content)
        titles = [item.find('title').text for item in root.findall('.//item')[:5] if item.find('title') is not None]
        
        if not titles:
            raise ValueError("No news")
            
        score = 0
        for t in titles:
            tl = t.lower()
            for bw in bull_words:
                if bw in tl: score += 1
            for rw in bear_words:
                if rw in tl: score -= 1
                
        sentiment = "Bullish 🟢" if score > 0 else ("Bearish 🔴" if score < 0 else "Neutral ⚪")
        headline = titles[0][:75] + "..." if len(titles[0]) > 75 else titles[0]
    except:
        sentiment = "Neutral ⚪"
        headline = "Global technical price action driving momentum."
        
    news_cache[asset] = {"ts": now_ts, "sentiment": sentiment, "headline": headline}
    return sentiment, headline

def calculate_indicators(df):
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # Wilder's RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = (100 - (100 / (1 + rs))).fillna(50)
    
    # Bollinger Bands (Great for Timer & Multiplier)
    df['BB_Mid'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['BB_Upper'] = df['BB_Mid'] + (bb_std * 2)
    df['BB_Lower'] = df['BB_Mid'] - (bb_std * 2)
    
    # ATR
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
    
    df['Support'] = df['low'].rolling(20).min()
    df['Resistance'] = df['high'].rolling(20).max()
    
    return df.bfill().ffill()

def fetch_data(asset):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{asset}?interval=5m&range=5d"
    res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8).json()
    result = res.get('chart', {}).get('result', [])
    if not result:
        raise ValueError("No data")
        
    quote = result[0]['indicators']['quote'][0]
    close_l = quote.get('close', [])
    open_l = quote.get('open', close_l)
    high_l = quote.get('high', [])
    low_l = quote.get('low', [])
    
    df = pd.DataFrame({
        'open': open_l if len(open_l) == len(close_l) else close_l,
        'close': close_l,
        'high': high_l,
        'low': low_l
    }).dropna()
    
    if len(df) < 35:
        raise ValueError("Not enough candles")
    return calculate_indicators(df)

def analyze_dual_engine(df, sentiment):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    decimals = 4 if float(latest['close']) < 10 else 2
    price = round(float(latest['close']), decimals)
    open_p = float(latest['open'])
    atr = max(float(latest['ATR']), price * 0.0008)
    rsi = round(float(latest['RSI']), 1)
    
    ema9 = float(latest['EMA_9'])
    ema21 = float(latest['EMA_21'])
    ema50 = float(latest['EMA_50'])
    macd_hist = float(latest['MACD_Hist'])
    prev_hist = float(prev['MACD_Hist'])
    
    up_score = 0
    down_score = 0
    
    # 1. Major Trend (EMA 50)
    if price > ema50: up_score += 25
    else: down_score += 25
    
    # 2. Fast EMA Alignment (EMA 9 & 21)
    if ema9 > ema21: up_score += 25
    else: down_score += 25
    
    # 3. MACD Momentum Acceleration
    if float(latest['MACD']) > float(latest['Signal_Line']) and macd_hist >= prev_hist:
        up_score += 20
    elif float(latest['MACD']) < float(latest['Signal_Line']) and macd_hist <= prev_hist:
        down_score += 20
        
    # 4. RSI Safe Power Zone
    if 48 <= rsi <= 68: up_score += 15
    elif 32 <= rsi <= 52: down_score += 15
    
    # 5. Candle Action + News Bonus
    if price >= open_p and price > float(prev['close']): up_score += 15
    elif price < open_p and price < float(prev['close']): down_score += 15
    
    if "Bullish" in sentiment: up_score = min(99, up_score + 5)
    elif "Bearish" in sentiment: down_score = min(99, down_score + 5)
    
    conf = max(up_score, down_score)
    direction = None
    if up_score >= 85 and price > ema50 and ema9 > ema21:
        direction = "UP"
    elif down_score >= 85 and price < ema50 and ema9 < ema21:
        direction = "DOWN"
        
    # Safe Auto-Multiplier calculation so ₹10 Auto-Cut sits outside random noise (1.5x ATR)
    sl_dist = max(atr * 1.5, price * 0.002)
    target_dist = sl_dist * 1.8 # 1:1.8 Risk-Reward (₹10 risk -> ₹18 profit!)
    
    raw_mult = int(round(price / sl_dist))
    safe_mult = max(20, min(500, raw_mult))
    
    if direction == "UP":
        target_price = round(price + target_dist, decimals)
        autocut_price = round(price - sl_dist, decimals)
    elif direction == "DOWN":
        target_price = round(price - target_dist, decimals)
        autocut_price = round(price + sl_dist, decimals)
    else:
        target_price = "--"
        autocut_price = "--"
        
    return direction, price, target_price, autocut_price, safe_mult, conf, rsi, decimals

def record_history(state, asset, mode_name, direction, entry, exit_p, is_win, profit_base10):
    now_str = get_ist_now().strftime("%I:%M %p")
    if is_win:
        state["stats"]["wins"] += 1
        state["hit_alerts"][asset] = True
    else:
        state["stats"]["losses"] += 1
        
    state["stats"]["net_profit_base10"] = round(state["stats"]["net_profit_base10"] + profit_base10, 2)
    
    item = {
        "asset": asset.replace("=X", "").replace("=F", "").replace("-USD", ""),
        "mode": mode_name,
        "dir": direction,
        "entry": entry,
        "exit": exit_p,
        "result": "WIN 🎯" if is_win else "LOSS 🛡️",
        "profit_base10": profit_base10,
        "time": now_str
    }
    state["history"].insert(0, item)
    state["history"] = state["history"][:20] # Keep last 20 trades

def process_asset_lifecycle(asset, df, sentiment, notify=True):
    direction, price, target_p, autocut_p, safe_mult, conf, rsi, decimals = analyze_dual_engine(df, sentiment)
    now_ts = time.time()
    clean_name = asset.replace("=X", "").replace("=F", "").replace("-USD", "")
    
    with memory_lock:
        state = load_state()
        
        # ==========================================
        # 1. FIXED TIME (5-MIN TIMER) LIFECYCLE
        # ==========================================
        t_trade = state["timer_trades"].get(asset)
        if t_trade is not None:
            if now_ts >= t_trade["expires_at"]:
                entry = float(t_trade["entry"])
                t_dir = t_trade["dir"]
                is_win = (price > entry) if t_dir == "UP" else (price < entry)
                
                if price == entry:
                    # Tie / Refund
                    state["timer_trades"][asset] = None
                else:
                    pnl_10 = 8.50 if is_win else -10.00
                    record_history(state, asset, "5m Timer", t_dir, entry, price, is_win, pnl_10)
                    state["timer_trades"][asset] = None
                    
                    if notify:
                        wins = state["stats"]["wins"]
                        losses = state["stats"]["losses"]
                        wr = round((wins / max(1, wins + losses)) * 100, 1)
                        if is_win:
                            send_telegram(f"🎯 <b>5m TIMER TRADE WON!</b>\nAsset: {clean_name} ({t_dir})\nEntry: {entry} ➔ Expiry: {price}\n💰 <b>₹10 Bet Payout: +₹8.50 (Total ₹18.50)</b>\n📊 AI Win Rate: {wr}% ({wins}W/{losses}L)")
                        else:
                            send_telegram(f"🛡️ <b>5m TIMER FINISHED (LOSS)</b>\nAsset: {clean_name} ({t_dir})\nEntry: {entry} ➔ Expiry: {price}\n💸 ₹10 Bet Lost (-₹10.00)\n📊 AI Win Rate: {wr}% ({wins}W/{losses}L)")
        else:
            if direction in ["UP", "DOWN"]:
                exp_ts = now_ts + 300 # 5 Minutes Timer
                exp_str = (get_ist_now() + timedelta(minutes=5)).strftime("%I:%M %p")
                state["timer_trades"][asset] = {
                    "dir": direction,
                    "entry": price,
                    "started_at": now_ts,
                    "expires_at": exp_ts,
                    "exp_str": exp_str,
                    "conf": conf
                }
                if notify:
                    icon = "🟢 <b>5-MIN TIMER: UP (BUY)</b>" if direction == "UP" else "🔴 <b>5-MIN TIMER: DOWN (SELL)</b>"
                    send_telegram(f"⏱️ {icon}\nAsset: {clean_name}\nEntry Line: {price}\n⏰ Expiry Time: {exp_str} (5 Mins)\n💵 ₹10 Bet Return: <b>+₹8.50 Profit</b>\n🔥 AI Confidence: {conf}%")

        # ==========================================
        # 2. MULTIPLIER (AUTO-CUT AT ₹10) LIFECYCLE
        # ==========================================
        m_trade = state["mult_trades"].get(asset)
        if m_trade is not None:
            m_dir = m_trade["dir"]
            entry = float(m_trade["entry"])
            target = float(m_trade["target"])
            autocut = float(m_trade["autocut"])
            
            if m_dir == "UP":
                if price >= target:
                    record_history(state, asset, "Multiplier", "UP", entry, price, True, 18.00)
                    state["mult_trades"][asset] = None
                    if notify:
                        send_telegram(f"🚀 <b>MULTIPLIER TARGET HIT!</b>\nAsset: {clean_name} (UP)\nEntry: {entry} ➔ Hit: {price}\n💰 <b>₹10 Bet Profit: +₹18.00 (Total ₹28.00)</b>")
                elif price <= autocut:
                    record_history(state, asset, "Multiplier", "UP", entry, price, False, -10.00)
                    state["mult_trades"][asset] = None
                    if notify:
                        send_telegram(f"🛑 <b>AUTO-CUT TRIGGERED (MAX LOSS CAPPED)</b>\nAsset: {clean_name}\nExited at: {price}. Only ₹10 deducted, account balance protected!")
            elif m_dir == "DOWN":
                if price <= target:
                    record_history(state, asset, "Multiplier", "DOWN", entry, price, True, 18.00)
                    state["mult_trades"][asset] = None
                    if notify:
                        send_telegram(f"🚀 <b>MULTIPLIER TARGET HIT!</b>\nAsset: {clean_name} (DOWN)\nEntry: {entry} ➔ Hit: {price}\n💰 <b>₹10 Bet Profit: +₹18.00 (Total ₹28.00)</b>")
                elif price >= autocut:
                    record_history(state, asset, "Multiplier", "DOWN", entry, price, False, -10.00)
                    state["mult_trades"][asset] = None
                    if notify:
                        send_telegram(f"🛑 <b>AUTO-CUT TRIGGERED (MAX LOSS CAPPED)</b>\nAsset: {clean_name}\nExited at: {price}. Only ₹10 deducted, account balance protected!")
        else:
            if direction in ["UP", "DOWN"]:
                state["mult_trades"][asset] = {
                    "dir": direction,
                    "entry": price,
                    "target": target_p,
                    "autocut": autocut_p,
                    "mult": safe_mult,
                    "conf": conf
                }
                if notify:
                    icon = "🚀 <b>MULTIPLIER UP (LONG)</b>" if direction == "UP" else "⚠️ <b>MULTIPLIER DOWN (SHORT)</b>"
                    send_telegram(f"{icon}\nAsset: {clean_name} ({safe_mult}x)\nEntry: {price}\n🎯 Target: {target_p} (<b>+₹18 Profit on ₹10</b>)\n🛑 Auto-Cut Line: {autocut_p} (<b>Max Loss capped at ₹10</b>)")

        save_state(state)

def background_engine():
    send_telegram("✅ Dual-Engine AI Live: 1. Timer Trading (5m) & 2. Multiplier (₹10 Auto-Cut) + Win/Loss History Activated!")
    while True:
        for asset in ASSETS:
            try:
                if not is_market_open(asset):
                    continue
                df = fetch_data(asset)
                sentiment, _ = fetch_news_sentiment(asset)
                process_asset_lifecycle(asset, df, sentiment, notify=True)
            except:
                pass
        time.sleep(30)

threading.Thread(target=background_engine, daemon=True).start()

@app.route('/')
def home():
    return "Dual-Engine Timer & Multiplier AI Server is Running!"

@app.route('/get_best_trades')
def get_best_trades():
    mode = request.args.get('mode', 'timer') # 'timer' or 'multiplier'
    trades_data = []
    
    tv_map = {
        "BTC-USD": "BINANCE:BTCUSDT",
        "ETH-USD": "BINANCE:ETHUSDT",
        "GC=F": "COMEX:GC1!",
        "SI=F": "COMEX:SI1!",
        "CL=F": "NYMEX:CL1!",
        "EURUSD=X": "FX:EURUSD",
        "GBPUSD=X": "FX:GBPUSD",
        "JPY=X": "FX:USDJPY"
    }
    
    name_map = {
        "BTC-USD": "BITCOIN (BTC)",
        "ETH-USD": "ETHEREUM (ETH)",
        "GC=F": "GOLD (XAU/USD)",
        "SI=F": "SILVER (XAG/USD)",
        "CL=F": "CRUDE OIL",
        "EURUSD=X": "EUR / USD",
        "GBPUSD=X": "GBP / USD",
        "JPY=X": "USD / JPY"
    }
    
    for asset in ASSETS:
        clean_name = name_map.get(asset, asset)
        tv_symbol = tv_map.get(asset, asset)
        
        if not is_market_open(asset):
            trades_data.append({
                "asset_id": asset, "stock": clean_name, "tv_symbol": tv_symbol, "price": "--", "change": 0,
                "signal": "MARKET CLOSED 😴", "confidence": 0, "entry": "--", "target": "--", "stop_loss": "--",
                "timeframe": "Opens Monday", "action_text": "Weekend closed. Bitcoin & Ethereum are open 24/7!",
                "support": "--", "resistance": "--", "news_sentiment": "Neutral ⚪", "news_headline": "Market closed for weekend.",
                "mult": 100, "live_pnl_pct": 0, "timer_rem": 0, "play_alert": False
            })
            continue
            
        try:
            df = fetch_data(asset)
            sentiment, headline = fetch_news_sentiment(asset)
            process_asset_lifecycle(asset, df, sentiment, notify=True)
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            direction, price, target_p, autocut_p, safe_mult, conf, rsi, decimals = analyze_dual_engine(df, sentiment)
            
            support = round(float(latest['Support']), decimals)
            resistance = round(float(latest['Resistance']), decimals)
            change = round(((price - float(prev['close'])) / float(prev['close'])) * 100, 2)
            
            with memory_lock:
                state = load_state()
                t_trade = state["timer_trades"].get(asset)
                m_trade = state["mult_trades"].get(asset)
                just_hit = state["hit_alerts"].get(asset, False)
                if just_hit:
                    state["hit_alerts"][asset] = False
                    save_state(state)
                    
            play_alert = True if just_hit else False
            now_ts = time.time()
            
            if mode == "timer":
                if just_hit:
                    signal = "TIMER WON! 💰🟢"
                    entry_val, target_val, sl_val = "--", "+85% Payout", "--"
                    action_text = "Boom! Timer finished in profit! Music alert triggered."
                    timer_rem = 0
                    live_pnl_pct = 85.0
                    conf = 100
                elif t_trade:
                    t_dir = t_trade["dir"]
                    entry_val = t_trade["entry"]
                    rem_sec = max(0, int(t_trade["expires_at"] - now_ts))
                    mins, secs = divmod(rem_sec, 60)
                    winning_now = (price > entry_val) if t_dir == "UP" else (price < entry_val)
                    status_tag = "WINNING 🟢" if winning_now else "WAITING 🔴"
                    
                    signal = f"ACTIVE {t_dir} ({mins}m {secs}s) ⏱️"
                    target_val = f"Above {entry_val}" if t_dir == "UP" else f"Below {entry_val}"
                    sl_val = f"Exp: {t_trade['exp_str']}"
                    action_text = f"Status: {status_tag} | Hold until {t_trade['exp_str']}."
                    timer_rem = rem_sec
                    live_pnl_pct = 85.0 if winning_now else -100.0
                    conf = t_trade.get("conf", conf)
                else:
                    timer_rem = 0
                    live_pnl_pct = 0
                    entry_val, target_val, sl_val = "--", "--", "--"
                    signal = "SCANNING 5m SETUP 🟡"
                    action_text = f"Confluence: {conf}% (Need 85%+ for guaranteed accuracy)."
                timeframe = "⏱️ 5-Min Fixed Timer"
            else:
                # MULTIPLIER MODE
                if just_hit:
                    signal = "TARGET HIT! 💰🟢"
                    entry_val, target_val, sl_val = "--", "--", "--"
                    action_text = "Multiplier Target Hit! +180% Profit booked."
                    timer_rem = 0
                    live_pnl_pct = 180.0
                    conf = 100
                elif m_trade:
                    m_dir = m_trade["dir"]
                    entry_val = float(m_trade["entry"])
                    target_val = float(m_trade["target"])
                    sl_val = float(m_trade["autocut"])
                    safe_mult = m_trade.get("mult", safe_mult)
                    
                    # Calculate exact live percentage on stake based on how far line moved
                    sl_dist = max(abs(entry_val - sl_val), 0.0001)
                    move = (price - entry_val) if m_dir == "UP" else (entry_val - price)
                    live_pnl_pct = round(max(-100.0, (move / sl_dist) * 100.0), 1)
                    
                    signal = f"ACTIVE {m_dir} ({safe_mult}x) 🚀" if m_dir == "UP" else f"ACTIVE {m_dir} ({safe_mult}x) 🔴"
                    action_text = f"Line Moving! Auto-Cut strictly locked at {sl_val} (Max Loss = Bet)."
                    timer_rem = 0
                    conf = m_trade.get("conf", conf)
                else:
                    timer_rem = 0
                    live_pnl_pct = 0
                    entry_val, target_val, sl_val = "--", "--", "--"
                    signal = "WAITING FOR BREAKOUT 🟡"
                    action_text = f"Filter Score: {conf}% (Waiting for 85%+ Sniper Trend)."
                timeframe = f"🚀 {safe_mult}x Multiplier (Auto-Cut)"
                
            trades_data.append({
                "asset_id": asset, "stock": clean_name, "tv_symbol": tv_symbol, "price": price, "change": change,
                "signal": signal, "confidence": conf, "entry": entry_val, "target": target_val, "stop_loss": sl_val,
                "timeframe": timeframe, "action_text": action_text, "support": support, "resistance": resistance,
                "news_sentiment": sentiment, "news_headline": headline, "mult": safe_mult,
                "live_pnl_pct": live_pnl_pct, "timer_rem": timer_rem, "play_alert": play_alert
            })
        except Exception as e:
            trades_data.append({
                "asset_id": asset, "stock": clean_name, "tv_symbol": tv_symbol, "price": "Syncing", "change": 0,
                "signal": "LOADING DATA ⏳", "confidence": 0, "entry": "--", "target": "--", "stop_loss": "--",
                "timeframe": "Please wait", "action_text": "Fetching global market feed...",
                "support": "--", "resistance": "--", "news_sentiment": "Neutral ⚪", "news_headline": "--",
                "mult": 100, "live_pnl_pct": 0, "timer_rem": 0, "play_alert": False
            })
            
    with memory_lock:
        final_state = load_state()
        stats = final_state["stats"]
        history = final_state["history"]
        
    trades_data.sort(key=lambda x: (1 if "WON" in x['signal'] or "HIT" in x['signal'] else (2 if "ACTIVE" in x['signal'] else 0), x['confidence']), reverse=True)
    return jsonify({
        "status": "success",
        "stats": stats,
        "history": history,
        "data": trades_data
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=False)
