print("Inicia el script")
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP
import requests
import json
import time

app = Flask(__name__)

# --- CONFIGURA AQUÍ LAS CUENTAS ---
ACCOUNT_CONFIGS = {
    "cuenta1": {
        "API_KEY": "Cy4T1Xz59g1LsgYbhH",
        "API_SECRET": "8F7rEZNCDSB6qteCyelf5eyxaCgRCUxeGcvQ",
    },
    "cuenta2": {
        "API_KEY": "5QT4MZpgPP9vS28Nb0",
        "API_SECRET": "Qfyuf4eNWlAgvRu3glSo69nJE4d1uGJjk1jK",
    },
    # Puedes agregar más cuentas así:
    # "cuenta3": {
    #     "API_KEY": "OTRA_API_KEY",
    #     "API_SECRET": "OTRO_SECRET",
    # },
}

BYBIT_CLIENTS = {
    name: HTTP(testnet=False, api_key=cfg["API_KEY"], api_secret=cfg["API_SECRET"])
    for name, cfg in ACCOUNT_CONFIGS.items()
}

DISCORD_WEBHOOK = "https://discordapp.com/api/webhooks/1381385638409932980/QEdqH-_1z1LsIHzU-jlAdTRwiCxbSO6qgIjcHAWtW_lJycTT4UMe0LjXjpwZQzt_cEeB"

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

# PENDING_LIMITS ahora por cuenta
PENDING_LIMITS = {name: {} for name in BYBIT_CLIENTS}

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

def hay_cualquier_posicion_abierta(bybit):
    posiciones = bybit.get_positions(category="linear", settleCoin="USDT")
    for pos in posiciones["result"]["list"]:
        if abs(float(pos["size"])) > 0:
            return True
    return False

def set_leverage_by_symbol(bybit, symbol):
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

