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

ASSETS = [
    "BTC-USD",   # Bitcoin (24/7)
    "ETH-USD",   # Ethereum (24/7)
    "GC=F",      # Gold (XAU/USD)
    "SI=F",      # Silver (XAG/USD)
    "CL=F",      # Crude Oil (WTI)
    "EURUSD=X",  # EUR/USD
    "GBPUSD=X",  # GBP/USD
    "JPY=X"      # USD/JPY
]

CRYPTO_24_7 = ["BTC-USD", "ETH-USD"]
STATE_FILE = "quantum_sniper_v4.json" # Fresh state file (resets old buggy losses)
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
        return True
    now = get_ist_now()
    return now.weekday() < 5

def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=5)
    except:
        pass

# 📰 Smart Pair-Aware News Sentiment Scanner
def fetch_news_sentiment(asset):
    now_ts = time.time()
    if asset in news_cache and (now_ts - news_cache[asset]["ts"] < 900):
        return news_cache[asset]["sentiment"], news_cache[asset]["headline"]
    
    bull_words = ["surge", "jump", "gain", "bull", "rally", "high", "rise", "record", "up", "growth", "boost", "firms"]
    bear_words = ["drop", "fall", "falls", "crash", "bear", "low", "sell", "down", "slump", "fear", "loss", "weak", "decline"]
    
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
            # Fix USD/JPY & Dollar specific inversion
            if asset == "JPY=X" and ("dollar falls" in tl or "lifts yen" in tl or "yen surges" in tl):
                score -= 3
                continue
            for bw in bull_words:
                if bw in tl: score += 1
            for rw in bear_words:
                if rw in tl: score -= 1
                
        sentiment = "Bullish 🟢" if score > 0 else ("Bearish 🔴" if score < 0 else "Neutral ⚪")
        headline = titles[0][:78] + "..." if len(titles[0]) > 78 else titles[0]
    except:
        sentiment = "Neutral ⚪"
        headline = "Pure institutional price action & volume flow active."
        
    news_cache[asset] = {"ts": now_ts, "sentiment": sentiment, "headline": headline}
    return sentiment, headline

def calculate_quantum_indicators(df):
    # Fast & Major EMAs on 1-Minute Chart
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # Wilder's Smooth RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = (100 - (100 / (1 + rs))).fillna(50)
    
    # Stochastic Oscillator (Pinpoints exact bottom/top turns)
    low_14 = df['low'].rolling(14).min()
    high_14 = df['high'].rolling(14).max()
    denom = (high_14 - low_14).replace(0, 1)
    df['Stoch_K'] = (((df['close'] - low_14) / denom) * 100).rolling(3).mean().fillna(50)
    
    # ATR (Volatility)
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
    
    # Dynamic Support & Resistance (30-candle channel)
    df['Support'] = df['low'].rolling(30).min()
    df['Resistance'] = df['high'].rolling(30).max()
    
    return df.bfill().ffill()

# ⚡ 1-Minute Ultra-Fast Live Data Feed (Fixes stale price bug!)
def fetch_data(asset):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{asset}?interval=1m&range=1d"
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
    
    if len(df) < 55:
        # Fallback to 5m if 1m session just started
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{asset}?interval=5m&range=5d"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=8).json()
        quote = res['chart']['result'][0]['indicators']['quote'][0]
        df = pd.DataFrame({
            'open': quote.get('open', quote['close']),
            'close': quote['close'],
            'high': quote['high'],
            'low': quote['low']
        }).dropna()
        
    return calculate_quantum_indicators(df)

