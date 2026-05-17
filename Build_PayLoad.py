# Build_PayLoad.py - Scalping-Optimized Version
import MetaTrader5 as mt5
import pandas as pd
import ta
import requests
from bs4 import BeautifulSoup
import json
import time
from datetime import datetime

class TradingPayloadBuilder:
    def __init__(self, symbol="XAUUSDm", timeframe=mt5.TIMEFRAME_M1, max_candles=50, data=None, trading_style="scalping"):
        self.symbol = symbol
        self.timeframe = timeframe if timeframe else mt5.TIMEFRAME_M1  # Default M1 for scalping
        self.max_candles = max_candles
        self.data = data
        self.trading_style = "scalping"  # Always scalping for high-frequency signals
        print(f"self.timeframe: {self.timeframe}, type: {type(self.timeframe)}")
        print(f"🎯 Trading style: SCALPING")

        # Optimized for scalping - faster signals
        self.recent_candles = 5  # Reduced for faster analysis

        if self.data is None:
            if not mt5.initialize():
                raise RuntimeError("❌ Không kết nối được MT5")
        else:
            print("🔄 Backtest mode: Skipping MT5 initialization")

    def _ensure_json_serializable(self, obj):
        """Convert numpy types to native Python types for JSON serialization"""
        import numpy as np
        
        if isinstance(obj, dict):
            return {key: self._ensure_json_serializable(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._ensure_json_serializable(item) for item in obj]
        elif isinstance(obj, tuple):
            return tuple(self._ensure_json_serializable(item) for item in obj)
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)  # Convert numpy bool to Python bool
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif hasattr(obj, 'item'):  # Other numpy scalars
            return obj.item()
        else:
            return obj

    def get_recent_candles_data(self, df):
        """Extract recent candles data for AI context - optimized"""
        recent = df.tail(self.recent_candles)
        
        candles_data = []
        for i, row in recent.iterrows():
            candle_info = {
                "o": round(float(row["open"]), 2),
                "h": round(float(row["high"]), 2),
                "l": round(float(row["low"]), 2),
                "c": round(float(row["close"]), 2),
                "b": round(float(abs(row["close"] - row["open"])), 2),
                "d": "B" if float(row["close"]) > float(row["open"]) else "S" if float(row["close"]) < float(row["open"]) else "D"
            }
            candles_data.append(candle_info)
        
        return candles_data

    def get_scalping_indicators(self, df):
        """Get fast-response indicators optimized for scalping"""
        try:
            indicators = {}
            
            # Fast Moving Averages for scalping
            indicators["EMA_5"] = round(ta.trend.ema_indicator(df["close"], window=5).iloc[-1], 5)
            indicators["EMA_9"] = round(ta.trend.ema_indicator(df["close"], window=9).iloc[-1], 5)
            indicators["EMA_21"] = round(ta.trend.ema_indicator(df["close"], window=21).iloc[-1], 5)
            
            # RSI - Fast settings for scalping
            indicators["RSI"] = round(ta.momentum.rsi(df["close"], window=7).iloc[-1], 2)  # Faster RSI
            indicators["RSI_14"] = round(ta.momentum.rsi(df["close"], window=14).iloc[-1], 2)  # Standard RSI
            
            # MACD - Fast settings for scalping (5,13,5 instead of 12,26,9)
            macd_line = ta.trend.macd(df["close"], window_fast=5, window_slow=13).iloc[-1]
            macd_signal = ta.trend.macd_signal(df["close"], window_fast=5, window_slow=13).iloc[-1] 
            macd_histogram = ta.trend.macd_diff(df["close"], window_fast=5, window_slow=13).iloc[-1]
            
            indicators["MACD"] = {
                "line": round(macd_line, 5),
                "signal": round(macd_signal, 5),
                "histogram": round(macd_histogram, 5),
                "cross": "Bullish" if macd_line > macd_signal else "Bearish"
            }
            
            # Fast Stochastic for scalping
            stoch_k = ta.momentum.stoch(df["high"], df["low"], df["close"], window=5, smooth_window=3).iloc[-1]  # Faster settings
            stoch_d = ta.momentum.stoch_signal(df["high"], df["low"], df["close"], window=5, smooth_window=3).iloc[-1]
            
            indicators["Stochastic"] = {
                "K": round(stoch_k, 2),
                "D": round(stoch_d, 2),
                "signal": "Overbought" if stoch_k > 75 else "Oversold" if stoch_k < 25 else "Neutral"  # Tighter levels
            }
            
            # Williams %R - Fast for scalping
            indicators["Williams_R"] = round(ta.momentum.williams_r(df["high"], df["low"], df["close"], lbp=7).iloc[-1], 2)  # Faster
            
            # Price momentum for scalping
            indicators["Price_Momentum"] = round(((df["close"].iloc[-1] - df["close"].iloc[-5]) / df["close"].iloc[-5]) * 100, 3)  # 5-period momentum
            
            # Bollinger Bands - Tight for scalping
            bb_upper = ta.volatility.bollinger_hband(df["close"], window=10, window_dev=1.5).iloc[-1]  # Tighter bands
            bb_lower = ta.volatility.bollinger_lband(df["close"], window=10, window_dev=1.5).iloc[-1]
            bb_middle = ta.volatility.bollinger_mavg(df["close"], window=10).iloc[-1]
            
            indicators["Bollinger_Bands"] = {
                "upper": round(bb_upper, 5),
                "lower": round(bb_lower, 5),
                "middle": round(bb_middle, 5),
                "squeeze": abs(bb_upper - bb_lower) / bb_middle < 0.02,  # Tight squeeze detection
                "position": "Above" if df["close"].iloc[-1] > bb_upper else "Below" if df["close"].iloc[-1] < bb_lower else "Inside"
            }
            
            # Fast ATR for scalping stops
            indicators["ATR"] = round(ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=7).iloc[-1], 5)
            
            # Price velocity (rate of change)
            indicators["Price_Velocity"] = round((df["close"].iloc[-1] - df["close"].iloc[-3]) / df["close"].iloc[-3] * 100, 4)
            
            # Fast EMA Alignment for scalping
            ema5 = indicators["EMA_5"]
            ema9 = indicators["EMA_9"]
            ema21 = indicators["EMA_21"]
            
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
            
            # Volatility Percentage
            high_low_pct = (df["high"].iloc[-1] - df["low"].iloc[-1]) / df["close"].iloc[-1] * 100
            indicators["Volatility_Pct"] = round(high_low_pct, 3)
            
            # Scalping signals
            indicators["Scalping_Signals"] = {
                "ema_cross": "Bullish" if ema5 > ema9 and df["close"].iloc[-2] <= ta.trend.ema_indicator(df["close"], window=9).iloc[-2] else "Bearish" if ema5 < ema9 and df["close"].iloc[-2] >= ta.trend.ema_indicator(df["close"], window=9).iloc[-2] else "None",
                "rsi_momentum": "Strong" if abs(indicators["RSI"] - 50) > 15 else "Weak",
                "macd_momentum": "Strong" if abs(indicators["MACD"]["histogram"]) > 0.5 else "Weak",
                "bb_squeeze_break": indicators["Bollinger_Bands"]["squeeze"] and indicators["Price_Velocity"] != 0
            }
            
            
        except Exception as e:
            print(f"⚠️ Error calculating scalping indicators: {e}")
            return {}

    def get_price_action_analysis(self, df):
        """Comprehensive price action analysis"""
        try:
            current = df.iloc[-1]
            recent_5 = df.tail(5)
            recent_10 = df.tail(10)
            recent_20 = df.tail(20)
            
            # Current candle
            current_candle = {
                "open": round(float(current["open"]), 5),
                "high": round(float(current["high"]), 5),
                "low": round(float(current["low"]), 5),
                "close": round(float(current["close"]), 5),
                "body_size": round(abs(current["close"] - current["open"]), 5),
                "upper_shadow": round(current["high"] - max(current["open"], current["close"]), 5),
                "lower_shadow": round(min(current["open"], current["close"]) - current["low"], 5),
                "range": round(current["high"] - current["low"], 5),
                "direction": "Bullish" if current["close"] > current["open"] else "Bearish" if current["close"] < current["open"] else "Doji"
            }
            
            # Price movement analysis
            price_movement = {
                "trend_5": self._analyze_trend(recent_5),
                "trend_10": self._analyze_trend(recent_10),
                "bullish_candles_5": len(recent_5[recent_5["close"] > recent_5["open"]]),
                "bearish_candles_5": len(recent_5[recent_5["close"] < recent_5["open"]]),
                "price_change_5": round(float(recent_5["close"].iloc[-1] - recent_5["open"].iloc[0]), 5),
                "price_change_pct_5": round(float(((recent_5["close"].iloc[-1] / recent_5["open"].iloc[0]) - 1) * 100), 3),
                "avg_body_size_5": round(float(abs(recent_5["close"] - recent_5["open"]).mean()), 5),
                "volatility_increase": self._check_volatility_increase(recent_5, recent_10),
                
                # Momentum indicators
                "consecutive_direction": self._get_consecutive_direction(recent_5),
                "momentum_acceleration": self._check_momentum_acceleration(recent_5),
            }
            
            # Market structure
            session_high = float(recent_20["high"].max())
            session_low = float(recent_20["low"].min())
            
            market_structure = {
                "session_high": round(session_high, 5),
                "session_low": round(session_low, 5),
                "session_range": round(session_high - session_low, 5),
                "current_position_pct": round(((current["close"] - session_low) / (session_high - session_low)) * 100, 1) if session_high != session_low else 50,
                "key_resistance": round(float(recent_10["high"].max()), 5),
                "key_support": round(float(recent_10["low"].min()), 5),
                "volume_trend": self._analyze_volume_trend(recent_5),
                "break_level": "Resistance" if current["close"] > recent_10["high"].max() * 0.999 else "Support" if current["close"] < recent_10["low"].min() * 1.001 else "Range"
            }
            
            # Pattern detection
            patterns = {
                "current_pattern": self._detect_current_patterns(df.tail(3)),
                "reversal_signals": self._detect_reversal_patterns(df.tail(5)),
                "continuation_signals": self._detect_continuation_patterns(recent_5),
                "breakout_signals": self._detect_breakout_signals(recent_10, current)
            }
            
            return {
                "current_candle": current_candle,
                "price_movement": price_movement,
                "market_structure": market_structure,
                "patterns": patterns
            }
            
        except Exception as e:
            print(f"⚠️ Error in price action analysis: {e}")
            return {"error": str(e)}

    def _analyze_trend(self, df_slice):
        """Analyze trend direction"""
        if len(df_slice) < 3:
            return "Insufficient_Data"
        
        closes = df_slice["close"]
        first_third = closes.iloc[:len(closes)//3].mean()
        last_third = closes.iloc[-len(closes)//3:].mean()
        
        change_pct = ((last_third - first_third) / first_third) * 100
        
        if change_pct > 0.1:
            return "Strong_Up"
        elif change_pct < -0.1:
            return "Strong_Down"
        elif change_pct > 0.05:
            return "Up"
        elif change_pct < -0.05:
            return "Down"
        else:
            return "Sideways"

    def _check_volatility_increase(self, recent, earlier):
        """Check if volatility is increasing"""
        recent_vol = (recent["high"] - recent["low"]).mean()
        earlier_vol = (earlier.head(len(earlier) - len(recent))["high"] - earlier.head(len(earlier) - len(recent))["low"]).mean()
        return recent_vol > earlier_vol * 1.2 if earlier_vol > 0 else False

    def _get_consecutive_direction(self, df_slice):
        """Count consecutive moves in same direction"""
        if len(df_slice) < 2:
            return 0
        
        direction_changes = (df_slice["close"].diff() > 0).astype(int)
        current_direction = direction_changes.iloc[-1]
        
        count = 0
        for i in range(len(direction_changes) - 1, -1, -1):
            if direction_changes.iloc[i] == current_direction:
                count += 1
            else:
                break
        
        return count

    def _check_momentum_acceleration(self, df_slice):
        """Check if momentum is accelerating"""
        if len(df_slice) < 3:
            return "Unknown"
        
        changes = df_slice["close"].pct_change().dropna()
        if len(changes) < 2:
            return "Unknown"
        
        latest_change = abs(changes.iloc[-1])
        prev_change = abs(changes.iloc[-2])
        
        if latest_change > prev_change * 1.5:
            return "Accelerating"
        elif latest_change < prev_change * 0.7:
            return "Decelerating"
        else:
            return "Stable"

    def _analyze_volume_trend(self, df_slice):
        """Analyze volume trend"""
        vol_col = "tick_volume" if "tick_volume" in df_slice.columns else "volume" if "volume" in df_slice.columns else None
        if vol_col is None:
            return "No_Data"
        
        if len(df_slice) < 3:
            return "Insufficient_Data"
        
        recent_vol = df_slice[vol_col].tail(2).mean()
        earlier_vol = df_slice[vol_col].head(3).mean()
        
        if recent_vol > earlier_vol * 1.3:
            return "Increasing"
        elif recent_vol < earlier_vol * 0.7:
            return "Decreasing"
        else:
            return "Stable"

    def _detect_current_patterns(self, df_slice):
        """Detect current candle patterns"""
        if len(df_slice) < 2:
            return ["Insufficient_Data"]
        
        patterns = []
        current = df_slice.iloc[-1]
        prev = df_slice.iloc[-2]
        
        body = abs(current["close"] - current["open"])
        range_size = current["high"] - current["low"]
        
        # Doji
        if body < range_size * 0.1 and range_size > 0:
            patterns.append("Doji")
        
        # Hammer/Shooting Star
        upper_shadow = current["high"] - max(current["open"], current["close"])
        lower_shadow = min(current["open"], current["close"]) - current["low"]
        
        if body > 0:
            if lower_shadow > body * 2 and upper_shadow < body * 0.5:
                patterns.append("Hammer")
            elif upper_shadow > body * 2 and lower_shadow < body * 0.5:
                patterns.append("Shooting_Star")
        
        # Inside/Outside Bar
        if current["high"] < prev["high"] and current["low"] > prev["low"]:
            patterns.append("Inside_Bar")
        elif current["high"] > prev["high"] and current["low"] < prev["low"]:
            patterns.append("Outside_Bar")
        
        return patterns if patterns else ["Normal"]

    def _detect_reversal_patterns(self, df_slice):
        """Detect reversal patterns"""
        if len(df_slice) < 3:
            return []
        
        patterns = []
        recent = df_slice.tail(3)
        
        # Morning Star / Evening Star
        if len(recent) >= 3:
            first = recent.iloc[0]
            middle = recent.iloc[1] 
            last = recent.iloc[2]
            
            # Evening Star (bearish reversal)
            if (first["close"] > first["open"] and  # First candle bullish
                abs(middle["close"] - middle["open"]) < abs(first["close"] - first["open"]) * 0.3 and  # Middle doji-like
                last["close"] < last["open"] and  # Last candle bearish
                last["close"] < first["close"]):
                patterns.append("Evening_Star")
            
            # Morning Star (bullish reversal)
            elif (first["close"] < first["open"] and  # First candle bearish
                  abs(middle["close"] - middle["open"]) < abs(first["close"] - first["open"]) * 0.3 and  # Middle doji-like
                  last["close"] > last["open"] and  # Last candle bullish
                  last["close"] > first["close"]):
                patterns.append("Morning_Star")
        
        # Engulfing patterns
        if len(recent) >= 2:
            prev = recent.iloc[-2]
            curr = recent.iloc[-1]
            
            # Bullish engulfing
            if (prev["close"] < prev["open"] and  # Previous bearish
                curr["close"] > curr["open"] and  # Current bullish
                curr["open"] < prev["close"] and  # Gap down
                curr["close"] > prev["open"]):  # Engulfs previous
                patterns.append("Bullish_Engulfing")
            
            # Bearish engulfing
            elif (prev["close"] > prev["open"] and  # Previous bullish
                  curr["close"] < curr["open"] and  # Current bearish
                  curr["open"] > prev["close"] and  # Gap up
                  curr["close"] < prev["open"]):  # Engulfs previous
                patterns.append("Bearish_Engulfing")
        
        return patterns

    def _detect_continuation_patterns(self, df_slice):
        """Enhanced continuation pattern detection"""
        if len(df_slice) < 4:
            return []
            
        patterns = []
        recent = df_slice.tail(6)  # Use more candles
        
        # Enhanced Flag/Pennant patterns
        if len(recent) >= 5:
            # Strong initial move
            initial_move = recent.iloc[:2]
            consolidation = recent.iloc[2:4]
            breakout = recent.iloc[-1]
            
            initial_strength = abs(initial_move["close"].iloc[-1] - initial_move["open"].iloc[0])
            consolidation_range = consolidation["high"].max() - consolidation["low"].min()
            
            if initial_strength > consolidation_range * 1.5:  # Strong move vs consolidation
                direction = "bullish" if initial_move["close"].iloc[-1] > initial_move["open"].iloc[0] else "bearish"
                
                # Flag pattern (parallel lines)
                if direction == "bullish":
                    if (breakout["close"] > consolidation["high"].max() and
                        breakout["close"] > breakout["open"]):
                        patterns.append("Bullish_Flag_Breakout")
                        patterns.append("Continuation_Confirmed")
                else:
                    if (breakout["close"] < consolidation["low"].min() and
                        breakout["close"] < breakout["open"]):
                        patterns.append("Bearish_Flag_Breakout")
                        patterns.append("Continuation_Confirmed")
                
                # Pennant pattern (converging lines)
                consolidation_highs = consolidation["high"].values
                consolidation_lows = consolidation["low"].values
                
                if (len(consolidation_highs) >= 2 and len(consolidation_lows) >= 2):
                    high_trend = consolidation_highs[-1] < consolidation_highs[0]  # Declining highs
                    low_trend = consolidation_lows[-1] > consolidation_lows[0]    # Rising lows
                    
                    if high_trend and low_trend:  # Converging
                        if direction == "bullish" and breakout["close"] > consolidation["high"].max():
                            patterns.append("Bullish_Pennant")
                        elif direction == "bearish" and breakout["close"] < consolidation["low"].min():
                            patterns.append("Bearish_Pennant")
        
        # Enhanced Three Soldiers/Crows
        if len(recent) >= 3:
            last_three = recent.tail(3)
            closes = last_three["close"].values
            opens = last_three["open"].values
            
            # Three White Soldiers (stronger version)
            if all(closes > opens):  # All bullish candles
                if all(closes[i] > closes[i-1] for i in range(1, len(closes))):  # Rising closes
                    if all(opens[i] > opens[i-1] for i in range(1, len(opens))):  # Rising opens
                        body_sizes = abs(closes - opens)
                        if all(body_sizes > body_sizes.mean() * 0.7):  # Good body sizes
                            patterns.append("Three_White_Soldiers")
                            patterns.append("Strong_Bullish_Momentum")
            
            # Three Black Crows (stronger version)
            elif all(closes < opens):  # All bearish candles
                if all(closes[i] < closes[i-1] for i in range(1, len(closes))):  # Falling closes
                    if all(opens[i] < opens[i-1] for i in range(1, len(opens))):  # Falling opens
                        body_sizes = abs(closes - opens)
                        if all(body_sizes > body_sizes.mean() * 0.7):  # Good body sizes
                            patterns.append("Three_Black_Crows")
                            patterns.append("Strong_Bearish_Momentum")
        
        # Triangle patterns (more sophisticated)
        if len(recent) >= 5:
            highs = recent["high"].values
            lows = recent["low"].values
            
            # Ascending Triangle (bullish continuation)
            resistance_level = max(highs)
            resistance_tests = sum(1 for h in highs if abs(h - resistance_level) / resistance_level < 0.005)
            
            if resistance_tests >= 2:  # Multiple resistance tests
                if lows[-1] > lows[0]:  # Rising lows
                    patterns.append("Ascending_Triangle")
            
            # Descending Triangle (bearish continuation)
            support_level = min(lows)
            support_tests = sum(1 for l in lows if abs(l - support_level) / support_level < 0.005)
            
            if support_tests >= 2:  # Multiple support tests
                if highs[-1] < highs[0]:  # Falling highs
                    patterns.append("Descending_Triangle")
            
            # Symmetrical Triangle
            if len(highs) >= 4 and len(lows) >= 4:
                high_slope = (highs[-1] - highs[0]) / len(highs)
                low_slope = (lows[-1] - lows[0]) / len(lows)
                
                if high_slope < 0 and low_slope > 0:  # Converging lines
                    range_compression = (max(highs) - min(lows)) / recent["close"].mean()
                    if range_compression < 0.02:  # Tight range
                        patterns.append("Symmetrical_Triangle")
        
        # Rectangle/Channel patterns
        if len(recent) >= 4:
            highs = recent["high"]
            lows = recent["low"]
            
            resistance = highs.max()
            support = lows.min()
            
            # Check for horizontal resistance/support
            resistance_touches = sum(1 for h in highs if abs(h - resistance) / resistance < 0.01)
            support_touches = sum(1 for l in lows if abs(l - support) / support < 0.01)
            
            if resistance_touches >= 2 and support_touches >= 2:
                patterns.append("Rectangle_Pattern")
                
                # Check for breakout
                current_price = recent["close"].iloc[-1]
                if current_price > resistance * 1.002:
                    patterns.append("Rectangle_Breakout_Bull")
                elif current_price < support * 0.998:
                    patterns.append("Rectangle_Breakout_Bear")
        
        # Gap patterns
        if len(recent) >= 2:
            for i in range(1, len(recent)):
                curr = recent.iloc[i]
                prev = recent.iloc[i-1]
                
                # Bullish gap
                if curr["low"] > prev["high"]:
                    gap_size = (curr["low"] - prev["high"]) / prev["close"]
                    if gap_size > 0.002:  # Significant gap
                        patterns.append("Bullish_Gap")
                        if gap_size > 0.01:  # Large gap
                            patterns.append("Strong_Bullish_Gap")
                
                # Bearish gap
                elif curr["high"] < prev["low"]:
                    gap_size = (prev["low"] - curr["high"]) / prev["close"]
                    if gap_size > 0.002:  # Significant gap
                        patterns.append("Bearish_Gap")
                        if gap_size > 0.01:  # Large gap
                            patterns.append("Strong_Bearish_Gap")
        
        return list(set(patterns))  # Remove duplicates

    def _detect_breakout_signals(self, df_recent, current):
        """Enhanced breakout signal detection"""
        signals = []
        
        # Multi-timeframe support/resistance levels
        recent_high = df_recent["high"].max()
        recent_low = df_recent["low"].min()
        
        # Calculate dynamic support/resistance levels
        highs = df_recent["high"].values
        lows = df_recent["low"].values
        closes = df_recent["close"].values
        
        # Pivot highs and lows
        pivot_highs = []
        pivot_lows = []
        
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1] and highs[i] > highs[i-2] and highs[i] > highs[i+2]:
                pivot_highs.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i+1] and lows[i] < lows[i-2] and lows[i] < lows[i+2]:
                pivot_lows.append(lows[i])
        
        # Key resistance levels (multiple touches)
        if pivot_highs:
            for resistance in pivot_highs:
                touches = sum(1 for h in highs if abs(h - resistance) / resistance < 0.005)
                if touches >= 2:  # Confirmed resistance
                    if current["close"] > resistance * 1.002:  # Clean breakout
                        signals.append("Confirmed_Resistance_Breakout")
                        if current["close"] > resistance * 1.005:  # Strong breakout
                            signals.append("Strong_Resistance_Breakout")
                    elif current["high"] >= resistance * 0.999:  # Test resistance
                        signals.append("Resistance_Test")
        
        # Key support levels (multiple touches)
        if pivot_lows:
            for support in pivot_lows:
                touches = sum(1 for l in lows if abs(l - support) / support < 0.005)
                if touches >= 2:  # Confirmed support
                    if current["close"] < support * 0.998:  # Clean breakdown
                        signals.append("Confirmed_Support_Breakdown")
                        if current["close"] < support * 0.995:  # Strong breakdown
                            signals.append("Strong_Support_Breakdown")
                    elif current["low"] <= support * 1.001:  # Test support
                        signals.append("Support_Test")
        
        # Enhanced range breakouts
        recent_range = recent_high - recent_low
        if recent_range > 0:
            mid_point = (recent_high + recent_low) / 2
            quarter_range = recent_range * 0.25
            
            # Upper quarter breakout (strong bullish)
            if current["close"] > recent_high - quarter_range:
                if current["close"] > recent_high:
                    signals.append("Range_High_Breakout")
                else:
                    signals.append("Upper_Range_Test")
            
            # Lower quarter breakdown (strong bearish)
            elif current["close"] < recent_low + quarter_range:
                if current["close"] < recent_low:
                    signals.append("Range_Low_Breakdown")
                else:
                    signals.append("Lower_Range_Test")
            
            # Mid-range breakouts
            if current["close"] > mid_point + quarter_range:
                signals.append("Upward_Momentum")
            elif current["close"] < mid_point - quarter_range:
                signals.append("Downward_Momentum")
        
        # Volume-based breakout confirmation
        vol_col = "tick_volume" if "tick_volume" in df_recent.columns else "volume" if "volume" in df_recent.columns else None
        if vol_col is not None:
            recent_volumes = df_recent[vol_col].values
            avg_volume = recent_volumes.mean()
            current_volume = current.get(vol_col, 0)
            
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
            
            if volume_ratio > 1.5:  # High volume
                signals.append("High_Volume_Activity")
                if volume_ratio > 2.0:  # Very high volume
                    signals.append("Exceptional_Volume")
                    
                # Volume + price breakout confirmation
                if any("Breakout" in signal for signal in signals):
                    signals.append("Volume_Confirmed_Breakout")
            elif volume_ratio < 0.5:  # Low volume
                signals.append("Low_Volume_Warning")
        
        # Momentum and volatility breakouts
        if len(closes) >= 3:
            price_changes = []
            for i in range(1, len(closes)):
                change = (closes[i] - closes[i-1]) / closes[i-1]
                price_changes.append(abs(change))
            
            avg_change = sum(price_changes) / len(price_changes) if price_changes else 0
            current_change = abs((current["close"] - closes[-1]) / closes[-1])
            
            if current_change > avg_change * 2:  # Strong momentum
                signals.append("Momentum_Breakout")
                if current_change > avg_change * 3:  # Exceptional momentum
                    signals.append("Explosive_Move")
        
        # Gap breakouts
        last_close = df_recent["close"].iloc[-1]
        gap_up = current["open"] > last_close * 1.002
        gap_down = current["open"] < last_close * 0.998
        
        if gap_up:
            gap_size = (current["open"] - last_close) / last_close
            if gap_size > 0.005:  # Significant gap
                signals.append("Gap_Up_Breakout")
                if gap_size > 0.01:  # Large gap
                    signals.append("Large_Gap_Up")
        elif gap_down:
            gap_size = (last_close - current["open"]) / last_close
            if gap_size > 0.005:  # Significant gap
                signals.append("Gap_Down_Breakdown")
                if gap_size > 0.01:  # Large gap
                    signals.append("Large_Gap_Down")
        
        # Time-based breakout patterns
        # Morning/Evening breakouts tend to be more reliable
        from datetime import datetime
        current_hour = datetime.now().hour
        
        if 8 <= current_hour <= 10 or 20 <= current_hour <= 22:  # Key trading hours
            if any("Breakout" in signal for signal in signals):
                signals.append("Prime_Time_Breakout")
        
        # Consolidation breakouts (after period of low volatility)
        if len(highs) >= 5:
            recent_ranges = []
            for i in range(len(highs) - 4, len(highs)):
                day_range = (highs[i] - lows[i]) / closes[i] if closes[i] > 0 else 0
                recent_ranges.append(day_range)
            
            avg_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else 0
            current_range = (current["high"] - current["low"]) / current["close"] if current["close"] > 0 else 0
            
            if current_range > avg_range * 1.5:  # Expansion after consolidation
                signals.append("Volatility_Expansion")
                if current_range > avg_range * 2:
                    signals.append("Volatility_Breakout")
        
        return list(set(signals))  # Remove duplicates

    # UPDATED get_mt5_payload với enhanced format
    def get_mt5_payload(self):        
        # ... existing data fetching code unchanged ...
        if self.data is not None:
            print(f"📊 BACKTEST: Using provided data ({len(self.data)} rows) - NO MT5 calls")
            df = self.data.copy()
            
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
            
            current_price = float(df['close'].iloc[-1]) if len(df) > 0 and 'close' in df.columns else 0.0
            print(f"💰 Current price from data: {current_price}")
            
        else:
            print(f"📈 REAL-TIME: Fetching data from MT5 for {self.symbol}")
            needed_candles = max(int(self.max_candles), 200)
            rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, needed_candles)
            print(f"Retrieved {len(rates)} candles from MT5")
            
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            
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

        # Scalping indicators
        indicators = self.get_scalping_indicators(df)
        
        # Enhanced price action analysis
        price_action = self.get_price_action_analysis(df)
        
        # Recent candles for context
        recent_candles = self.get_recent_candles_data(df)
        
        # Support/Resistance
        support = [round(df["low"].tail(30).min(), 5), round(df["low"].tail(10).min(), 5)]
        resistance = [round(df["high"].tail(30).max(), 5), round(df["high"].tail(10).max(), 5)]

        # Enhanced trend analysis
        ema9 = indicators.get("EMA_9", current_price)
        ema21 = indicators.get("EMA_21", current_price)
        ema50 = indicators.get("EMA_50", current_price)
        ema200 = indicators.get("EMA_200", current_price)
        
        short_trend = "Bullish" if ema9 > ema21 else "Bearish"
        long_trend = "Bullish" if ema50 > ema200 else "Bearish"
        trend = f"{short_trend}/{long_trend}"

        # Enhanced price action pattern
        last_candle = df.iloc[-1]
        prev_candle = df.iloc[-2]
        if last_candle["close"] < prev_candle["open"] and last_candle["open"] > prev_candle["close"]:
            price_action_pattern = "Bearish_Engulfing"
        elif last_candle["close"] > prev_candle["open"] and last_candle["open"] < prev_candle["close"]:
            price_action_pattern = "Bullish_Engulfing"
        else:
            price_action_pattern = "None"

        tf_label = {
            1: "M1", 5: "M5", 15: "M15", 30: "M30",
            60: "H1", 240: "H4", 1440: "D1",
            mt5.TIMEFRAME_M1: "M1", 
            mt5.TIMEFRAME_M5: "M5",
            mt5.TIMEFRAME_M15: "M15",
            mt5.TIMEFRAME_M30: "M30",
            mt5.TIMEFRAME_H1: "H1",
            mt5.TIMEFRAME_H4: "H4",
            mt5.TIMEFRAME_D1: "D1"
        }.get(self.timeframe, f"TF_{self.timeframe}")

        # 🎯 ENHANCED OUTPUT FORMAT FOR AI TRADING SIGNALS with JSON serialization fix
        payload = {
            "symbol": self.symbol,
            "timeframe": tf_label,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "current_price": round(float(current_price), 5),  # Ensure float
            
            # Core technical analysis
            "indicators": self._ensure_json_serializable(indicators),
            "price_action": self._ensure_json_serializable(price_action),
            "recent_candles": self._ensure_json_serializable(recent_candles),
            "support_resistance": {
                "support": [float(s) for s in support], 
                "resistance": [float(r) for r in resistance]
            },
            "trend": str(trend),
            "price_action_pattern": str(price_action_pattern),
            
            # AI-focused trading context
            "market_context": {
                "volatility_environment": "High" if float(indicators.get("Volatility_Pct", 0)) > 2 else "Low" if float(indicators.get("Volatility_Pct", 0)) < 0.5 else "Normal",
                "trend_strength": float(indicators.get("ADX", 0)),
                "market_phase": str(self._determine_market_phase(indicators, price_action))
            },
            
            # Data confidence metrics for AI analysis
            "confidence_metrics": self._ensure_json_serializable({
                "trend_confidence": self._calculate_trend_confidence(indicators),
                "volatility_score": round(float(indicators.get("Volatility_Pct", 0)), 2),
                "momentum_strength": self._calculate_momentum_strength(indicators, price_action),
                "pattern_reliability": self._assess_pattern_reliability(price_action.get("patterns", {})),
                "overall_confidence": 0  # Will be calculated
            })
        }
        
        # Calculate overall confidence
        payload["confidence_metrics"]["overall_confidence"] = float(self._calculate_overall_confidence(payload["confidence_metrics"]))
        
        return payload

    def _determine_market_phase(self, indicators, price_action):
        """Determine current market phase for AI context"""
        volatility = indicators.get("Volatility_Pct", 0)
        adx = indicators.get("ADX", 0)
        rsi = indicators.get("RSI", 50)
        
        if adx > 25 and volatility > 1.5:
            return "Trending_High_Vol"
        elif adx > 25:
            return "Trending"
        elif volatility > 2:
            return "High_Volatility_Range"
        elif rsi > 70 or rsi < 30:
            return "Overbought_Oversold"
        else:
            return "Consolidation"
    

    
    def _calculate_trend_confidence(self, indicators):
        """Calculate trend confidence score 0-100"""
        ema_alignment = indicators.get("EMA_Alignment", "Mixed")
        adx = indicators.get("ADX", 20)
        macd_div = indicators.get("MACD", {}).get("divergence", "Bearish")
        
        score = 0
        if "Strong" in ema_alignment:
            score += 40
        elif ema_alignment in ["Bullish", "Bearish"]:
            score += 25
        
        if adx > 30:
            score += 30
        elif adx > 20:
            score += 15
        
        if macd_div == "Bullish":
            score += 15
        elif macd_div == "Bearish":
            score += 15
        
        score += min(adx, 25)  # ADX bonus up to 25
        
        return min(score, 100)
    
    def _calculate_momentum_strength(self, indicators, price_action):
        """Calculate momentum strength 0-100"""
        rsi = indicators.get("RSI", 50)
        roc = indicators.get("ROC", 0)
        momentum_acc = price_action.get("price_movement", {}).get("momentum_acceleration", "Stable")
        
        score = 0
        
        # RSI momentum
        if rsi > 60:
            score += 30
        elif rsi < 40:
            score += 30
        else:
            score += 10
        
        # ROC momentum
        if abs(roc) > 0.5:
            score += 40
        elif abs(roc) > 0.2:
            score += 25
        else:
            score += 10
        
        # Momentum acceleration
        if momentum_acc == "Accelerating":
            score += 30
        elif momentum_acc == "Stable":
            score += 15
        
        return min(score, 100)
    
    def _assess_pattern_reliability(self, patterns):
        """Assess pattern reliability 0-100"""
        if not patterns:
            return 0
            
        reliable_patterns = [
            "Bullish_Engulfing", "Bearish_Engulfing", "Morning_Star", "Evening_Star",
            "Three_White_Soldiers", "Three_Black_Crows", "Bullish_Flag_Breakout", "Bearish_Flag_Breakout"
        ]
        
        score = 0
        total_patterns = 0
        
        for pattern_type, pattern_list in patterns.items():
            if isinstance(pattern_list, list):
                for pattern in pattern_list:
                    total_patterns += 1
                    if pattern in reliable_patterns:
                        score += 25
                    else:
                        score += 10
        
        return min(score, 100) if total_patterns > 0 else 30
    
    def _calculate_overall_confidence(self, confidence_metrics):
        """Calculate scalping confidence 0-100 - more aggressive"""
        trend_conf = confidence_metrics.get("trend_confidence", 0)
        momentum_str = confidence_metrics.get("momentum_strength", 0)
        pattern_rel = confidence_metrics.get("pattern_reliability", 0)
        volatility = confidence_metrics.get("volatility_score", 1)
        
        # Scalping weights - favor momentum and immediate signals
        weighted_score = (
            trend_conf * 0.25 +
            momentum_str * 0.45 +
            pattern_rel * 0.20 +
            min(volatility * 15, 30) * 0.10  # Higher volatility = higher confidence for scalping
        )
        
        # Boost confidence for scalping (less conservative)
        boosted_score = min(weighted_score * 1.2, 100)  # 20% boost
        
        return round(boosted_score, 1)
    
    def _determine_market_phase(self, indicators, price_action):
        """Determine current market phase for AI context"""
        volatility = indicators.get("Volatility_Pct", 0)
        adx = indicators.get("ADX", 0)
        rsi = indicators.get("RSI", 50)
        
        if adx > 25 and volatility > 1.5:
            return "Trending_High_Vol"
        elif adx > 25:
            return "Trending"
        elif volatility > 2:
            return "High_Volatility_Range"
        elif rsi > 70 or rsi < 30:
            return "Overbought_Oversold"
        else:
            return "Consolidation"
    

        
        if volatility > 3 or adx < 15:
            return "Small"  # High volatility or weak trend
        elif volatility < 1 and adx > 30:
            return "Large"  # Low volatility and strong trend
        else:
            return "Medium"
    
    def _calculate_trend_confidence(self, indicators):
        """Calculate trend confidence score 0-100"""
        ema_alignment = indicators.get("EMA_Alignment", "Mixed")
        adx = indicators.get("ADX", 20)
        macd_div = indicators.get("MACD", {}).get("divergence", "Bearish")
        
        score = 0
        if "Strong" in ema_alignment:
            score += 40
        elif ema_alignment in ["Bullish", "Bearish"]:
            score += 25
        
        if adx > 30:
            score += 30
        elif adx > 20:
            score += 15
        
        if macd_div == "Bullish":
            score += 15
        elif macd_div == "Bearish":
            score += 15
        
        score += min(adx, 25)  # ADX bonus up to 25
        
        return min(score, 100)
    
    def _calculate_momentum_strength(self, indicators, price_action):
        """Calculate momentum strength 0-100"""
        rsi = indicators.get("RSI", 50)
        roc = indicators.get("ROC", 0)
        momentum_acc = price_action.get("price_movement", {}).get("momentum_acceleration", "Stable")
        
        score = 0
        
        # RSI momentum
        if rsi > 60:
            score += 30
        elif rsi < 40:
            score += 30
        else:
            score += 10
        
        # ROC momentum
        if abs(roc) > 0.5:
            score += 40
        elif abs(roc) > 0.2:
            score += 25
        else:
            score += 10
        
        # Momentum acceleration
        if momentum_acc == "Accelerating":
            score += 30
        elif momentum_acc == "Stable":
            score += 15
        
        return min(score, 100)
    
    def _assess_pattern_reliability(self, patterns):
        """Assess pattern reliability 0-100"""
        if not patterns:
            return 0
            
        reliable_patterns = [
            "Bullish_Engulfing", "Bearish_Engulfing", "Morning_Star", "Evening_Star",
            "Three_White_Soldiers", "Three_Black_Crows", "Bullish_Flag_Breakout", "Bearish_Flag_Breakout"
        ]
        
        score = 0
        total_patterns = 0
        
        for pattern_type, pattern_list in patterns.items():
            if isinstance(pattern_list, list):
                for pattern in pattern_list:
                    total_patterns += 1
                    if pattern in reliable_patterns:
                        score += 25
                    else:
                        score += 10
        
        return min(score, 100) if total_patterns > 0 else 30
    
    def _calculate_overall_confidence(self, confidence_metrics):
        """Calculate overall trading confidence 0-100"""
        trend_conf = confidence_metrics.get("trend_confidence", 0)
        momentum_str = confidence_metrics.get("momentum_strength", 0)
        pattern_rel = confidence_metrics.get("pattern_reliability", 0)
        volatility = confidence_metrics.get("volatility_score", 1)
        
        # Weight the components
        weighted_score = (
            trend_conf * 0.35 +
            momentum_str * 0.30 +
            pattern_rel * 0.25 +
            min((2 - volatility) * 20, 40) * 0.10  # Lower volatility = higher confidence
        )
        
        return round(min(weighted_score, 100), 1)

    # ... existing news methods unchanged ...
    def get_forexfactory_news(self):
        json_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        try:
            r = requests.get(json_url, headers=headers, timeout=15)
            r.raise_for_status()
            items = r.json()
            news_data = []
            # Ngày hiện tại theo UTC+7
            today_utc7 = (pd.Timestamp.utcnow() + pd.Timedelta(hours=7)).date()
            for it in items:
                try:
                    impact = it.get("impact", "") or "None"
                    if isinstance(impact, dict):
                        impact_text = impact.get("display", "None")
                    else:
                        impact_text = str(impact)

                    if "High" in impact_text:
                        strength = "Strong"
                    elif "Medium" in impact_text:
                        strength = "Moderate"
                    else:
                        strength = "Weak"

                    # Convert time to UTC+7 if possible
                    date_raw = it.get("date", "")
                    try:
                        ts = pd.to_datetime(date_raw, utc=True, errors='coerce')
                        if pd.notna(ts):
                            ts_utc7 = (ts + pd.Timedelta(hours=7)).tz_localize(None)
                            time_utc7 = ts_utc7.strftime("%Y-%m-%d %H:%M:%S")
                            # Chỉ lấy tin của ngày hiện tại theo UTC+7
                            if ts_utc7.date() != today_utc7:
                                continue
                        else:
                            time_utc7 = str(date_raw)
                            # Không xác định được thời gian → bỏ qua để đảm bảo chỉ lấy tin trong ngày
                            continue
                    except Exception:
                        time_utc7 = str(date_raw)
                        # Không xác định được thời gian → bỏ qua
                        continue

                    news_data.append({
                        "time": time_utc7,
                        "currency": it.get("country", ""),
                        "event": it.get("title", ""),
                        "impact": impact_text,
                        "strength": strength
                    })
                except Exception:
                    continue
            return news_data
        except Exception:
            # Fallback parse HTML nếu JSON không truy cập được (có thể không đủ do render JS)
            try:
                url = "https://www.forexfactory.com/calendar"
                r = requests.get(url, headers=headers, timeout=15)
                soup = BeautifulSoup(r.text, "html.parser")
                news_data = []
                for row in soup.select("tr.calendar__row"):
                    try:
                        time_str = row.select_one("td.calendar__time").get_text(strip=True)
                        currency = row.select_one("td.calendar__currency").get_text(strip=True)
                        event = row.select_one("td.calendar__event").get_text(strip=True)
                        impact_tag = row.select_one("td.calendar__impact span")
                        impact = impact_tag.get("title") if impact_tag else "None"
                        if "High" in impact:
                            strength = "Strong"
                        elif "Medium" in impact:
                            strength = "Moderate"
                        else:
                            strength = "Weak"
                        news_data.append({
                            "time": time_str,
                            "currency": currency,
                            "event": event,
                            "impact": impact,
                            "strength": strength
                        })
                    except Exception:
                        continue
                return news_data
            except Exception:
                return []
        # ... existing implementation unchanged ...
        pass

    def build_payload(self, news=True):
        mt5_data = self.get_mt5_payload()
        if news:
            news_data = self.get_forexfactory_news()
        else:
            news_data = []
        payload = {**mt5_data, "news_sentiment": news_data}
        return payload

