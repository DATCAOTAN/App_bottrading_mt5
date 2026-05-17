#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Client - Extracted AI calling and validation functions from LiveTradeAI
"""

import json
import requests
import logging

# Setup logging
logger = logging.getLogger("ai_client")

class AIClient:
    """Client for calling AI endpoints and validating responses.
    
    Contains the AI calling and decision validation logic extracted from LiveTradeAI.
    """
    
    def __init__(self, ai_endpoint: str, ai_key: str, ai_name_model: str, 
                 symbol: str = "XAUUSDm", timeframe_sec: int = 60, rr: float | None = None):
        self.ai_endpoint = ai_endpoint or "https://api.openai.com/v1/responses"
        self.ai_key = ai_key
        self.ai_name_model = ai_name_model
        self.symbol = symbol
        self.timeframe_sec = int(timeframe_sec)
        self.rr = rr

    def _call_ai(self, payload: dict) -> dict:
        """Call AI endpoint to get trading decision.
        
        Args:
            payload: Trading data payload to send to AI
            
        Returns:
            dict: AI response containing trading decision
            
        Raises:
            RuntimeError: If AI call fails
        """
        headers = {
            "Content-Type": "application/json"
        }
        if self.ai_key:
            headers["Authorization"] = f"Bearer {self.ai_key}"

        # Special handling for OpenAI endpoints
        if "api.openai.com" in (self.ai_endpoint or ""):
            # Default model; can be overridden by passing different endpoint or extending config
            default_model = self.ai_name_model
            user_content = {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
            # Nếu user chỉ định endpoint Responses API, dùng format JSON object
            # https://learn.microsoft.com/en-us/azure/ai-services/cognitive-services-apis/openai/reference/v1/responses
            # https://platform.openai.com/docs/api-reference/chat/completions/create
            # https://platform.openai.com/docs/guides/chat/introduction
            # https://platform.openai.com/docs/guides/chat/response-formatting
            # https://learn.microsoft.com/en-us/azure/ai-services/cognitive-services-apis/openai/concepts/response-formatting
            # https://learn.microsoft.com/en-us/azure/ai-services/cognitive-services-apis/openai/concepts/response-formatting#response-format-types
            # Yêu cầu AI trả về JSON object với các khóa cần thiết
            # để tránh parse lỗi do giải thích thêm

            # Compose a strict instruction to return a JSON object with required keys only
            instruction = (
            f"Bạn là senior quant trader chuyên SCALPING với 15+ năm kinh nghiệm. "
            f"Phân tích dữ liệu scalping cho symbol {self.symbol} khung thời gian {self.timeframe_sec} giây để đưa ra quyết định giao dịch nhanh và chính xác.\n\n"
            
            f"PHÂN TÍCH DỮ LIỆU SCALPING INPUT:\n"
            f"- Current price: Giá hiện tại của symbol\n"
            f"- Trading style: 'scalping' (giao dịch tần suất cao {self.timeframe_sec} giây)\n"
            f"- Fast Indicators: EMA 5/9/21, RSI-7, Fast MACD 5,13, Stochastic-5, Williams %R-7, ATR-7\n"
            f"- Tight Bollinger Bands: window=10, dev=1.5 (phát hiện breakout nhanh)\n"
            f"- Price Momentum & Velocity: Tốc độ thay đổi giá 3-5 nến\n"
            f"- EMA Alignment: Strong_Bullish/Strong_Bearish/Bullish/Bearish/Neutral\n"
            f"- Scalping Signals: ema_cross, rsi_momentum, macd_momentum, bb_squeeze_break\n"
            f"- Recent candles: 20 nến gần nhất format [o,h,l,c,d] (d=B/S/D)\n"
            f"- Support/Resistance: Mức hỗ trợ kháng cự ngắn hạn\n"
            f"- Confidence metrics: Độ tin cậy với scalping boost 30%\n\n"
            
            
            f"CÔNG THỨC RISK:REWARD SCALPING:\n"
            f"- Risk = |entry_price - stop_loss|\n"
            f"- Reward = |take_profit - entry_price|\n"
            f"- R:R = Reward / Risk\n"
            f"- YÊU CẦU: R:R >= {self.rr if self.rr else 1.0} (Scalping cho phép R:R thấp hơn)\n\n"
            
            f"KHOẢNG CÁCH STOP LOSS"
            f"- Stop Loss: Khoảng cách từ entry_price phải từ 2-4 đơn vị giá\n"
            f"- Ví dụ: entry=2650.50 → SL có thể 2648.50-2646.50 (BUY) hoặc 2652.50-2654.50 (SELL)\n"
            
            f"VÍ DỤ SCALPING R:R:\n"
            f"- Signal BUY: entry=2650.00, stop_loss=2647.00 (khoảng cách 3.0), take_profit=2655.00 (khoảng cách 5.0)\n"
            f"- Risk = |2650.00-2647.00| = 3.00\n"
            f"- Reward = |2655.00-2650.00| = 5.00\n"
            f"- R:R = 5.00/3.00 = 1.67  (thỏa >= {self.rr if self.rr else 1.0})\n"
            f"- Khoảng cách SL: 3.00 ✅ (trong khoảng 2-4)\n"
            
            
            f"OUTPUT FORMAT (chỉ JSON, không giải thích):\n"
            f'{{"signal": "buy|sell|hold", "entry_price": float|null, "stop_loss": float|null, "take_profit": float|null, "confidence": float, "pending_timeout_sec": int|null}}\n\n'
            
            f"LƯU Ý SCALPING:\n"
            f"1. QUAN TRỌNG; R:R >= {self.rr if self.rr else 1.0}\n"    
            f"2. QUAN TRỌNG: |entry_price - stop_loss| phải trong khoảng 2-4 đơn vị giá\n"
            f"3. Pending timeout: {self.timeframe_sec}-{self.timeframe_sec*4} giây (nhanh)\n"
            f"4. Nếu không thể thỏa điều kiện trả về signal='hold'\n"
        )
            # Xây dựng content theo chuẩn Responses API (content parts)
            user_payload_text = json.dumps(payload, ensure_ascii=False)

            try:
                if self.ai_endpoint.rstrip("/").endswith("/v1/responses"):
                    body = {
                        "model": default_model,
                        "input": [
                            {
                                "role": "system",
                                "content": [
                                        {"type": "input_text", "text": instruction}
                                ]
                            },
                            {
                                "role": "user",
                                "content": [
                                    {"type": "input_text", "text": user_payload_text}
                                ]
                            }
                        ],
                        "text": {
                            "format": {"type": "json_object"}
                        }
                    }
                else:
                    # Fallback to chat completions if user points elsewhere
                    # e.g., https://api.openai.com/v1/chat/completions
                    body = {
                        "model": default_model,
                        "messages": [
                            {"role": "system", "content": instruction},
                            user_content,
                        ],
                        "temperature": 0
                    }

                resp = requests.post(self.ai_endpoint, json=body, headers=headers, timeout=30)
                try:
                    resp.raise_for_status()
                except requests.HTTPError as http_err:
                    # Log chi tiết body lỗi để chẩn đoán 400
                    raise RuntimeError(f"OpenAI HTTPError {resp.status_code}: {resp.text}") from http_err
                data = resp.json()

                # Try to extract JSON from OpenAI responses or chat-completions
                def _extract_decision(obj: dict) -> dict:
                    # Shortcut field sometimes provided by Responses API
                    try:
                        if isinstance(obj.get("output_text"), list) and obj["output_text"]:
                            txt = obj["output_text"][0].strip()
                            if txt:
                                return json.loads(txt)
                    except Exception:
                        pass
                    # Responses API shape
                    try:
                        output = obj.get("output")
                        if isinstance(output, list) and output:
                            parts = output[0].get("content", [])
                            # Lấy text từ phần tử đầu tiên (thường là output_text)
                            if isinstance(parts, list) and parts:
                                text = parts[0].get("text", "").strip()
                                if text:
                                    return json.loads(text)
                    except Exception:
                        pass
                    # Chat Completions shape
                    try:
                        choices = obj.get("choices")
                        if isinstance(choices, list) and choices:
                            msg = choices[0].get("message", {}).get("content", "").strip()
                            if msg:
                                # Handle ```json code block format
                                if msg.startswith("```json"):
                                    # Extract JSON from code block
                                    start = msg.find("{")
                                    end = msg.rfind("}") + 1
                                    if start != -1 and end > start:
                                        json_str = msg[start:end]
                                        return json.loads(json_str)
                                else:
                                    # Try direct JSON parse
                                    return json.loads(msg)
                    except Exception as e:
                        print(f"⚠️ Failed to parse chat completion: {e}")
                        logger.warning(f"Failed to parse chat completion: {e}")
                        print(f"📄 Content was: {msg[:200]}...")
                        logger.debug(f"Content was: {msg[:200]}...")
                        pass
                    # As last resort, return the raw object (will be validated later)
                    return obj

                return _extract_decision(data)
            except Exception as e:
                raise RuntimeError(f"OpenAI call failed: {e}")

        # Generic HTTP JSON POST for custom endpoints
        resp = requests.post(self.ai_endpoint, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _validate_decision(decision: dict) -> dict:
        """Validate and normalize AI output schema.
        
        Args:
            decision: Raw AI response dictionary
            
        Returns:
            dict: Validated and normalized decision with required keys:
                - signal: "buy"|"sell"|"hold" 
                - entry_price: float|None
                - stop_loss: float|None  
                - take_profit: float|None
                - confidence: float
                - pending_timeout_sec: int|None
                
        Raises:
            ValueError: If decision format is invalid or missing required keys
        """
        if not isinstance(decision, dict):
            raise ValueError(f"AI response must be dict, got {type(decision)}: {decision}")
            
        # Debug: Show what keys we actually have
        available_keys = list(decision.keys()) if isinstance(decision, dict) else []
        print(f"🔍 Available keys in AI response: {available_keys}")
        logger.debug(f"Available keys in AI response: {available_keys}")
        
        if "signal" not in decision or "confidence" not in decision:
            raise ValueError(f"AI response missing required keys: signal, confidence. Available keys: {available_keys}")
        
        if "signal" not in decision:
            # Try alternative key names
            if "action" in decision:
                decision["signal"] = decision["action"]
            elif "decision" in decision:
                decision["signal"] = decision["decision"]
            else:
                raise ValueError(f"No signal/action/decision key found. Keys: {available_keys}")
                
        if "confidence" not in decision:
            # Provide default confidence if missing
            decision["confidence"] = 0.5
            print("⚠️ No confidence provided, defaulting to 0.5")
            logger.warning("No confidence provided, defaulting to 0.5")
            
        signal = str(decision["signal"]).strip().lower()
        if signal not in ("buy", "sell", "hold"):
            raise ValueError(f"Invalid AI signal: {decision['signal']}")

        # Optional fields may be null
        ep = decision.get("entry_price", None)
        sl = decision.get("stop_loss", None)
        tp = decision.get("take_profit", None)
        pending_timeout = decision.get("pending_timeout_sec", None)

        def _to_float_or_none(x):
            try:
                return float(x) if x is not None else None
            except Exception:
                return None

        def _to_int_or_none(x):
            try:
                return int(x) if x is not None else None
            except Exception:
                return None

        # Normalize types
        ep = _to_float_or_none(ep)
        sl = _to_float_or_none(sl)
        tp = _to_float_or_none(tp)
        pending_timeout = _to_int_or_none(pending_timeout)

        # For hold, allow None for price levels
        if signal in ("buy", "sell"):
            # Not strictly required, but keep numeric if provided
            pass

        return {
            "signal": signal,
            "entry_price": ep,
            "stop_loss": sl,
            "take_profit": tp,
            "confidence": float(decision["confidence"]),
            "pending_timeout_sec": pending_timeout,
        }