def analyze_quantum_setup(df, sentiment):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]
    
    decimals = 4 if float(latest['close']) < 10 else 2
    price = round(float(latest['close']), decimals)
    open_p = float(latest['open'])
    atr = max(float(latest['ATR']), price * 0.0004)
    rsi = round(float(latest['RSI']), 1)
    stoch = round(float(latest['Stoch_K']), 1)
    
    ema9 = float(latest['EMA_9'])
    ema21 = float(latest['EMA_21'])
    ema50 = float(latest['EMA_50'])
    
    macd_hist = float(latest['MACD_Hist'])
    prev_hist = float(prev['MACD_Hist'])
    
    # Trend & Momentum Confluence Scoring
    up_score = 0
    down_score = 0
    
    # 1. Macro Trend Alignment (EMA 21 vs EMA 50)
    if ema21 > ema50 and price > ema50: up_score += 25
    elif ema21 < ema50 and price < ema50: down_score += 25
    
    # 2. Micro Trend (EMA 9 > EMA 21)
    if ema9 > ema21: up_score += 20
    elif ema9 < ema21: down_score += 20
    
    # 3. MACD Histogram Rising / Falling
    if macd_hist > prev_hist and float(latest['MACD']) >= float(latest['Signal_Line']):
        up_score += 20
    elif macd_hist < prev_hist and float(latest['MACD']) <= float(latest['Signal_Line']):
        down_score += 20
        
    # 4. Safe Pullback Zone (Never buy at extreme top >72, never sell at extreme bottom <28)
    if 42 <= rsi <= 66 and stoch < 82: up_score += 20
    elif 34 <= rsi <= 58 and stoch > 18: down_score += 20
    
    # 5. Live Candle Breakout Confirmation
    is_bull_bounce = (price > open_p) and (price > float(prev['close']))
    is_bear_drop = (price < open_p) and (price < float(prev['close']))
    
    if is_bull_bounce: up_score += 15
    elif is_bear_drop: down_score += 15
    
    # News Conflict Protection (Never trade against strong news)
    if "Bearish" in sentiment: up_score -= 20
    if "Bullish" in sentiment: down_score -= 20
    
    conf = max(0, min(98, max(up_score, down_score)))
    direction = None
    if up_score >= 85 and is_bull_bounce:
        direction = "UP"
    elif down_score >= 85 and is_bear_drop:
        direction = "DOWN"
        
    # 🚀 DYNAMIC MULTIPLIER & EXPECTED X-FACTOR CALCULATION
    # Stop-loss distance (1x risk unit = ₹10 Bet)
    sl_dist = max(atr * 1.6, price * 0.0008)
    raw_leverage = int(round(price / sl_dist))
    broker_mult = max(25, min(500, raw_leverage))
    
    # Calculate how many X (2x, 3.5x, 5x, 8x, 10x) this wave can realistically run!
    trend_strength = abs(ema9 - ema50) / max(atr, 0.00001)
    room_up = max(0.0, float(latest['Resistance']) - price) / sl_dist
    room_down = max(0.0, price - float(latest['Support'])) / sl_dist
    room_x = room_up if (up_score >= down_score) else room_down
    
    # Expected X-Payout Multiplier on Bet (Between 2.0x and 10.0x)
    potential_x = round(min(10.0, max(2.2, 2.0 + (trend_strength * 0.75) + (min(room_x, 5.0) * 0.45))), 1)
    target_dist = sl_dist * potential_x
    
    if direction == "UP" or up_score >= down_score:
        target_price = round(price + target_dist, decimals)
        autocut_price = round(price - sl_dist, decimals)
        t_2x = round(price + (sl_dist * 2.0), decimals)
        t_5x = round(price + (sl_dist * 5.0), decimals)
        t_10x = round(price + (sl_dist * 10.0), decimals)
    else:
        target_price = round(price - target_dist, decimals)
        autocut_price = round(price + sl_dist, decimals)
        t_2x = round(price - (sl_dist * 2.0), decimals)
        t_5x = round(price - (sl_dist * 5.0), decimals)
        t_10x = round(price - (sl_dist * 10.0), decimals)
        
    milestones = {"m2x": t_2x, "m5x": t_5x, "m10x": t_10x}
    return direction, price, target_price, autocut_price, sl_dist, broker_mult, potential_x, milestones, conf, rsi, decimals

