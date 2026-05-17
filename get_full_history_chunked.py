"""
Script lấy toàn bộ dữ liệu lịch sử bằng cách chia nhỏ requests
Để tránh giới hạn của MT5 API
"""

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
import sys
import os

# Import hàm từ utils_account
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils_account import get_oldest_candle

def get_full_history_chunked(symbol, timeframe, from_date=None, to_date=None, chunk_days=30, save_to_csv=False):
    """
    Lấy toàn bộ dữ liệu lịch sử bằng cách chia nhỏ thành chunks
    
    Args:
        symbol: Symbol cần lấy (vd: XAUUSDm)
        timeframe: Timeframe (vd: mt5.TIMEFRAME_M5)
        from_date: Ngày bắt đầu (datetime object hoặc None để lấy từ oldest)
        to_date: Ngày kết thúc (datetime object hoặc None để lấy đến hiện tại)
        chunk_days: Số ngày mỗi chunk (default: 30)
        save_to_csv: Có lưu file CSV không
    
    Returns:
        DataFrame hoặc None nếu lỗi
    """
    
    if not mt5.initialize():
        print("❌ MT5 initialization failed")
        return None
    
    try:
        # Xác định from_date
        if from_date is None:
            print(f"🔍 Getting oldest time for {symbol}...")
            from_date = get_oldest_candle(symbol, timeframe)
            if from_date is None:
                print(f"❌ Cannot find oldest candle for {symbol}")
                return None
            # Nếu là tuple, lấy phần tử đầu tiên
            if isinstance(from_date, tuple):
                from_date = from_date[0]
        else:
            print(f"📅 RECEIVED from_date parameter: {from_date} (type: {type(from_date)})")
            
        # Xác định to_date
        if to_date is None:
            to_date = datetime.now()
            print(f"📅 Using current time as to_date: {to_date}")
        else:
            print(f"📅 RECEIVED to_date parameter: {to_date} (type: {type(to_date)})")
            
        total_days = (to_date - from_date).days
        
        print(f"📊 Data range: {from_date} to {to_date}")
        print(f"📅 Total duration: {total_days} days")
        print(f"🔄 Will process in {chunk_days}-day chunks...")
        
        all_data = []
        chunk_count = 0
        
        # Chia thành chunks và lấy từng phần
        start_time = from_date
        
        while start_time < to_date:
            chunk_count += 1
            end_time = min(start_time + timedelta(days=chunk_days), to_date)
            
            print(f"\n📦 Chunk {chunk_count}: {start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')}")
            
            # Lấy data cho chunk này
            rates = mt5.copy_rates_range(symbol, timeframe, start_time, end_time)
            
            if rates is not None and len(rates) > 0:
                df_chunk = pd.DataFrame(rates)
                df_chunk['time'] = pd.to_datetime(df_chunk['time'], unit='s')
                all_data.append(df_chunk)
                print(f"   ✅ Got {len(rates)} candles")
            else:
                print(f"   ⚠️ No data for this chunk")
            
            # Move to next chunk
            start_time = end_time
        
        if not all_data:
            print("❌ No data collected from any chunk")
            return None
        
        # Combine all chunks
        print(f"\n🔄 Combining {len(all_data)} chunks...")
        full_df = pd.concat(all_data, ignore_index=True)
        
        # Remove duplicates and sort
        full_df = full_df.drop_duplicates(subset=['time']).sort_values('time').reset_index(drop=True)
        
        # Convert timestamps from UTC to UTC+7 (Vietnam timezone)
        print("🌏 Converting timestamps from UTC to UTC+7...")
        full_df['time'] = full_df['time'] + timedelta(hours=7)
        
        print(f"✅ Combined {len(full_df)} total candles")
        print(f"   First: {full_df['time'].iloc[0]} (UTC+7)")
        print(f"   Last:  {full_df['time'].iloc[-1]} (UTC+7)")
        
        # Save to CSV if requested
        if save_to_csv:
            timeframe_name = {
                mt5.TIMEFRAME_M1: "M1",
                mt5.TIMEFRAME_M5: "M5", 
                mt5.TIMEFRAME_M15: "M15",
                mt5.TIMEFRAME_M30: "M30",
                mt5.TIMEFRAME_H1: "H1",
                mt5.TIMEFRAME_H4: "H4",
                mt5.TIMEFRAME_D1: "D1"
            }.get(timeframe, "Unknown")
            
            filename = f"{symbol}_{timeframe_name}_full_history.csv"
            full_df.to_csv(filename, index=False)
            print(f"✅ Saved to {filename}")
        
        return full_df
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None
    finally:
        mt5.shutdown()

def get_statistics(df):
    """Hiển thị thống kê data"""
    if df is None or len(df) == 0:
        return
    
    duration_days = (df['time'].iloc[-1] - df['time'].iloc[0]).days
    avg_candles_per_day = len(df) / max(duration_days, 1)
    
    print(f"\n📈 Statistics:")
    print(f"   Total candles: {len(df):,}")
    print(f"   Duration: {duration_days} days")
    print(f"   Avg candles/day: {avg_candles_per_day:.1f}")
    print(f"   Price range: {df['low'].min():.3f} - {df['high'].max():.3f}")
    print(f"   Latest price: {df['close'].iloc[-1]:.3f}")

# if __name__ == "__main__":
#     print("=" * 60)
#     print("=== FULL HISTORY CHUNKED RETRIEVAL ===")
#     print("=" * 60)
    
#     # Test với XAUUSDm M5
#     symbol = "XAUUSDm"
#     timeframe = mt5.TIMEFRAME_M5
    
#     print(f"\n🚀 Getting full history for {symbol} M5...")
#     full_data = get_full_history_chunked(symbol, timeframe, chunk_days=30)

#     print(f"full_data length: {len(full_data) if full_data is not None else 'None'}")

#     if full_data is not None:
#         get_statistics(full_data)
#     else:
#         print("❌ Failed to get data")