# Usage examples:
# Scalping
# print("=" * 60)
# print("🧪 TESTING SCALPING PAYLOAD")
# print("=" * 60)

# scalper = TradingPayloadBuilder(symbol="XAUUSDm", timeframe=mt5.TIMEFRAME_M1, trading_style="scalping")
# scalping_payload = scalper.build_payload(news=False)

# print(f"📊 Scalping payload size: {len(str(scalping_payload))} characters")
# print(f"🔑 Payload keys: {list(scalping_payload.keys())}")

# if "error" not in scalping_payload:
#     print(f"✅ SUCCESS - Scalping payload generated")
#     print(f"💰 Current price: {scalping_payload.get('current_price', 'N/A')}")
#     print(f"📈 Trend: {scalping_payload.get('trend', 'N/A')}")
#     print(f"🎯 Indicators count: {len(scalping_payload.get('indicators', {}))}")
#     print(f"🕯️ Recent candles: {len(scalping_payload.get('recent_candles', []))}")
# else:
#     print(f"❌ ERROR: {scalping_payload['error']}")

# print("\n" + "=" * 60)
# print("📋 SCALPING PAYLOAD DETAILS:")
# print("=" * 60)

# # Print main sections
# for key, value in scalping_payload.items():
#     if key == "indicators":
#         print(f"🎯 {key}: {len(value)} indicators")
#         for ind_key, ind_val in value.items():
#             if isinstance(ind_val, (int, float)):
#                 print(f"   {ind_key}: {ind_val}")
#             elif isinstance(ind_val, dict):
#                 print(f"   {ind_key}: {ind_val}")
#     elif key == "recent_candles":
#         print(f"🕯️ {key}: {len(value)} candles")
#         if len(value) > 0:
#             print(f"   First: {value[0]}")
#             print(f"   Last: {value[-1]}")
#     elif key == "price_action":
#         print(f"📊 {key}: {type(value)}")
#         if isinstance(value, dict):
#             for pa_key, pa_val in value.items():
#                 print(f"   {pa_key}: {pa_val}")
#     else:
#         print(f"📋 {key}: {value}")

