import pandas as pd
import numpy as np

df = pd.read_csv(r'results/backtest/trade_history_xauusdm.csv')
df['Datetime_entry'] = pd.to_datetime(df['Datetime_entry'])
df['Profit'] = df['Profit'].astype(float)
df['Win'] = df['Win'].astype(str).str.strip().str.lower() == 'true'

total = len(df)
wins = int(df['Win'].sum())
losses = total - wins
win_rate = wins / total * 100

net_pnl = df['Profit'].sum()
gross_win = df[df['Profit'] > 0]['Profit'].sum()
gross_loss = abs(df[df['Profit'] < 0]['Profit'].sum())
profit_factor = gross_win / gross_loss if gross_loss > 0 else 0

avg_win = df[df['Win']]['Profit'].mean()
avg_loss = df[~df['Win']]['Profit'].mean()
best_trade = df['Profit'].max()
worst_trade = df['Profit'].min()

# Max Drawdown
cumulative = df['Profit'].cumsum()
roll_max = cumulative.cummax()
drawdown = cumulative - roll_max
max_drawdown = drawdown.min()

start = df['Datetime_entry'].min()
end = df['Datetime_entry'].max()
days = (end - start).days
avg_per_day = total / days if days > 0 else 0

roi = (net_pnl / 10000) * 100  # vs $10,000 initial

print(f"Date range     : {start.date()} to {end.date()} ({days} days)")
print(f"Total trades   : {total:,}")
print(f"Wins / Losses  : {wins:,} / {losses:,}")
print(f"Win rate       : {win_rate:.1f}%")
print(f"Net P/L        : ${net_pnl:,.2f}")
print(f"Gross Win      : ${gross_win:,.2f}")
print(f"Gross Loss     : ${gross_loss:,.2f}")
print(f"Profit Factor  : {profit_factor:.2f}")
print(f"Avg Win/trade  : ${avg_win:.2f}")
print(f"Avg Loss/trade : ${avg_loss:.2f}")
print(f"Best trade     : ${best_trade:.2f}")
print(f"Worst trade    : ${worst_trade:.2f}")
print(f"Max Drawdown   : ${max_drawdown:.2f}")
print(f"Avg trades/day : {avg_per_day:.1f}")
print(f"ROI (vs $10k)  : {roi:.1f}%")
