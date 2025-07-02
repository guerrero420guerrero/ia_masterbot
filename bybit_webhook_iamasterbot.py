from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP
import requests
import json
import time

app = Flask(__name__)

API_KEY = "Cy4T1Xz59g1LsgYbhH"
API_SECRET = "8F7rEZNCDSB6qteCyelf5eyxaCgRCUxeGcvQ"
DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1381385638409932980/QEdqH-_1z1LsIHzU-jlAdTRwiCxbSO6qgIjcHAWtW_lJycTT4UMe0LjXjpwZQzt_cEeB"

bybit = HTTP(
    testnet=False,
    api_key=API_KEY,
    api_secret=API_SECRET
)

PORCENTAJES = {
    "TP1": 0.75,
    "TP2": 0.15,
    "TP3": 0.10,
    "CERRAR": 1.0,
    "SL": 1.0,
    "SL_ENTRADA": 1.0,
    "SL_TP1": 1.0,
    "SL_FINAL": 1.0,
}

PORCENTAJE_PREENTRADA = 0.5
PORCENTAJE_ENTRADA_LIMIT = 0.5
PENDING_LIMITS = {}

BYBIT_SYMBOL_INFO_CACHE = {}

def get_symbol_info(symbol, category="linear"):
    global BYBIT_SYMBOL_INFO_CACHE
    symbol = symbol.upper().replace('.P', '')

    cache_key = f"{category}_{symbol}"
    if cache_key in BYBIT_SYMBOL_INFO_CACHE and (time.time() - BYBIT_SYMBOL_INFO_CACHE[cache_key]['ts']) < 3600:
        return BYBIT_SYMBOL_INFO_CACHE[cache_key]['min_qty'], BYBIT_SYMBOL_INFO_CACHE[cache_key]['step']

    url = f"https://api.bybit.com/v5/market/instruments-info?category={category}&symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data["retCode"] == 0 and data["result"]["list"]:
            info = data["result"]["list"][0]
            min_qty = float(info["lotSizeFilter"]["minOrderQty"])
            step = float(info["lotSizeFilter"]["qtyStep"])
            BYBIT_SYMBOL_INFO_CACHE[cache_key] = {'min_qty': min_qty, 'step': step, 'ts': time.time()}
            return min_qty, step
        else:
            print(f"❌ Error consultando lotSizeFilter: {data}")
    except Exception as e:
        print(f"❌ Error consultando info de símbolo {symbol}: {e}")

    return 0.01, 0.01

def hay_cualquier_posicion_abierta():
    posiciones = bybit.get_positions(category="linear", settleCoin="USDT")
    for pos in posiciones["result"]["list"]:
        if abs(float(pos["size"])) > 0:
            return True
    return False

def set_leverage_by_symbol(symbol):
    symbol = symbol.upper().replace('.P', '')
    if symbol == "BTCUSDT":
        leverage = 20
    elif symbol == "ETHUSDT":
        leverage = 10
    else:
        leverage = 10
    try:
        bybit.set_leverage(
            category="linear",
            symbol=symbol,
            buyLeverage=leverage,
            sellLeverage=leverage
        )
    except Exception as e:
        print(f"Error setting leverage: {e}")
        send_discord(f"❌ ERROR set_leverage {symbol}: {e}")

def colocar_stop_loss(symbol, side, qty, stop_loss):
    # Ya NO se usa para entradas. Solo para referencia o si quieres una orden condicional manual.
    pass

def colocar_take_profit(symbol, side, qty, tp_price):
    symbol = symbol.upper().replace('.P', '')
    if tp_price > 0:
        positionIdx = 2 if side == "Buy" else 1
        try:
            return bybit.place_order(
                category="linear",
                symbol=symbol,
                side="Sell" if side == "Buy" else "Buy",
                orderType="Market",
                qty=qty,
                takeProfit=tp_price,
                reduceOnly=True,
                positionIdx=positionIdx
            )
        except Exception as e:
            error_msg = f"❌ ERROR al colocar TAKE PROFIT: {e}\nSímbolo: {symbol}, Qty: {qty}, TP: {tp_price}"
            print(error_msg)
            send_discord(error_msg)
            return None
    return None

