#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scalping-Optimized Payload Builder - Enhanced with Backtest Support
"""

import MetaTrader5 as mt5
import pandas as pd
import ta
import json
import numpy as np
from datetime import datetime

class ScalpingPayloadBuilder:
    def __init__(self, symbol="XAUUSDm", timeframe=mt5.TIMEFRAME_M5, data=None):
        self.symbol = symbol
        self.timeframe = timeframe
        self.data = data  # For backtest mode
        self.trading_style = "scalping"
        self.recent_candles = 20  # Reduced for faster analysis

        print(f"🎯 Scalping Payload Builder: {symbol} - timeframe:{self.timeframe}s")

        if self.data is None:
            if not mt5.initialize():
                raise RuntimeError("❌ Không kết nối được MT5")
        else:
            print("🔄 Backtest mode: Skipping MT5 initialization")

    def _ensure_json_safe(self, obj):
        """Ensure object is JSON serializable"""
        if isinstance(obj, dict):
            return {key: self._ensure_json_safe(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._ensure_json_safe(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(self._ensure_json_safe(item) for item in obj)
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif hasattr(obj, 'item'):  # Other numpy scalars
            return obj.item()
        else:
            return obj

    def get_scalping_indicators(self, df):
        """Get fast-response indicators optimized for scalping"""
        try:
            indicators = {}
            
            # Fast Moving Averages 
            indicators["EMA_5"] = round(float(ta.trend.ema_indicator(df["close"], window=5).iloc[-1]), 5)
            indicators["EMA_9"] = round(float(ta.trend.ema_indicator(df["close"], window=9).iloc[-1]), 5)
            indicators["EMA_21"] = round(float(ta.trend.ema_indicator(df["close"], window=21).iloc[-1]), 5)
            
            # Fast RSI
            indicators["RSI"] = round(float(ta.momentum.rsi(df["close"], window=7).iloc[-1]), 2)
            indicators["RSI_14"] = round(float(ta.momentum.rsi(df["close"], window=14).iloc[-1]), 2)
            
            # Fast MACD
            macd_line = ta.trend.macd(df["close"], window_fast=5, window_slow=13).iloc[-1]
            macd_signal = ta.trend.macd_signal(df["close"], window_fast=5, window_slow=13).iloc[-1]
            macd_histogram = ta.trend.macd_diff(df["close"], window_fast=5, window_slow=13).iloc[-1]
            
            indicators["MACD"] = {
                "line": round(float(macd_line), 5),
                "signal": round(float(macd_signal), 5),
                "histogram": round(float(macd_histogram), 5),
                "cross": "Bullish" if macd_line > macd_signal else "Bearish"
            }
            
            # Fast Stochastic
            stoch_k = ta.momentum.stoch(df["high"], df["low"], df["close"], window=5).iloc[-1]
            indicators["Stochastic"] = {
                "K": round(float(stoch_k), 2),
                "signal": "Overbought" if stoch_k > 75 else "Oversold" if stoch_k < 25 else "Neutral"
            }
            
            # Williams %R
            indicators["Williams_R"] = round(float(ta.momentum.williams_r(df["high"], df["low"], df["close"], lbp=7).iloc[-1]), 2)
            
            # Price momentum
            indicators["Price_Momentum"] = round(float((df["close"].iloc[-1] - df["close"].iloc[-5]) / df["close"].iloc[-5] * 100), 3)
            
            # Tight Bollinger Bands
            bb_upper = ta.volatility.bollinger_hband(df["close"], window=10, window_dev=1.5).iloc[-1]
            bb_lower = ta.volatility.bollinger_lband(df["close"], window=10, window_dev=1.5).iloc[-1]
            bb_middle = ta.volatility.bollinger_mavg(df["close"], window=10).iloc[-1]
            
            indicators["Bollinger_Bands"] = {
                "upper": round(float(bb_upper), 5),
                "lower": round(float(bb_lower), 5),
                "middle": round(float(bb_middle), 5),
                "squeeze": bool(abs(bb_upper - bb_lower) / bb_middle < 0.02),
                "position": "Above" if df["close"].iloc[-1] > bb_upper else "Below" if df["close"].iloc[-1] < bb_lower else "Inside"
            }
            
            # Fast ATR
            indicators["ATR"] = round(float(ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=7).iloc[-1]), 5)
            
            # Price velocity
            indicators["Price_Velocity"] = round(float((df["close"].iloc[-1] - df["close"].iloc[-3]) / df["close"].iloc[-3] * 100), 4)
            
            # EMA Alignment
            ema5, ema9, ema21 = indicators["EMA_5"], indicators["EMA_9"], indicators["EMA_21"]
            if ema5 > ema9 > ema21:
                indicators["EMA_Alignment"] = "Strong_Bullish"
            elif ema5 < ema9 < ema21:
                indicators["EMA_Alignment"] = "Strong_Bearish"
            elif ema5 > ema9:
                indicators["EMA_Alignment"] = "Bullish"
            elif ema5 < ema9:
                indicators["EMA_Alignment"] = "Bearish"
            else:
                indicators["EMA_Alignment"] = "Neutral"
            
            # Volatility
            indicators["Volatility_Pct"] = round(float((df["high"].iloc[-1] - df["low"].iloc[-1]) / df["close"].iloc[-1] * 100), 3)
            
            # Scalping signals
            indicators["Scalping_Signals"] = {
                "ema_cross": "Bullish" if ema5 > ema9 else "Bearish" if ema5 < ema9 else "Neutral",
                "rsi_momentum": "Strong" if abs(indicators["RSI"] - 50) > 15 else "Weak",
                "macd_momentum": "Strong" if abs(indicators["MACD"]["histogram"]) > 0.1 else "Weak",
                "bb_squeeze_break": bool(indicators["Bollinger_Bands"]["squeeze"] and abs(indicators["Price_Velocity"]) > 0.01)
            }
            
            return self._ensure_json_safe(indicators)
            
        except Exception as e:
            print(f"⚠️ Error in scalping indicators: {e}")
            return self._get_fallback_indicators(df)
    
    def _get_fallback_indicators(self, df):
        """Fallback indicators if calculation fails"""
        current_price = float(df["close"].iloc[-1])
        return {
            "EMA_5": current_price,
            "EMA_9": current_price,
            "EMA_21": current_price,
            "RSI": 50.0,
            "RSI_14": 50.0,
            "EMA_Alignment": "Neutral",
            "Volatility_Pct": 1.0,
            "MACD": {"line": 0.0, "signal": 0.0, "histogram": 0.0, "cross": "Neutral"},
            "Stochastic": {"K": 50.0, "signal": "Neutral"},
            "Williams_R": -50.0,
            "Price_Momentum": 0.0,
            "Price_Velocity": 0.0,
            "Bollinger_Bands": {"upper": current_price, "lower": current_price, "middle": current_price, "squeeze": False, "position": "Inside"},
            "ATR": 1.0,
            "Scalping_Signals": {"ema_cross": "Neutral", "rsi_momentum": "Weak", "macd_momentum": "Weak", "bb_squeeze_break": False}
        }

    def get_recent_candles(self, df):
        """Get recent candles data"""
        recent = df.tail(self.recent_candles)
        candles_data = []
        
        for i, row in recent.iterrows():
            candle = {
                "o": round(float(row["open"]), 2),
                "h": round(float(row["high"]), 2),
                "l": round(float(row["low"]), 2),
                "c": round(float(row["close"]), 2),
                "d": "B" if float(row["close"]) > float(row["open"]) else "S" if float(row["close"]) < float(row["open"]) else "D"
            }
            candles_data.append(candle)
        
        return candles_data

    def build_scalping_payload(self,price_open=None):
        """Build optimized scalping payload - supports both live and backtest mode"""
        try:
            # Get data from MT5 or use provided data
            if self.data is not None:
                print(f"📊 BACKTEST: Using provided data ({len(self.data)} rows) - NO MT5 calls")
                df = self.data.copy()
                
                # Ensure time column is datetime
                if 'time' in df.columns:
                    try:
                        df["time"] = pd.to_datetime(df["time"], unit="s")
                    except (ValueError, TypeError, pd.errors.OutOfBoundsDatetimeError):
                        try:
                            df["time"] = pd.to_datetime(df["time"])
                        except:
                            print("⚠️ Warning: Could not parse time column, using index as fallback")
                            df["time"] = pd.to_datetime(df.index, unit='s')
                else:
                    df.reset_index(inplace=True)
                    if 'index' in df.columns:
                        df['time'] = pd.to_datetime(df['index'], unit='s')
                
                current_price = price_open if price_open is not None else float(df['close'].iloc[-1]) if len(df) > 0 and 'close' in df.columns else 0.0
                print(f'time-current: {df["time"].iloc[-1]}')
                print(f"💰 Current price from data: {current_price}")
                
            else:
                print(f"📈 REAL-TIME: Fetching data from MT5 for {self.symbol}")
                rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, 100)
                df = pd.DataFrame(rates)
                df["time"] = pd.to_datetime(df["time"], unit="s")

                
                # Get current price from MT5
                current_price = 0.0
                try:
                    mt5.symbol_select(self.symbol, True)
                    tick = mt5.symbol_info_tick(self.symbol)
                    if tick is not None:
                        ask = float(getattr(tick, "ask", 0.0) or 0.0)
                        bid = float(getattr(tick, "bid", 0.0) or 0.0)
                        last = float(getattr(tick, "last", 0.0) or 0.0)
                        current_price = bid if ask > 0 else (ask if bid > 0 else last)
                except Exception:
                    current_price = 0.0
                print(f"💰 Current price from MT5: {current_price}")
                
            
            # Get indicators
            indicators = self.get_scalping_indicators(df)
            
            # Get recent candles
            recent_candles = self.get_recent_candles(df)
            
            # Calculate confidence (aggressive for scalping)
            rsi_momentum = abs(indicators["RSI"] - 50) / 50 * 100
            macd_strength = min(abs(indicators["MACD"]["histogram"]) * 1000, 100)
            ema_trend = 80 if "Strong" in indicators["EMA_Alignment"] else 50 if indicators["EMA_Alignment"] in ["Bullish", "Bearish"] else 20
            
            # Scalping confidence boost
            confidence = (rsi_momentum * 0.4 + macd_strength * 0.35 + ema_trend * 0.25) * 1.3  # 30% boost
            confidence = min(confidence, 100)
            
            # Build payload with JSON serialization safety
            payload = {
                "symbol": self.symbol,
                "timeframe": str(self.timeframe),  # Ensure string for JSON
                "trading_style": "scalping",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "current_price": round(float(current_price), 5),  # Ensure float
                "indicators": self._ensure_json_safe(indicators),
                "recent_candles": self._ensure_json_safe(recent_candles),
                "support_resistance": {
                    "support": [round(float(df["low"].tail(10).min()), 5)],
                    "resistance": [round(float(df["high"].tail(10).max()), 5)]
                },
                "trend": str(indicators["EMA_Alignment"]),
                "confidence_metrics": {
                    "overall_confidence": round(float(confidence), 1),
                    "signal_strength": "High" if confidence > 70 else "Medium" if confidence > 40 else "Low"
                }
            }
            
            return payload
            
        except Exception as e:
            print(f"❌ Error building scalping payload: {e}")
            return {"error": str(e)}

# def test_scalping(use_sample_data=False):
#     """Test scalping payload - supports both live and backtest mode"""
#     print("🎯 TESTING SCALPING PAYLOAD")
#     print("=" * 40)
    
#     try:
#         if use_sample_data:
#             # Create sample backtest data
#             dates = pd.date_range(start='2025-09-22 10:00:00', periods=200, freq='1min')
            
#             sample_data = pd.DataFrame({
#                 'time': dates,
#                 'open': np.random.uniform(3680, 3720, 200),
#                 'high': np.random.uniform(3690, 3730, 200),
#                 'low': np.random.uniform(3670, 3710, 200), 
#                 'close': np.random.uniform(3685, 3715, 200),
#                 'tick_volume': np.random.randint(400, 800, 200),
#                 'spread': np.full(200, 160),
#                 'real_volume': np.zeros(200)
#             })
            
#             # Ensure high >= max(open, close) and low <= min(open, close)
#             sample_data['high'] = np.maximum(sample_data['high'], 
#                                            np.maximum(sample_data['open'], sample_data['close']))
#             sample_data['low'] = np.minimum(sample_data['low'], 
#                                           np.minimum(sample_data['open'], sample_data['close']))
            
#             builder = ScalpingPayloadBuilder(data=sample_data)
#             print("📊 Testing with sample backtest data")
#         else:
#             builder = ScalpingPayloadBuilder()
#             print("📈 Testing with live MT5 data")
        
#         payload = builder.build_scalping_payload()
        
#         if "error" in payload:
#             print(f"❌ Error: {payload['error']}")
#             return False
        
#         # Test JSON serialization
#         json_str = json.dumps(payload, ensure_ascii=False)
        
#         print("✅ Scalping payload generated successfully!")
#         print(f"📊 Size: {len(json_str)} characters ({len(json_str)//4} tokens)")
#         print(f"💰 Current price: ${payload['current_price']}")
#         print(f"🎯 Confidence: {payload['confidence_metrics']['overall_confidence']}%")
#         print(f"📈 Trend: {payload['trend']}")
#         print(f"⚡ EMA Cross: {payload['indicators']['Scalping_Signals']['ema_cross']}")
#         print(f"💪 RSI Momentum: {payload['indicators']['Scalping_Signals']['rsi_momentum']}")
#         print(f"🌊 MACD Momentum: {payload['indicators']['Scalping_Signals']['macd_momentum']}")
        
#         # Signal prediction
#         confidence = payload['confidence_metrics']['overall_confidence']
#         if confidence > 70:
#             print("🟢 PREDICTION: Strong BUY/SELL signal likely")
#         elif confidence > 50:
#             print("🟡 PREDICTION: Moderate signal possible")
#         else:
#             print("🔴 PREDICTION: Weak signal, likely HOLD")
        
#         print(f"\n🚀 SCALPING PAYLOAD OPTIMIZED FOR HIGH-FREQUENCY TRADING!")
        
#         # Test JSON serialization
#         try:
#             json_test = json.dumps(payload, ensure_ascii=False)
#             print(f"✅ JSON serialization successful!")
#             return True
#         except Exception as json_err:
#             print(f"❌ JSON serialization failed: {json_err}")
#             return False
        
#     except Exception as e:
#         print(f"❌ Test failed: {e}")
#         import traceback
#         traceback.print_exc()
#         return False

# def test_backtest_mode():
#     """Test backtest mode specifically"""
#     print("🔄 TESTING BACKTEST MODE")
#     print("=" * 30)
#     return test_scalping(use_sample_data=True)

# if __name__ == "__main__":
#     # Test both modes
#     print("🎯 TESTING LIVE MODE")
#     print("=" * 30)
#     live_success = test_scalping()  # Live mode
    
#     print("\n" + "=" * 60 + "\n")
    
#     print("🔄 TESTING BACKTEST MODE")
#     print("=" * 30)
#     backtest_success = test_backtest_mode()  # Backtest mode
    
#     print("\n" + "=" * 60)
#     if live_success and backtest_success:
#         print("🎉 ALL TESTS PASSED!")
#         print("✅ Live mode: Working")
#         print("✅ Backtest mode: Working")
#         print("✅ JSON serialization: Working")
#     else:
#         print("💥 SOME TESTS FAILED!")
#         print(f"Live mode: {'✅' if live_success else '❌'}")
#         print(f"Backtest mode: {'✅' if backtest_success else '❌'}")
#     print("=" * 60)