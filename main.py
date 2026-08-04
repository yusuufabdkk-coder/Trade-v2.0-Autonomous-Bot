import logging
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError
from config import get_settings
from models import AIDataPayload
from pydantic import BaseModel
from ai_trader import get_trade_decision
from binance_executor import executor
from telegram_bot import send_telegram_message
import asyncio
import html

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Trade v2.0 - Autonomous AI Agent")
settings = get_settings()

# Import autonomous loop
from autonomous_loop import start_autonomous_loop, stop_autonomous_loop

@app.on_event("startup")
async def startup_event():
    """Start the autonomous trading loop when the app starts."""
    logger.info("🚀 App starting — launching autonomous Binance data loop...")
    start_autonomous_loop()

@app.on_event("shutdown")
async def shutdown_event():
    """Stop the autonomous loop gracefully."""
    stop_autonomous_loop()

class ChatRequest(BaseModel):
    message: str

from storage import load_chat_history, save_chat_history

# Store user chat interactions (persistent)
user_chat_history = load_chat_history()

@app.get("/")
async def root():
    return {"status": "running", "system": "Trade v2.0 AI Agent", "version": "3.0.0", "mode": "autonomous"}

@app.get("/health")
async def health():
    from ai_trader import rate_limiter
    return {
        "status": "healthy",
        "ai_calls_today": rate_limiter.calls_today,
        "max_calls_per_day": settings.MAX_AI_CALLS_PER_DAY,
        "testnet": settings.BINANCE_TESTNET
    }

from fastapi.responses import HTMLResponse