def get_wallet_qty(symbol, pct):
    symbol = symbol.upper().replace('.P', '')
    wallet = bybit.get_wallet_balance(accountType="UNIFIED")
    saldo_total = float(wallet["result"]["list"][0]["totalEquity"])
    ticker = bybit.get_tickers(category="linear", symbol=symbol)
    precio_actual = float(ticker["result"]["list"][0]["lastPrice"])
    monto = saldo_total * pct

    min_qty, step = get_symbol_info(symbol, category="linear")

    qty = monto / precio_actual
    qty = max(min_qty, (qty // step) * step)
    return qty

def is_within_02_percent(precio, ema13):
    if ema13 == 0:
        return False
    return abs(precio - ema13) / ema13 <= 0.002

def send_discord(msg):
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": msg})
    except Exception as e:
        print(f"Error enviando a Discord: {e}")

def format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=None):
    msg = ""
    if "PREENTRADA LONG" in evento:
        msg = (
            f"🟩 **PREENTRADA LONG**\n"
            f"Moneda: {symbol}\n"
            f"Precio de entrada: {precio}\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
            f"TP1: {tp1} | TP2: {tp2} | TP3: {tp3}\n"
        )
    elif "PREENTRADA SHORT" in evento:
        msg = (
            f"🟥 **PREENTRADA SHORT**\n"
            f"Moneda: {symbol}\n"
            f"Precio de entrada: {precio}\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
            f"TP1: {tp1} | TP2: {tp2} | TP3: {tp3}\n"
        )
    elif "APERTURA LONG" in evento or "CONFIRMACION LONG REAL" in evento:
        msg = (
            f"🟩 **APERTURA LONG**\n"
            f"Moneda: {symbol}\n"
            f"Precio de entrada: {precio}\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
            f"TP1: {tp1} | TP2: {tp2} | TP3: {tp3}\n"
        )
    elif "APERTURA SHORT" in evento or "CONFIRMACION SHORT REAL" in evento:
        msg = (
            f"🟥 **APERTURA SHORT**\n"
            f"Moneda: {symbol}\n"
            f"Precio de entrada: {precio}\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
            f"TP1: {tp1} | TP2: {tp2} | TP3: {tp3}\n"
        )
    elif "TP1" in evento:
        msg = (
            f"🏁 **TP1 ejecutado**\n"
            f"Moneda: {symbol}\n"
            f"TP1: {tp1}\n"
            f"Porcentaje: 75%\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
        )
    elif "TP2" in evento:
        msg = (
            f"🏁 **TP2 ejecutado**\n"
            f"Moneda: {symbol}\n"
            f"TP2: {tp2}\n"
            f"Porcentaje: 15%\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
        )
    elif "TP3" in evento:
        msg = (
            f"🏁 **TP3 ejecutado**\n"
            f"Moneda: {symbol}\n"
            f"TP3: {tp3}\n"
            f"Porcentaje: 10%\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
        )
    elif "SL FINAL" in evento or "SL_TP3" in evento:
        msg = (
            f"🟥 **STOP LOSS FINAL ejecutado**\n"
            f"Moneda: {symbol}\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
        )
    elif "SL ENTRADA" in evento or "SL_ENTRADA" in evento:
        msg = (
            f"🟧 **STOP LOSS EN ENTRADA ejecutado**\n"
            f"Moneda: {symbol}\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
        )
    elif "SL TP1" in evento or "SL_TP1" in evento:
        msg = (
            f"🟧 **STOP LOSS TP1 ejecutado**\n"
            f"Moneda: {symbol}\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
        )
    elif "SL INICIAL" in evento or "SL" in evento:
        msg = (
            f"🟧 **STOP LOSS ejecutado**\n"
            f"Moneda: {symbol}\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
        )
    elif "REENTRADA LONG" in evento:
        msg = (
            f"🔁 **REENTRADA LONG**\n"
            f"Moneda: {symbol}\n"
            f"Precio de entrada: {precio}\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
        )
    elif "REENTRADA SHORT" in evento:
        msg = (
            f"🔁 **REENTRADA SHORT**\n"
            f"Moneda: {symbol}\n"
            f"Precio de entrada: {precio}\n"
            f"Stop Loss: {stop_loss}\n"
            f"EMA13: {ema13}\n"
        )
    elif "CERRAR" in evento or "CANCELA" in evento or "CANCELAR" in evento:
        msg = (
            f"🔴 **CIERRE TOTAL**\n"
            f"Moneda: {symbol}\n"
            f"Precio actual: {precio}\n"
            f"EMA13: {ema13}\n"
        )
    elif "ACTUALIZA SL DINAMICO" in evento:
        msg = (
            f"⚙️ **SL DINÁMICO actualizado**\n"
            f"Moneda: {symbol}\n"
            f"Nuevo SL: {stop_loss}\n"
            f"EMA13: {ema13}\n"
        )
    else:
        msg = (
            f"🔔 **Alerta recibida**: {evento}\n"
            f"Moneda: {symbol}\n"
            f"Precio: {precio}\n"
            f"EMA13: {ema13}\n"
        )
    if extra:
        msg += f"\n{extra}"
    return msg

# Aquí empieza el resto del webhook con la lógica de integración híbrida de TP-limit/market.
# ... (el resto del código va aquí, incluyendo el endpoint Flask y la lógica de órdenes limitadas y mercado para TPs. Si quieres el archivo completo con todo el endpoint, pídelo.)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        print("--- NUEVA PETICIÓN WEBHOOK ---")
        print("Headers:", request.headers)
        print("Data cruda (request.data):", request.data)
        print("Intentando decodificar como JSON...")
        data = request.get_json(force=True, silent=True)
        if not data:
            raw = request.data.decode("utf-8")
            print("Raw recibido (como texto):", raw)
            data = json.loads(raw)
        print("JSON decodificado correctamente:", data)
    except Exception as e:
        print("No se pudo decodificar JSON:", e)
        print("Headers:", request.headers)
        print("Data:", request.data)
        return jsonify({"status": "error", "msg": "No se pudo decodificar JSON"}), 400

    evento = data.get("evento", "")
    symbol = data.get("symbol", "BTCUSDT").upper().replace('.P', '')
    precio = float(data.get("precio", 0))
    porcentaje = float(data.get("porcentaje", 1))
    stop_loss = float(data.get("stop_loss", 0))
    tp1 = float(data.get("tp1", 0))
    tp2 = float(data.get("tp2", 0))
    tp3 = float(data.get("tp3", 0))
    ema13 = float(data.get("ema13", 0))

    # Toma los porcentajes de los TPs desde el payload, si existen
    tp1_pct = float(data.get("tp1_pct", 0.33))
    tp2_pct = float(data.get("tp2_pct", 0.33))
    tp3_pct = float(data.get("tp3_pct", 0.34))

    pos_data = bybit.get_positions(category="linear", symbol=symbol)
    size = float(pos_data["result"]["list"][0]["size"]) if pos_data["result"]["list"] else 0

    wallet = bybit.get_wallet_balance(accountType="UNIFIED")
    saldo_total = float(wallet["result"]["list"][0]["totalEquity"])

    ticker = bybit.get_tickers(category="linear", symbol=symbol)
    precio_actual = float(ticker["result"]["list"][0]["lastPrice"])

    # --- RESTRICCIÓN GLOBAL: SOLO UNA OPERACIÓN TOTAL ---
    if (("APERTURA LONG" in evento or "APERTURA SHORT" in evento or "REENTRADA LONG" in evento or "REENTRADA SHORT" in evento or 
         "CONFIRMACION LONG REAL" in evento or "CONFIRMACION SHORT REAL" in evento)
        and hay_cualquier_posicion_abierta()):
        msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra="⛔ Ya existe una operación abierta en otro par. No se abre nueva posición.")
        send_discord(msg)
        return jsonify({"status": "Ya existe una operación abierta en otro par. No se abre nueva posición."}), 200

    # === ENTRADAS: SL DIRECTO EN LA ORDEN ===
    if "PREENTRADA LONG" in evento and size == 0:
        if not is_within_02_percent(precio_actual, ema13):
            msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra="⛔ Precio fuera de rango para preentrada LONG (no está dentro del 0.2% de la EMA13).")
            send_discord(msg)
            return jsonify({"status": "Precio fuera de rango para preentrada (no está dentro del 0.2% de la EMA13)."}), 200
        set_leverage_by_symbol(symbol)
        qty = get_wallet_qty(symbol, PORCENTAJE_PREENTRADA)
        try:
            order = bybit.place_order(
                category="linear",
                symbol=symbol,
                side="Buy",
                orderType="Market",
                qty=qty,
                stopLoss=stop_loss,
                reduceOnly=False,
                positionIdx=1
            )
        except Exception as e:
            error_msg = f"❌ ERROR al colocar orden: {e}\nSímbolo: {symbol}, Qty: {qty}"
            print(error_msg)
            send_discord(error_msg)
            return jsonify({"status": "error", "msg": str(e), "qty": qty, "symbol": symbol}), 400
        msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty: {qty}, SL: {stop_loss}")
        send_discord(msg)
        return jsonify({"status": f"Preentrada LONG abierta qty={qty}, SL={stop_loss}", "order": order}), 200

    if "PREENTRADA SHORT" in evento and size == 0:
        if not is_within_02_percent(precio_actual, ema13):
            msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra="⛔ Precio fuera de rango para preentrada SHORT (no está dentro del 0.2% de la EMA13).")
            send_discord(msg)
            return jsonify({"status": "Precio fuera de rango para preentrada (no está dentro del 0.2% de la EMA13)."}), 200
        set_leverage_by_symbol(symbol)
        qty = get_wallet_qty(symbol, PORCENTAJE_PREENTRADA)
        try:
            order = bybit.place_order(
                category="linear",
                symbol=symbol,
                side="Sell",
                orderType="Market",
                qty=qty,
                stopLoss=stop_loss,
                reduceOnly=False,
                positionIdx=2
            )
        except Exception as e:
            error_msg = f"❌ ERROR al colocar orden: {e}\nSímbolo: {symbol}, Qty: {qty}"
            print(error_msg)
            send_discord(error_msg)
            return jsonify({"status": "error", "msg": str(e), "qty": qty, "symbol": symbol}), 400
        msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty: {qty}, SL: {stop_loss}")
        send_discord(msg)
        return jsonify({"status": f"Preentrada SHORT abierta qty={qty}, SL={stop_loss}", "order": order}), 200

    # === ENTRADA REAL: COLOCAR LIMITADAS TP1, TP2, TP3 ===
    if "CONFIRMACION LONG REAL" in evento and size == 0:
        if not is_within_02_percent(precio_actual, ema13):
            msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra="⛔ Precio fuera de rango para CONFIRMACION LONG REAL (no está dentro del 0.2% de la EMA13).")
            send_discord(msg)
            return jsonify({"status": "Precio fuera de rango para CONFIRMACION LONG REAL (no está dentro del 0.2% de la EMA13)."}), 200
        set_leverage_by_symbol(symbol)
        qty = get_wallet_qty(symbol, PORCENTAJE_ENTRADA_LIMIT)
        try:
            order = bybit.place_order(
                category="linear",
                symbol=symbol,
                side="Buy",
                orderType="Market",
                qty=qty,
                stopLoss=stop_loss,
                reduceOnly=False,
                positionIdx=1
            )
        except Exception as e:
            error_msg = f"❌ ERROR al colocar orden: {e}\nSímbolo: {symbol}, Qty: {qty}"
            print(error_msg)
            send_discord(error_msg)
            return jsonify({"status": "error", "msg": str(e), "qty": qty, "symbol": symbol}), 400

        # COLOCAR LIMITS TP1/TP2/TP3
        min_qty, step = get_symbol_info(symbol, category="linear")
        qty_tp1 = max(min_qty, (qty * tp1_pct // step) * step)
        qty_tp2 = max(min_qty, (qty * tp2_pct // step) * step)
        qty_tp3 = max(min_qty, (qty * tp3_pct // step) * step)
        tp1_order = bybit.place_order(
            category="linear", symbol=symbol, side="Sell",
            orderType="Limit", qty=qty_tp1, price=tp1,
            reduceOnly=True, positionIdx=1
        )
        tp2_order = bybit.place_order(
            category="linear", symbol=symbol, side="Sell",
            orderType="Limit", qty=qty_tp2, price=tp2,
            reduceOnly=True, positionIdx=1
        )
        tp3_order = bybit.place_order(
            category="linear", symbol=symbol, side="Sell",
            orderType="Limit", qty=qty_tp3, price=tp3,
            reduceOnly=True, positionIdx=1
        )
        PENDING_LIMITS[symbol] = {
            "tp1": tp1_order["result"]["orderId"],
            "tp2": tp2_order["result"]["orderId"],
            "tp3": tp3_order["result"]["orderId"]
        }

        msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty: {qty}, SL: {stop_loss}, TP1 limit: {qty_tp1}, TP2 limit: {qty_tp2}, TP3 limit: {qty_tp3}")
        send_discord(msg)
        return jsonify({"status": f"CONFIRMACION LONG REAL abierta qty={qty}, SL={stop_loss}, TP1/2/3 limits colocadas", "order": order}), 200


        # COLOCAR LIMITS TP1/TP2/TP3 SHORT
        min_qty, step = get_symbol_info(symbol, category="linear")
        qty_tp1 = max(min_qty, (qty * tp1_pct // step) * step)
        qty_tp2 = max(min_qty, (qty * tp2_pct // step) * step)
        qty_tp3 = max(min_qty, (qty * tp3_pct // step) * step)
        tp1_order = bybit.place_order(
            category="linear", symbol=symbol, side="Buy",
            orderType="Limit", qty=qty_tp1, price=tp1,
            reduceOnly=True, positionIdx=2
        )
        tp2_order = bybit.place_order(
            category="linear", symbol=symbol, side="Buy",
            orderType="Limit", qty=qty_tp2, price=tp2,
            reduceOnly=True, positionIdx=2
        )
        tp3_order = bybit.place_order(
            category="linear", symbol=symbol, side="Buy",
            orderType="Limit", qty=qty_tp3, price=tp3,
            reduceOnly=True, positionIdx=2
        )
        PENDING_LIMITS[symbol] = {
            "tp1": tp1_order["result"]["orderId"],
            "tp2": tp2_order["result"]["orderId"],
            "tp3": tp3_order["result"]["orderId"]
        }

        msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty: {qty}, SL: {stop_loss}, TP1 limit: {qty_tp1}, TP2 limit: {qty_tp2}, TP3 limit: {qty_tp3}")
        send_discord(msg)
        return jsonify({"status": f"CONFIRMACION SHORT REAL abierta qty={qty}, SL={stop_loss}, TP1/2/3 limits colocadas", "order": order}), 200
    
    
    if "CONFIRMACION SHORT REAL" in evento and size == 0:
        if not is_within_02_percent(precio_actual, ema13):
            msg = format_discord_msg(
                evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
                extra="⛔ Precio fuera de rango para CONFIRMACION SHORT REAL (no está dentro del 0.2% de la EMA13)."
            )
            send_discord(msg)
            return jsonify({"status": "Precio fuera de rango para CONFIRMACION SHORT REAL (no está dentro del 0.2% de la EMA13)."}), 200

        set_leverage_by_symbol(symbol)
        qty = get_wallet_qty(symbol, PORCENTAJE_ENTRADA_LIMIT)
        try:
            order = bybit.place_order(
                category="linear",
                symbol=symbol,
                side="Sell",
                orderType="Market",
                qty=qty,
                stopLoss=stop_loss,
                reduceOnly=False,
                positionIdx=2
            )
        except Exception as e:
            error_msg = f"❌ ERROR al colocar orden: {e}\nSímbolo: {symbol}, Qty: {qty}"
            print(error_msg)
            send_discord(error_msg)
            return jsonify({"status": "error", "msg": str(e), "qty": qty, "symbol": symbol}), 400

        # COLOCAR LIMITS TP1/TP2/TP3 SHORT
        min_qty, step = get_symbol_info(symbol, category="linear")
        qty_tp1 = max(min_qty, (qty * tp1_pct // step) * step)
        qty_tp2 = max(min_qty, (qty * tp2_pct // step) * step)
        qty_tp3 = max(min_qty, (qty * tp3_pct // step) * step)
        tp1_order = bybit.place_order(
            category="linear", symbol=symbol, side="Buy",
            orderType="Limit", qty=qty_tp1, price=tp1,
            reduceOnly=True, positionIdx=2
        )
        tp2_order = bybit.place_order(
            category="linear", symbol=symbol, side="Buy",
            orderType="Limit", qty=qty_tp2, price=tp2,
            reduceOnly=True, positionIdx=2
        )
        tp3_order = bybit.place_order(
            category="linear", symbol=symbol, side="Buy",
            orderType="Limit", qty=qty_tp3, price=tp3,
            reduceOnly=True, positionIdx=2
        )
        PENDING_LIMITS[symbol] = {
            "tp1": tp1_order["result"]["orderId"],
            "tp2": tp2_order["result"]["orderId"],
            "tp3": tp3_order["result"]["orderId"]
        }

        msg = format_discord_msg(
            evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
            extra=f"Qty: {qty}, SL: {stop_loss}, TP1 limit: {qty_tp1}, TP2 limit: {qty_tp2}, TP3 limit: {qty_tp3}"
        )
        send_discord(msg)
        return jsonify({
            "status": f"CONFIRMACION SHORT REAL abierta qty={qty}, SL={stop_loss}, TP1/2/3 limits colocadas",
            "order": order
        }), 200

    # COLOCAR LIMITS TP1/TP2/TP3 SHORT
    tp1_pct = float(data.get("tp1_pct", 0.33))
    tp2_pct = float(data.get("tp2_pct", 0.33))
    tp3_pct = float(data.get("tp3_pct", 0.34))
    min_qty, step = get_symbol_info(symbol, category="linear")
    qty_tp1 = max(min_qty, (qty * tp1_pct // step) * step)
    qty_tp2 = max(min_qty, (qty * tp2_pct // step) * step)
    qty_tp3 = max(min_qty, (qty * tp3_pct // step) * step)
    tp1_order = bybit.place_order(
        category="linear", symbol=symbol, side="Buy",
        orderType="Limit", qty=qty_tp1, price=tp1,
        reduceOnly=True, positionIdx=2
    )
    tp2_order = bybit.place_order(
        category="linear", symbol=symbol, side="Buy",
        orderType="Limit", qty=qty_tp2, price=tp2,
        reduceOnly=True, positionIdx=2
    )
    tp3_order = bybit.place_order(
        category="linear", symbol=symbol, side="Buy",
        orderType="Limit", qty=qty_tp3, price=tp3,
        reduceOnly=True, positionIdx=2
    )
    PENDING_LIMITS[symbol] = {
        "tp1": tp1_order["result"]["orderId"],
        "tp2": tp2_order["result"]["orderId"],
        "tp3": tp3_order["result"]["orderId"]
    }

    msg = format_discord_msg(
        evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
        extra=f"Qty: {qty}, SL: {stop_loss}, TP1 limit: {qty_tp1}, TP2 limit: {qty_tp2}, TP3 limit: {qty_tp3}"
    )
    send_discord(msg)
    return jsonify({
        "status": f"CONFIRMACION SHORT REAL abierta qty={qty}, SL={stop_loss}, TP1/2/3 limits colocadas",
        "order": order
    }), 200

    # === SL DINÁMICO: Actualizar SL de posición abierta ===
    if "ACTUALIZA SL DINAMICO" in evento and stop_loss:
        if size != 0:
            positionIdx = 1 if size > 0 else 2
            try:
                sl_result = bybit.set_trading_stop(
                    category="linear",
                    symbol=symbol,
                    stopLoss=stop_loss,
                    positionIdx=positionIdx
                )
            except Exception as e:
                error_msg = f"❌ ERROR SL DINÁMICO: {e}\nSímbolo: {symbol}, Qty: {abs(size)}, SL: {stop_loss}"
                print(error_msg)
                send_discord(error_msg)
                return jsonify({"status": "error", "msg": str(e), "qty": abs(size), "symbol": symbol}), 400

            msg = format_discord_msg(
                evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
                extra=f"SL dinámico actualizado a {stop_loss} qty={abs(size)}"
            )
            send_discord(msg)
            return jsonify({"status": f"SL dinámico actualizado a {stop_loss}", "sl_result": sl_result}), 200
        else:
            msg = format_discord_msg(
                evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
                extra="⚠️ No hay posición abierta para actualizar SL dinámico"
            )
            send_discord(msg)
            return jsonify({"status": "No hay posición abierta para actualizar SL dinámico"}), 200
        
    # === TP1: Ejecutar 75%, cancelar limit si no se ha llenado ===
    if "TP1" in evento and size != 0:
        orderId = PENDING_LIMITS.get(symbol, {}).get("tp1")
        if orderId:
            # Consultar el estado de la orden limitada
            order_info = bybit.get_order(category="linear", symbol=symbol, orderId=orderId)
            if order_info["result"]["orderStatus"] == "Filled":
                # Ya está ejecutada la limitada, no hacer nada
                return jsonify({"status": "TP1 limit ya ejecutada"}), 200
            else:
                # Cancelar la limitada antes de ejecutar market
                try:
                    bybit.cancel_order(category="linear", symbol=symbol, orderId=orderId)
                except Exception as e:
                    print(f"Error cancelando limit: {e}")
            # Elimina el orderId de TP1
            if symbol in PENDING_LIMITS:
                PENDING_LIMITS[symbol].pop("tp1", None)
        qty_tp1 = abs(size) * PORCENTAJES["TP1"]
        min_qty, step = get_symbol_info(symbol, category="linear")
        qty_tp1 = max(min_qty, (qty_tp1 // step) * step)
        positionIdx = 1 if size > 0 else 2
        try:
            order = bybit.place_order(
                category="linear",
                symbol=symbol,
                side="Sell" if size > 0 else "Buy",
                orderType="Market",
                qty=qty_tp1,
                reduceOnly=True,
                positionIdx=positionIdx
            )
        except Exception as e:
            error_msg = f"❌ ERROR TP1: {e}\nSímbolo: {symbol}, Qty: {qty_tp1}"
            print(error_msg)
            send_discord(error_msg)
            return jsonify({"status": "error", "msg": str(e), "qty": qty_tp1, "symbol": symbol}), 400
        msg = format_discord_msg(
            evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
            extra=f"Qty TP1: {qty_tp1} y limit cancelada"
        )
        send_discord(msg)
        return jsonify({"status": "TP1 ejecutado y limit cancelada", "order": order}), 200

# === TP2: lo mismo, pero para TP2 limit ===
if "TP2" in evento and size != 0:
    orderId = PENDING_LIMITS.get(symbol, {}).get("tp2")
    if orderId:
        order_info = bybit.get_order(category="linear", symbol=symbol, orderId=orderId)
        if order_info["result"]["orderStatus"] == "Filled":
            return jsonify({"status": "TP2 limit ya ejecutada"}), 200
        else:
            try:
                bybit.cancel_order(category="linear", symbol=symbol, orderId=orderId)
            except Exception as e:
                print(f"Error cancelando limit: {e}")
        if symbol in PENDING_LIMITS:
            PENDING_LIMITS[symbol].pop("tp2", None)
    qty_tp2 = abs(size) * PORCENTAJES["TP2"]
    min_qty, step = get_symbol_info(symbol, category="linear")
    qty_tp2 = max(min_qty, (qty_tp2 // step) * step)
    positionIdx = 1 if size > 0 else 2
    try:
        order = bybit.place_order(
            category="linear",
            symbol=symbol,
            side="Sell" if size > 0 else "Buy",
            orderType="Market",
            qty=qty_tp2,
            reduceOnly=True,
            positionIdx=positionIdx
        )
    except Exception as e:
        error_msg = f"❌ ERROR TP2: {e}\nSímbolo: {symbol}, Qty: {qty_tp2}"
        print(error_msg)
        send_discord(error_msg)
        return jsonify({"status": "error", "msg": str(e), "qty": qty_tp2, "symbol": symbol}), 400
    msg = format_discord_msg(
        evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
        extra=f"Qty TP2: {qty_tp2}"
    )
    send_discord(msg)
    return jsonify({"status": "TP2 ejecutado", "order": order}), 200

       # === TP3 ===
    if "TP3" in evento and size != 0:
        orderId = PENDING_LIMITS.get(symbol, {}).get("tp3")
        if orderId:
            order_info = bybit.get_order(category="linear", symbol=symbol, orderId=orderId)
            if order_info["result"]["orderStatus"] == "Filled":
                return jsonify({"status": "TP3 limit ya ejecutada"}), 200
            else:
                try:
                    bybit.cancel_order(category="linear", symbol=symbol, orderId=orderId)
                except Exception as e:
                    print(f"Error cancelando limit: {e}")
            if symbol in PENDING_LIMITS:
                PENDING_LIMITS[symbol].pop("tp3", None)
        qty_tp3 = abs(size) * PORCENTAJES["TP3"]
        min_qty, step = get_symbol_info(symbol, category="linear")
        qty_tp3 = max(min_qty, (qty_tp3 // step) * step)
        positionIdx = 1 if size > 0 else 2
        try:
            order = bybit.place_order(
                category="linear",
                symbol=symbol,
                side="Sell" if size > 0 else "Buy",
                orderType="Market",
                qty=qty_tp3,
                reduceOnly=True,
                positionIdx=positionIdx
            )
        except Exception as e:
            error_msg = f"❌ ERROR TP3: {e}\nSímbolo: {symbol}, Qty: {qty_tp3}"
            print(error_msg)
            send_discord(error_msg)
            return jsonify({"status": "error", "msg": str(e), "qty": qty_tp3, "symbol": symbol}), 400
        msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty TP3: {qty_tp3}")
        send_discord(msg)
        return jsonify({"status": "TP3 ejecutado", "order": order}), 200

    # === Cancelación total: cierre y cancelar limit ===
    if ("CANCELAR" in evento or "CERRAR" in evento or "CANCELA" in evento or "CERRAR LONG" in evento or "CERRAR SHORT" in evento):
        try:
            if size > 0:
                bybit.place_order(
                    category="linear",
                    symbol=symbol,
                    side="Sell",
                    orderType="Market",
                    qty=size,
                    reduceOnly=True,
                    positionIdx=1  # Cierre LONG
                )
            elif size < 0:
                bybit.place_order(
                    category="linear",
                    symbol=symbol,
                    side="Buy",
                    orderType="Market",
                    qty=abs(size),
                    reduceOnly=True,
                    positionIdx=2  # Cierre SHORT
                )
        except Exception as e:
            error_msg = f"❌ ERROR al cerrar posición: {e}\nSímbolo: {symbol}, Qty: {size}"
            print(error_msg)
            send_discord(error_msg)
            return jsonify({"status": "error", "msg": str(e), "qty": size, "symbol": symbol}), 400
        if symbol in PENDING_LIMITS:
            # Cancela todas las órdenes limitadas de TP pendientes
            for tp_key in ["tp1", "tp2", "tp3"]:
                orderId = PENDING_LIMITS[symbol].get(tp_key)
                if orderId:
                    try:
                        bybit.cancel_order(category="linear", symbol=symbol, orderId=orderId)
                    except Exception as e:
                        print(f"Error cancelando limit {tp_key}: {e}")
            PENDING_LIMITS.pop(symbol)
        msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra="Cierre total y cancelación de limit")
        send_discord(msg)
        return jsonify({"status": "Cierre total y cancelación de limit"}), 200

    # === Reentrada tras SL o tras TP3 ===
    if "REENTRADA LONG" in evento and size == 0:
        set_leverage_by_symbol(symbol)
        qty = get_wallet_qty(symbol, PORCENTAJE_PREENTRADA)
        try:
            order = bybit.place_order(
                category="linear",
                symbol=symbol,
                side="Buy",
                orderType="Market",
                qty=qty,
                stopLoss=stop_loss,
                reduceOnly=False,
                positionIdx=1  # LONG
            )
        except Exception as e:
            error_msg = f"❌ ERROR REENTRADA LONG: {e}\nSímbolo: {symbol}, Qty: {qty}"
            print(error_msg)
            send_discord(error_msg)
            return jsonify({"status": "error", "msg": str(e), "qty": qty, "symbol": symbol}), 400
        msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty: {qty}, SL: {stop_loss}")
        send_discord(msg)
        return jsonify({
            "status": "reentrada long abierta",
            "order": order
        }), 200

    if "REENTRADA SHORT" in evento and size == 0:
        set_leverage_by_symbol(symbol)
        qty = get_wallet_qty(symbol, PORCENTAJE_PREENTRADA)
        try:
            order = bybit.place_order(
                category="linear",
                symbol=symbol,
                side="Sell",
                orderType="Market",
                qty=qty,
                stopLoss=stop_loss,
                reduceOnly=False,
                positionIdx=2  # SHORT
            )
        except Exception as e:
            error_msg = f"❌ ERROR REENTRADA SHORT: {e}\nSímbolo: {symbol}, Qty: {qty}"
            print(error_msg)
            send_discord(error_msg)
            return jsonify({"status": "error", "msg": str(e), "qty": qty, "symbol": symbol}), 400
        msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty: {qty}, SL: {stop_loss}")
        send_discord(msg)
        return jsonify({
            "status": "reentrada short abierta",
            "order": order
        }), 200

    # Bloque final literal con manejo de error detallado:
    try:
        msg = format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13)
        send_discord(msg)
    except Exception as e:
        error_msg = f"❌ ERROR al enviar mensaje a Discord o formatear mensaje: {e}\nEvento: {evento}, Símbolo: {symbol}, Precio: {precio}"
        print(error_msg)
        try:
            send_discord(error_msg)
        except Exception as e2:
            print(f"Error adicional al intentar enviar mensaje de error a Discord: {e2}")
        return jsonify({"status": "error", "msg": str(e), "evento": evento, "symbol": symbol}), 400

    return jsonify({"status": "sin acción"}), 200

if __name__ == "__main__":
    app.run(port=5000)