def get_wallet_qty(bybit, symbol, pct):
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

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            raw = request.data.decode("utf-8")
            data = json.loads(raw)
    except Exception as e:
        return jsonify({"status": "error", "msg": "No se pudo decodificar JSON"}), 400

    resultados = []
    for cuenta_name, bybit in BYBIT_CLIENTS.items():
        try:
            pending_limits = PENDING_LIMITS[cuenta_name]

            evento = data.get("evento", "")
            symbol = data.get("symbol", "BTCUSDT").upper().replace('.P', '')
            precio = float(data.get("precio", 0))
            porcentaje = float(data.get("porcentaje", 1))
            stop_loss = float(data.get("stop_loss", 0))
            tp1 = float(data.get("tp1", 0))
            tp2 = float(data.get("tp2", 0))
            tp3 = float(data.get("tp3", 0))
            ema13 = float(data.get("ema13", 0))
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
                and hay_cualquier_posicion_abierta(bybit)):
                msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra="⛔ Ya existe una operación abierta en otro par. No se abre nueva posición.")
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": "Ya existe una operación abierta en otro par. No se abre nueva posición."})
                continue

            # === PREENTRADA LONG ===
            if "PREENTRADA LONG" in evento and size == 0:
                if not is_within_02_percent(precio_actual, ema13):
                    msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra="⛔ Precio fuera de rango para preentrada LONG (no está dentro del 0.2% de la EMA13).")
                    send_discord(msg)
                    resultados.append({"cuenta": cuenta_name, "status": "Precio fuera de rango para preentrada (no está dentro del 0.2% de la EMA13)."})
                    continue
                set_leverage_by_symbol(bybit, symbol)
                qty = get_wallet_qty(bybit, symbol, PORCENTAJE_PREENTRADA)
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
                    error_msg = f"[{cuenta_name}] ❌ ERROR al colocar orden: {e}\nSímbolo: {symbol}, Qty: {qty}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": qty, "symbol": symbol})
                    continue
                msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty: {qty}, SL: {stop_loss}")
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": f"Preentrada LONG abierta qty={qty}, SL={stop_loss}", "order": order})
                continue

            # === PREENTRADA SHORT ===
            if "PREENTRADA SHORT" in evento and size == 0:
                if not is_within_02_percent(precio_actual, ema13):
                    msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra="⛔ Precio fuera de rango para preentrada SHORT (no está dentro del 0.2% de la EMA13).")
                    send_discord(msg)
                    resultados.append({"cuenta": cuenta_name, "status": "Precio fuera de rango para preentrada (no está dentro del 0.2% de la EMA13)."})
                    continue
                set_leverage_by_symbol(bybit, symbol)
                qty = get_wallet_qty(bybit, symbol, PORCENTAJE_PREENTRADA)
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
                    error_msg = f"[{cuenta_name}] ❌ ERROR al colocar orden: {e}\nSímbolo: {symbol}, Qty: {qty}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": qty, "symbol": symbol})
                    continue
                msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty: {qty}, SL: {stop_loss}")
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": f"Preentrada SHORT abierta qty={qty}, SL={stop_loss}", "order": order})
                continue

            # === ENTRADA LONG CRUCE VOLUMEN ===
            if "ENTRADA LONG CRUCE VOLUMEN" in evento and size == 0:
                set_leverage_by_symbol(bybit, symbol)
                qty = get_wallet_qty(bybit, symbol, PORCENTAJE_PREENTRADA)
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
                    error_msg = f"[{cuenta_name}] ❌ ERROR al colocar orden LONG CRUCE VOLUMEN: {e}\nSímbolo: {symbol}, Qty: {qty}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": qty, "symbol": symbol})
                    continue
                msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty: {qty}, SL: {stop_loss}")
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": f"ENTRADA LONG CRUCE VOLUMEN abierta qty={qty}, SL={stop_loss}", "order": order})
                continue

            # === ENTRADA SHORT CRUCE VOLUMEN ===
            if "ENTRADA SHORT CRUCE VOLUMEN" in evento and size == 0:
                set_leverage_by_symbol(bybit, symbol)
                qty = get_wallet_qty(bybit, symbol, PORCENTAJE_PREENTRADA)
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
                    error_msg = f"[{cuenta_name}] ❌ ERROR al colocar orden SHORT CRUCE VOLUMEN: {e}\nSímbolo: {symbol}, Qty: {qty}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": qty, "symbol": symbol})
                    continue
                msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty: {qty}, SL: {stop_loss}")
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": f"ENTRADA SHORT CRUCE VOLUMEN abierta qty={qty}, SL={stop_loss}", "order": order})
                continue

                        # === ACTUALIZA SL DINAMICO LONG ===
            if "ACTUALIZA SL DINAMICO LONG" in evento and size != 0:
                positionIdx = 1  # LONG
                try:
                    sl_result = bybit.set_trading_stop(
                        category="linear",
                        symbol=symbol,
                        stopLoss=stop_loss,
                        positionIdx=positionIdx
                    )
                except Exception as e:
                    error_msg = f"[{cuenta_name}] ❌ ERROR SL DINÁMICO LONG: {e}\nSímbolo: {symbol}, Qty: {abs(size)}, SL: {stop_loss}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": abs(size), "symbol": symbol})
                    continue

                msg = f"[{cuenta_name}] " + format_discord_msg(
                    evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
                    extra=f"SL dinámico LONG actualizado a {stop_loss} qty={abs(size)}"
                )
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": f"SL dinámico LONG actualizado a {stop_loss}", "sl_result": sl_result})
                continue

            # === ACTUALIZA SL DINAMICO SHORT ===
            if "ACTUALIZA SL DINAMICO SHORT" in evento and size != 0:
                positionIdx = 2  # SHORT
                try:
                    sl_result = bybit.set_trading_stop(
                        category="linear",
                        symbol=symbol,
                        stopLoss=stop_loss,
                        positionIdx=positionIdx
                    )
                except Exception as e:
                    error_msg = f"[{cuenta_name}] ❌ ERROR SL DINÁMICO SHORT: {e}\nSímbolo: {symbol}, Qty: {abs(size)}, SL: {stop_loss}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": abs(size), "symbol": symbol})
                    continue

                msg = f"[{cuenta_name}] " + format_discord_msg(
                    evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
                    extra=f"SL dinámico SHORT actualizado a {stop_loss} qty={abs(size)}"
                )
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": f"SL dinámico SHORT actualizado a {stop_loss}", "sl_result": sl_result})
                continue

            # === CONFIRMACION LONG REAL ===
            if "CONFIRMACION LONG REAL" in evento and size == 0:
                if not is_within_02_percent(precio_actual, ema13):
                    msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra="⛔ Precio fuera de rango para CONFIRMACION LONG REAL (no está dentro del 0.2% de la EMA13).")
                    send_discord(msg)
                    resultados.append({"cuenta": cuenta_name, "status": "Precio fuera de rango para CONFIRMACION LONG REAL (no está dentro del 0.2% de la EMA13)."})
                    continue
                set_leverage_by_symbol(bybit, symbol)
                qty = get_wallet_qty(bybit, symbol, PORCENTAJE_ENTRADA_LIMIT)
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
                    error_msg = f"[{cuenta_name}] ❌ ERROR al colocar orden: {e}\nSímbolo: {symbol}, Qty: {qty}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": qty, "symbol": symbol})
                    continue

                # COLOCAR LIMITS TP1/TP2/TP3 LONG
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
                pending_limits[symbol] = {
                    "tp1": tp1_order["result"]["orderId"],
                    "tp2": tp2_order["result"]["orderId"],
                    "tp3": tp3_order["result"]["orderId"]
                }

                msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty: {qty}, SL: {stop_loss}, TP1 limit: {qty_tp1}, TP2 limit: {qty_tp2}, TP3 limit: {qty_tp3}")
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": f"CONFIRMACION LONG REAL abierta qty={qty}, SL={stop_loss}, TP1/2/3 limits colocadas", "order": order})
                continue

            # === CONFIRMACION SHORT REAL ===
            if "CONFIRMACION SHORT REAL" in evento and size == 0:
                if not is_within_02_percent(precio_actual, ema13):
                    msg = f"[{cuenta_name}] " + format_discord_msg(
                        evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
                        extra="⛔ Precio fuera de rango para CONFIRMACION SHORT REAL (no está dentro del 0.2% de la EMA13)."
                    )
                    send_discord(msg)
                    resultados.append({"cuenta": cuenta_name, "status": "Precio fuera de rango para CONFIRMACION SHORT REAL (no está dentro del 0.2% de la EMA13)."})
                    continue

                set_leverage_by_symbol(bybit, symbol)
                qty = get_wallet_qty(bybit, symbol, PORCENTAJE_ENTRADA_LIMIT)
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
                    error_msg = f"[{cuenta_name}] ❌ ERROR al colocar orden: {e}\nSímbolo: {symbol}, Qty: {qty}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": qty, "symbol": symbol})
                    continue

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
                pending_limits[symbol] = {
                    "tp1": tp1_order["result"]["orderId"],
                    "tp2": tp2_order["result"]["orderId"],
                    "tp3": tp3_order["result"]["orderId"]
                }

                msg = f"[{cuenta_name}] " + format_discord_msg(
                    evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
                    extra=f"Qty: {qty}, SL: {stop_loss}, TP1 limit: {qty_tp1}, TP2 limit: {qty_tp2}, TP3 limit: {qty_tp3}"
                )
                send_discord(msg)
                resultados.append({
                    "cuenta": cuenta_name,
                    "status": f"CONFIRMACION SHORT REAL abierta qty={qty}, SL={stop_loss}, TP1/2/3 limits colocadas",
                    "order": order
                })
                continue

                        # === TP1: Ejecutar 75%, cancelar limit si no se ha llenado ===
            if "TP1" in evento and size != 0:
                orderId = pending_limits.get(symbol, {}).get("tp1")
                if orderId:
                    order_info = bybit.get_order(category="linear", symbol=symbol, orderId=orderId)
                    if order_info["result"]["orderStatus"] == "Filled":
                        resultados.append({"cuenta": cuenta_name, "status": "TP1 limit ya ejecutada"})
                        continue
                    else:
                        try:
                            bybit.cancel_order(category="linear", symbol=symbol, orderId=orderId)
                        except Exception as e:
                            print(f"[{cuenta_name}] Error cancelando limit: {e}")
                    if symbol in pending_limits:
                        pending_limits[symbol].pop("tp1", None)
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
                    error_msg = f"[{cuenta_name}] ❌ ERROR TP1: {e}\nSímbolo: {symbol}, Qty: {qty_tp1}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": qty_tp1, "symbol": symbol})
                    continue
                msg = f"[{cuenta_name}] " + format_discord_msg(
                    evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
                    extra=f"Qty TP1: {qty_tp1} y limit cancelada"
                )
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": "TP1 ejecutado y limit cancelada", "order": order})
                continue

            # === TP2: Ejecutar 15%, cancelar limit si no se ha llenado ===
            if "TP2" in evento and size != 0:
                orderId = pending_limits.get(symbol, {}).get("tp2")
                if orderId:
                    order_info = bybit.get_order(category="linear", symbol=symbol, orderId=orderId)
                    if order_info["result"]["orderStatus"] == "Filled":
                        resultados.append({"cuenta": cuenta_name, "status": "TP2 limit ya ejecutada"})
                        continue
                    else:
                        try:
                            bybit.cancel_order(category="linear", symbol=symbol, orderId=orderId)
                        except Exception as e:
                            print(f"[{cuenta_name}] Error cancelando limit: {e}")
                    if symbol in pending_limits:
                        pending_limits[symbol].pop("tp2", None)
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
                    error_msg = f"[{cuenta_name}] ❌ ERROR TP2: {e}\nSímbolo: {symbol}, Qty: {qty_tp2}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": qty_tp2, "symbol": symbol})
                    continue
                msg = f"[{cuenta_name}] " + format_discord_msg(
                    evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13,
                    extra=f"Qty TP2: {qty_tp2}"
                )
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": "TP2 ejecutado", "order": order})
                continue

            # === TP3: Ejecutar 10%, cancelar limit si no se ha llenado ===
            if "TP3" in evento and size != 0:
                orderId = pending_limits.get(symbol, {}).get("tp3")
                if orderId:
                    order_info = bybit.get_order(category="linear", symbol=symbol, orderId=orderId)
                    if order_info["result"]["orderStatus"] == "Filled":
                        resultados.append({"cuenta": cuenta_name, "status": "TP3 limit ya ejecutada"})
                        continue
                    else:
                        try:
                            bybit.cancel_order(category="linear", symbol=symbol, orderId=orderId)
                        except Exception as e:
                            print(f"[{cuenta_name}] Error cancelando limit: {e}")
                    if symbol in pending_limits:
                        pending_limits[symbol].pop("tp3", None)
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
                    error_msg = f"[{cuenta_name}] ❌ ERROR TP3: {e}\nSímbolo: {symbol}, Qty: {qty_tp3}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": qty_tp3, "symbol": symbol})
                    continue
                msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra=f"Qty TP3: {qty_tp3}")
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": "TP3 ejecutado", "order": order})
                continue

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
                    error_msg = f"[{cuenta_name}] ❌ ERROR al cerrar posición: {e}\nSímbolo: {symbol}, Qty: {size}"
                    print(error_msg)
                    send_discord(error_msg)
                    resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "qty": size, "symbol": symbol})
                    continue
                if symbol in pending_limits:
                    for tp_key in ["tp1", "tp2", "tp3"]:
                        orderId = pending_limits[symbol].get(tp_key)
                        if orderId:
                            try:
                                bybit.cancel_order(category="linear", symbol=symbol, orderId=orderId)
                            except Exception as e:
                                print(f"[{cuenta_name}] Error cancelando limit {tp_key}: {e}")
                    pending_limits.pop(symbol)
                msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13, extra="Cierre total y cancelación de limit")
                send_discord(msg)
                resultados.append({"cuenta": cuenta_name, "status": "Cierre total y cancelación de limit"})
                continue

            # Mensaje genérico final si no se ejecuta ninguna acción específica
            try:
                msg = f"[{cuenta_name}] " + format_discord_msg(evento, symbol, precio, porcentaje, stop_loss, tp1, tp2, tp3, ema13)
                send_discord(msg)
            except Exception as e:
                error_msg = f"[{cuenta_name}] ❌ ERROR al enviar mensaje a Discord o formatear mensaje: {e}\nEvento: {evento}, Símbolo: {symbol}, Precio: {precio}"
                print(error_msg)
                try:
                    send_discord(error_msg)
                except Exception as e2:
                    print(f"Error adicional al intentar enviar mensaje de error a Discord: {e2}")
                resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e), "evento": evento, "symbol": symbol})
                continue

            resultados.append({"cuenta": cuenta_name, "status": "sin acción"})
        except Exception as e:
            resultados.append({"cuenta": cuenta_name, "status": "error", "msg": str(e)})

    return jsonify({"status": "ok", "resultados": resultados}), 200

if __name__ == "__main__":
    app.run(port=5000)