def record_history(state, asset, mode_name, direction, entry, exit_p, is_win, profit_base10, x_hit=""):
    now_str = get_ist_now().strftime("%I:%M %p")
    if is_win:
        state["stats"]["wins"] += 1
        state["hit_alerts"][asset] = True
    else:
        state["stats"]["losses"] += 1
        
    state["stats"]["net_profit_base10"] = round(state["stats"]["net_profit_base10"] + profit_base10, 2)
    
    item = {
        "asset": asset.replace("=X", "").replace("=F", "").replace("-USD", ""),
        "mode": f"{mode_name} {x_hit}".strip(),
        "dir": direction,
        "entry": entry,
        "exit": exit_p,
        "result": "WIN 🎯" if is_win else "LOSS 🛡️",
        "profit_base10": round(profit_base10, 2),
        "time": now_str
    }
    state["history"].insert(0, item)
    state["history"] = state["history"][:25]

def process_asset_lifecycle(asset, df, sentiment, notify=True):
    direction, price, target_p, autocut_p, sl_dist, broker_mult, potential_x, milestones, conf, rsi, decimals = analyze_quantum_setup(df, sentiment)
    now_ts = time.time()
    clean_name = asset.replace("=X", "").replace("=F", "").replace("-USD", "")
    
    with memory_lock:
        state = load_state()
        
        # =========================================================
        # 1. SMART 3-MIN TIMER LIFECYCLE (Fast 1m Candle Precision)
        # =========================================================
        t_trade = state["timer_trades"].get(asset)
        if t_trade is not None:
            entry = float(t_trade["entry"])
            t_dir = t_trade["dir"]
            rem_sec = t_trade["expires_at"] - now_ts
            
            if rem_sec <= 0:
                if abs(price - entry) <= (price * 0.00002):
                    # Exact Tie = Refund (NEVER count a tie as a loss!)
                    state["timer_trades"][asset] = None
                else:
                    is_win = (price > entry) if t_dir == "UP" else (price < entry)
                    pnl_10 = 8.50 if is_win else -10.00
                    record_history(state, asset, "Timer", t_dir, entry, price, is_win, pnl_10, "(+85%)")
                    state["timer_trades"][asset] = None
                    
                    if notify:
                        wins = state["stats"]["wins"]
                        losses = state["stats"]["losses"]
                        wr = round((wins / max(1, wins + losses)) * 100, 1)
                        if is_win:
                            send_telegram(f"🎯 <b>TIMER TRADE WON!</b>\nAsset: {clean_name} ({t_dir})\nEntry: {entry} ➔ Close: {price}\n💰 <b>₹10 Bet Payout: +₹8.50 (Total ₹18.50)</b>\n📊 Accuracy: {wr}% ({wins}W/{losses}L)")
                        else:
                            send_telegram(f"🛡️ <b>TIMER TRADE CLOSED</b>\nAsset: {clean_name} ({t_dir})\nEntry: {entry} ➔ Close: {price}\n📊 Accuracy: {wr}% ({wins}W/{losses}L)")
        else:
            if direction in ["UP", "DOWN"]:
                exp_ts = now_ts + 180 # 3-Minute High-Accuracy Timer on 1m chart
                exp_str = (get_ist_now() + timedelta(minutes=3)).strftime("%I:%M %p")
                state["timer_trades"][asset] = {
                    "dir": direction,
                    "entry": price,
                    "started_at": now_ts,
                    "expires_at": exp_ts,
                    "exp_str": exp_str,
                    "conf": conf
                }
                if notify:
                    icon = "🟢 <b>TIMER SIGNAL: UP (BUY)</b>" if direction == "UP" else "🔴 <b>TIMER SIGNAL: DOWN (SELL)</b>"
                    send_telegram(f"⏱️ {icon}\nAsset: {clean_name}\nEntry Line: {price}\n⏰ Expiry: {exp_str} (3 Mins)\n💵 ₹10 Bet Profit: <b>+₹8.50 (Total ₹18.50)</b>\n🔥 Sniper Score: {conf}%")

        # =========================================================
        # 2. DYNAMIC MULTIPLIER LIFECYCLE (2x to 10x + Trailing Lock)
        # =========================================================
        m_trade = state["mult_trades"].get(asset)
        if m_trade is not None:
            m_dir = m_trade["dir"]
            entry = float(m_trade["entry"])
            target = float(m_trade["target"])
            autocut = float(m_trade["autocut"])
            unit_risk = max(float(m_trade.get("sl_dist", sl_dist)), 0.00001)
            pot_x = float(m_trade.get("potential_x", 3.0))
            max_x_reached = float(m_trade.get("max_x_reached", 0.0))
            
            # How many X has the line currently moved in our favor?
            move = (price - entry) if m_dir == "UP" else (entry - price)
            current_x = round(move / unit_risk, 2)
            
            if current_x > max_x_reached:
                max_x_reached = current_x
                m_trade["max_x_reached"] = max_x_reached
                
            # 🔒 TRAILING PROFIT LOCK: Once trade reaches +1.0x (100% profit), lock Auto-Cut in Profit!
            if max_x_reached >= 2.0 and not m_trade.get("locked_15x"):
                m_trade["autocut"] = round(entry + (unit_risk * 1.2) if m_dir == "UP" else entry - (unit_risk * 1.2), decimals)
                m_trade["locked_15x"] = True
                m_trade["locked_1x"] = True
            elif max_x_reached >= 1.0 and not m_trade.get("locked_1x"):
                m_trade["autocut"] = round(entry + (unit_risk * 0.5) if m_dir == "UP" else entry - (unit_risk * 0.5), decimals)
                m_trade["locked_1x"] = True
                if notify:
                    send_telegram(f"🔒 <b>PROFIT LOCKED (ZERO LOSS)!</b>\nAsset: {clean_name} crossed +1.0x! Auto-Cut moved into guaranteed profit zone ({m_trade['autocut']}).")

            autocut = float(m_trade["autocut"])
            
            # Check Full Target Hit
            if (m_dir == "UP" and price >= target) or (m_dir == "DOWN" and price <= target):
                win_rs = round(10.0 * pot_x, 2)
                record_history(state, asset, "Multiplier", m_dir, entry, price, True, win_rs, f"({pot_x}x Hit!)")
                state["mult_trades"][asset] = None
                if notify:
                    send_telegram(f"🚀 <b>{pot_x}x MULTIPLIER JACKPOT HIT!</b>\nAsset: {clean_name} ({m_dir})\nEntry: {entry} ➔ Hit: {price}\n💰 <b>₹10 Bet Profit: +₹{win_rs} (Total ₹{round(10+win_rs, 2)})</b>")
            # Check Auto-Cut / Trailing Stop Hit
            elif (m_dir == "UP" and price <= autocut) or (m_dir == "DOWN" and price >= autocut):
                if m_trade.get("locked_1x"):
                    # Closed in Trailing Profit -> Counts as a WIN!
                    locked_x = 1.2 if m_trade.get("locked_15x") else 0.5
                    win_rs = round(10.0 * locked_x, 2)
                    record_history(state, asset, "Multiplier", m_dir, entry, price, True, win_rs, f"(+{locked_x}x Locked)")
                    state["mult_trades"][asset] = None
                    if notify:
                        send_telegram(f"✅ <b>TRAILING PROFIT BOOKED!</b>\nAsset: {clean_name}\nBooked at: {price} (+{locked_x}x Profit = +₹{win_rs} on ₹10 Bet)!")
                else:
                    record_history(state, asset, "Multiplier", m_dir, entry, price, False, -10.0, "(Auto-Cut)")
                    state["mult_trades"][asset] = None
                    if notify:
                        send_telegram(f"🛑 <b>AUTO-CUT TRIGGERED</b>\nAsset: {clean_name}\nExited at: {price}. Max loss strictly capped at ₹10.")
        else:
            if direction in ["UP", "DOWN"]:
                state["mult_trades"][asset] = {
                    "dir": direction,
                    "entry": price,
                    "target": target_p,
                    "autocut": autocut_p,
                    "sl_dist": sl_dist,
                    "mult": broker_mult,
                    "potential_x": potential_x,
                    "milestones": milestones,
                    "max_x_reached": 0.0,
                    "locked_1x": False,
                    "locked_15x": False,
                    "conf": conf
                }
                if notify:
                    win_rs = round(10.0 * potential_x, 2)
                    icon = "🚀 <b>MULTIPLIER UP (LONG)</b>" if direction == "UP" else "⚠️ <b>MULTIPLIER DOWN (SHORT)</b>"
                    send_telegram(
                        f"{icon}\nAsset: {clean_name} ({broker_mult}x Leverage)\n"
                        f"🔥 <b>Expected Rally: {potential_x}x Your Bet!</b>\n"
                        f"🔵 Entry: {price}\n"
                        f"🎯 {potential_x}x Target: {target_p} (<b>+₹{win_rs} Profit on ₹10</b>)\n"
                        f"🛑 Auto-Cut: {autocut_p} (Max Loss = ₹10)"
                    )

        save_state(state)