@app.get("/logs", response_class=HTMLResponse)
async def view_logs():
    from ai_trader import ai_history
    
    html_content = """
    <html>
        <head>
            <title>AI Trade Logs</title>
            <style>
                body { font-family: Arial, sans-serif; background-color: #1e1e1e; color: #d4d4d4; padding: 20px; }
                h1 { color: #569cd6; }
                .log-entry { background-color: #252526; border-left: 4px solid #007acc; padding: 15px; margin-bottom: 20px; border-radius: 4px; }
                .time { color: #4ec9b0; font-weight: bold; }
                .decision { color: #ce9178; font-weight: bold; font-size: 1.1em; }
                pre { background-color: #1e1e1e; padding: 10px; border: 1px solid #333; overflow-x: auto; white-space: pre-wrap; }
                .prompt { color: #9cdcfe; }
                .response { color: #c586c0; }
            </style>
        </head>
        <body>
            <h1>🤖 AI Trade Logs (Last 50)</h1>
    """
    
    if not ai_history:
        html_content += "<p>No logs available yet. Waiting for TradingView webhooks...</p>"
        
    for idx, entry in enumerate(ai_history):
        # Highlight the first (latest) entry slightly differently or keep it open by default
        is_open = "open" if idx == 0 else ""
        
        # Formatting Execution Details
        exec_details = ""
        if entry.get('decision') != 'WAIT':
            price_str = f"{entry.get('execution_price')} USDT" if entry.get('execution_price') else "MARKET"
            exec_details = f" | Executed Price: <span style='color: #dcdcaa;'>{price_str}</span>"
        
        html_content += f"""
        <details class="log-entry" {is_open}>
            <summary>
                <span class="time">{entry['time']}</span> | Symbol: {entry['symbol']} | Decision: <span class="decision">{entry['decision']}</span>
                | Balance: <span style="color: #4ec9b0;">{entry.get('balance', 0.0):.2f} USDT</span> {exec_details}
            </summary>
            <div style="padding-top: 10px;">
                <h3>📥 Giden Prompt (TradingView -> Claude)</h3>
                <pre class="prompt">{entry['prompt']}</pre>
                <h3>📤 Gelen Cevap (Claude -> Sistem)</h3>
                <pre class="response">{entry['raw_response']}</pre>
                <h3>📈 Borsa Sonucu</h3>
                <pre style="color: #ce9178;">{entry.get('execution_msg', 'İşlem Yok (WAIT)')}</pre>
            </div>
        </details>
        """
        
    # Build previous chat history HTML
    chat_html = ""
    for msg in user_chat_history:
        if msg['role'] == 'user':
            chat_html += f'<p><strong>Sen:</strong> {msg["content"]}</p>'
        else:
            safe_resp = str(msg["content"]).replace('\\n', '<br>')
            chat_html += f'<p style="color: #c586c0;"><strong>Claude:</strong> {safe_resp}</p>'

    html_content += f"""
        <div id="chat-container" style="margin-top: 40px; padding: 20px; background-color: #252526; border-radius: 8px;">
            <h2>💬 Yapay Zeka İle Sohbet (Geçmiş Sohbetler Kaydedilir)</h2>
            <div id="chat-history" style="height: 300px; overflow-y: auto; background-color: #1e1e1e; padding: 10px; border: 1px solid #333; margin-bottom: 10px;">
                {chat_html}
            </div>
            <input type="text" id="chat-input" placeholder="Yapay zekaya bir şey sor..." style="width: 80%; padding: 10px; background-color: #333; color: white; border: 1px solid #555;">
            <button onclick="sendChatMessage()" style="width: 18%; padding: 10px; background-color: #007acc; color: white; border: none; cursor: pointer;">Gönder</button>
        </div>
        <script>
            // Scroll to bottom on load
            const historyDiv = document.getElementById('chat-history');
            historyDiv.scrollTop = historyDiv.scrollHeight;

            async function sendChatMessage() {{
                const input = document.getElementById('chat-input');
                const msg = input.value;
                if(!msg) return;
                
                historyDiv.innerHTML += '<p><strong>Sen:</strong> ' + msg + '</p>';
                input.value = '';
                historyDiv.innerHTML += '<p id="loading" style="color: #888;">Yapay Zeka düşünüyor...</p>';
                historyDiv.scrollTop = historyDiv.scrollHeight;
                
                try {{
                    const res = await fetch('/chat', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{message: msg}})
                    }});
                    const data = await res.json();
                    document.getElementById('loading').remove();
                    historyDiv.innerHTML += '<p style="color: #c586c0;"><strong>Claude:</strong> ' + data.response.replace(/\\n/g, '<br>') + '</p>';
                    historyDiv.scrollTop = historyDiv.scrollHeight;
                }} catch(e) {{
                    document.getElementById('loading').remove();
                    historyDiv.innerHTML += '<p style="color: red;"><strong>Hata:</strong> ' + e + '</p>';
                }}
            }}
        </script>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.post("/chat")
async def chat_with_ai(chat_req: ChatRequest):
    from ai_trader import ai_history
    import anthropic
    global user_chat_history
    
    if not ai_history:
        return {"response": "Hiç log bulunmuyor. Lütfen ilk sinyali bekleyin."}
        
    latest_log = ai_history[0]
    
    system_prompt = f'''
Sen XAUUSDT SMC yatırım asistanısın. Aşağıda son incelediğin piyasa verisi ve senin o anki kararın yer alıyor. 
Kullanıcı bu kararınla veya genel strateji ile ilgili sana soru soruyor. Lütfen Türkçe yanıtla ve dostça davran.

--- GELEN VERİ (SON İŞLEM BAĞLAMI) ---
{latest_log['prompt']}

--- SENİN YANITIN/KARARIN ---
{latest_log['raw_response']}
'''

    # Build messages array
    messages = []
    # Add past chat history
    for msg in user_chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
        
    # Add current user message
    messages.append({"role": "user", "content": chat_req.message})
    
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        response = await client.messages.create(
            model=settings.AI_MODEL_NAME,
            max_tokens=800,
            temperature=0.7,
            system=system_prompt,
            messages=messages
        )
        
        reply_text = response.content[0].text
        
        # Save to history
        user_chat_history.append({"role": "user", "content": chat_req.message})
        user_chat_history.append({"role": "assistant", "content": reply_text})
        
        # Keep history manageable (last 40 messages = 20 turns)
        if len(user_chat_history) > 40:
            user_chat_history = user_chat_history[-40:]
            
        save_chat_history(user_chat_history)
            
        return {"response": reply_text}
    except Exception as e:
        return {"response": f"API Hatası: {e}"}

@app.post("/webhook")
async def receive_data(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Validate generic payload
    try:
        payload = AIDataPayload(**body)
    except ValidationError as e:
        logger.error(f"Payload validation failed: {e.errors()}")
        raise HTTPException(status_code=422, detail=e.errors())

    # Security check
    if payload.secret != settings.WEBHOOK_SECRET:
        logger.warning(f"Unauthorized access attempt with secret: {payload.secret}")
        raise HTTPException(status_code=401, detail="Unauthorized")

    logger.info(f"Received 5m data packet for {payload.symbol} at {payload.bar_time}. Forwarding to AI...")

    # Run AI evaluation asynchronously so we can return 200 OK immediately if needed, 
    # but since we want to respond to the webhook properly, we'll await it.
    # TradingView timeout is around 3 seconds, so we might want to run this in background!
    asyncio.create_task(process_ai_decision(payload))
    
    return {"status": "ok", "message": "Data received, processing via AI in background."}

async def process_ai_decision(payload: AIDataPayload):
    decision = await get_trade_decision(payload)
    logger.info(f"AI Decision: {decision.decision}")
    
    if decision.decision in ["LONG", "SHORT", "CLOSE_LONG", "CLOSE_SHORT"]:
        # Fetch open position BEFORE executing (in case we are closing it)
        clean_sym = payload.symbol.split(":")[-1].replace(".P", "")
        pos_before = executor.get_open_position(clean_sym)
        
        # Execute trade
        execution_result = executor.execute_trade(payload.symbol, decision)
        
        from ai_trader import ai_history
        if len(ai_history) > 0:
            ai_history[0]["execution_price"] = execution_result.get("price", 0.0)
            ai_history[0]["execution_msg"] = execution_result.get("msg", "")
        
        # Escape HTML chars to prevent Telegram Bad Request
        safe_reasoning = html.escape(decision.reasoning)
        safe_exec_msg = html.escape(str(execution_result.get('msg', '')))
        
        rsi_warning = ""
        if payload.rsi_14 > 70:
            rsi_warning = f"⚠️ <b>RSI Durumu:</b> {payload.rsi_14:.1f} (Aşırı Alım - Tehlikeli)\n"
        elif payload.rsi_14 < 30:
            rsi_warning = f"⚠️ <b>RSI Durumu:</b> {payload.rsi_14:.1f} (Aşırı Satım - Tehlikeli)\n"
        else:
            rsi_warning = f"ℹ️ <b>RSI Durumu:</b> {payload.rsi_14:.1f} (Normal)\n"
            
        # Build Telegram Message
        if "CLOSE" in decision.decision:
            duration = pos_before.get('duration_minutes', 0)
            pnl = pos_before.get('unrealized_pnl', 0.0)
            
            msg = f"🛑 <b>AI POZİSYON KAPATTI ({decision.decision})</b> 🛑\n\n"
            msg += f"<b>Sembol:</b> {payload.symbol}\n"
            msg += f"⏱️ <b>Açık Kalma Süresi:</b> {duration} Dakika\n"
            msg += f"💰 <b>Anlık Kâr/Zarar:</b> {pnl:.2f} USDT\n"
            msg += rsi_warning
            msg += f"<b>Kapanış Fiyatı:</b> {execution_result.get('price') or 'MARKET'}\n\n"
            msg += f"<b>Kapatma Sebebi:</b>\n{safe_reasoning}\n\n"
            msg += f"<b>Borsa Sonucu:</b> {safe_exec_msg}"
        else:
            lev = decision.leverage or 10
            notional = decision.trade_amount_usdt or 60.0
            margin_cost = notional / lev
            msg = f"🤖 <b>AI İŞLEM AÇTI ({decision.decision})</b> 🤖\n\n"
            msg += f"<b>Sembol:</b> {payload.symbol}\n"
            msg += f"⚡ <b>Kaldıraç:</b> {lev}x\n"
            msg += f"<b>Pozisyon Büyüklüğü:</b> {notional} USDT\n"
            msg += f"💳 <b>Kullanılan Teminat:</b> ~{margin_cost:.2f} USDT\n"
            msg += f"<b>Giriş:</b> {execution_result.get('price') or decision.entry_price or 'MARKET'}\n"
            msg += f"<b>Zarar Kes (SL):</b> {decision.stop_loss}\n"
            msg += f"<b>Kar Al (TP):</b> {decision.take_profit}\n"
            msg += rsi_warning + "\n"
            msg += f"<b>Yapay Zeka Analizi:</b>\n{safe_reasoning}\n\n"
            msg += f"<b>Borsa Sonucu:</b> {safe_exec_msg}"
        
        await send_telegram_message(msg)
    else:
        # If WAIT, we can optionally log to telegram, but probably better to keep it silent to avoid spam every 5m.
        logger.info(f"AI chose to WAIT. Reasoning: {decision.reasoning}")

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", settings.PORT))
    uvicorn.run("main:app", host=settings.HOST, port=port, reload=False)