def background_engine():
    send_telegram("✅ Quantum Sniper V4 Live: 1-Min Fast Feed, Dynamic 2x-10x Multiplier Predictor & Trailing Profit Lock Active!")
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
        time.sleep(20)

threading.Thread(target=background_engine, daemon=True).start()

@app.route('/')
def home():
    return "Quantum Sniper V4 Server is Awake and Running!"

@app.route('/reset_stats')
def reset_stats():
    with memory_lock:
        state = default_state()
        save_state(state)
    return jsonify({"status": "reset_done"})

@app.route('/get_best_trades')
def get_best_trades():
    mode = request.args.get('mode', 'multiplier')
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
                "mult": 100, "potential_x": 3.0, "live_x": 0.0, "milestones": {"m2x": "--", "m5x": "--", "m10x": "--"},
                "live_pnl_pct": 0, "play_alert": False
            })
            continue
            
        try:
            df = fetch_data(asset)
            sentiment, headline = fetch_news_sentiment(asset)
            process_asset_lifecycle(asset, df, sentiment, notify=True)
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            direction, price, target_p, autocut_p, sl_dist, broker_mult, potential_x, milestones, conf, rsi, decimals = analyze_quantum_setup(df, sentiment)
            
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
            live_x = 0.0
            
            if mode == "timer":
                potential_x = 0.85
                if just_hit:
                    signal = "TIMER WON! 💰🟢"
                    entry_val, target_val, sl_val = "--", "+85% Won", "--"
                    action_text = "Boom! Timer Trade Won! Profit music triggered."
                    live_pnl_pct = 85.0
                    conf = 100
                elif t_trade:
                    t_dir = t_trade["dir"]
                    entry_val = t_trade["entry"]
                    rem_sec = max(0, int(t_trade["expires_at"] - now_ts))
                    mins, secs = divmod(rem_sec, 60)
                    winning_now = (price > entry_val) if t_dir == "UP" else (price < entry_val)
                    status_tag = "WINNING 🟢" if winning_now else "PULLBACK 🟡"
                    
                    signal = f"ACTIVE {t_dir} ({mins}m {secs}s) ⏱️"
                    target_val = f"Above {entry_val}" if t_dir == "UP" else f"Below {entry_val}"
                    sl_val = f"Exp: {t_trade['exp_str']}"
                    action_text = f"Status: {status_tag} | Hold until {t_trade['exp_str']}."
                    live_pnl_pct = 85.0 if winning_now else -100.0
                    conf = t_trade.get("conf", conf)
                else:
                    live_pnl_pct = 0
                    entry_val, target_val, sl_val = price, target_p, autocut_p
                    signal = f"WAIT FOR SNIPER ({conf}%) 🟡"
                    action_text = "Scanning 1m pullback for 85%+ guaranteed entry."
                timeframe = "⏱️ 3-Min Fast Timer (85% Return)"
            else:
                # 🚀 MULTIPLIER MODE (Dynamic 2x to 10x)
                if just_hit:
                    signal = "JACKPOT TARGET HIT! 💰🟢"
                    entry_val, target_val, sl_val = "--", "--", "--"
                    action_text = "Boom! Multiplier Profit Booked! Music triggered."
                    live_pnl_pct = potential_x * 100.0
                    live_x = potential_x
                    conf = 100
                elif m_trade:
                    m_dir = m_trade["dir"]
                    entry_val = float(m_trade["entry"])
                    target_val = float(m_trade["target"])
                    sl_val = float(m_trade["autocut"])
                    broker_mult = m_trade.get("mult", broker_mult)
                    potential_x = float(m_trade.get("potential_x", potential_x))
                    milestones = m_trade.get("milestones", milestones)
                    
                    unit_risk = max(float(m_trade.get("sl_dist", sl_dist)), 0.00001)
                    move = (price - entry_val) if m_dir == "UP" else (entry_val - price)
                    live_x = round(max(-1.0, move / unit_risk), 2)
                    live_pnl_pct = round(live_x * 100.0, 1)
                    
                    lock_tag = "🔒 PROFIT LOCKED!" if m_trade.get("locked_1x") else f"Aiming for {potential_x}x"
                    signal = f"ACTIVE {m_dir} (Aim: {potential_x}x) 🚀" if m_dir == "UP" else f"ACTIVE {m_dir} (Aim: {potential_x}x) 🔴"
                    action_text = f"{lock_tag} | Broker Leverage: {broker_mult}x | Auto-Cut: {sl_val}"
                    conf = m_trade.get("conf", conf)
                else:
                    live_pnl_pct = 0
                    live_x = 0.0
                    entry_val, target_val, sl_val = price, target_p, autocut_p
                    dir_hint = "UP 🟢" if float(latest['EMA_9']) >= float(latest['EMA_21']) else "DOWN 🔴"
                    signal = f"SCANNING {potential_x}x WAVE ({dir_hint})"
                    action_text = f"Wave Power: {potential_x}x Bet | Filter Score: {conf}% (Need 85%+)"
                timeframe = f"🚀 {broker_mult}x Leverage | Potential: {potential_x}x Bet"
                
            trades_data.append({
                "asset_id": asset, "stock": clean_name, "tv_symbol": tv_symbol, "price": price, "change": change,
                "signal": signal, "confidence": conf, "entry": entry_val, "target": target_val, "stop_loss": sl_val,
                "timeframe": timeframe, "action_text": action_text, "support": support, "resistance": resistance,
                "news_sentiment": sentiment, "news_headline": headline, "mult": broker_mult,
                "potential_x": potential_x, "live_x": live_x, "milestones": milestones,
                "live_pnl_pct": live_pnl_pct, "play_alert": play_alert
            })
        except Exception as e:
            trades_data.append({
                "asset_id": asset, "stock": clean_name, "tv_symbol": tv_symbol, "price": "Syncing", "change": 0,
                "signal": "LOADING 1m FEED ⏳", "confidence": 0, "entry": "--", "target": "--", "stop_loss": "--",
                "timeframe": "Please wait", "action_text": "Connecting to 1-minute live stream...",
                "support": "--", "resistance": "--", "news_sentiment": "Neutral ⚪", "news_headline": "--",
                "mult": 100, "potential_x": 3.0, "live_x": 0.0, "milestones": {"m2x": "--", "m5x": "--", "m10x": "--"},
                "live_pnl_pct": 0, "play_alert": False
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
