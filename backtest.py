import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

API_KEY = "YOUR_API_KEY"
START_DATE = "2025-10-24T12:00:00Z"
END_DATE = "2026-04-15T12:00:00Z"
INITIAL_BANKROLL = 1000.0

def american_to_decimal(odds):
    return (odds / 100) + 1 if odds > 0 else (100 / abs(odds)) + 1

def quarter_kelly_stake(win_prob, decimal_odds, bankroll):
    b = decimal_odds - 1
    p = win_prob
    q = 1 - p
    kelly_fraction = (b * p - q) / b
    return max(0, (kelly_fraction / 4) * bankroll)

def run_backtest():
    current_date = datetime.strptime(START_DATE, "%Y-%m-%dT%H:%M:%SZ")
    end_dt = datetime.strptime(END_DATE, "%Y-%m-%dT%H:%M:%SZ")
    
    bankroll = INITIAL_BANKROLL
    bet_history = []
    
    print("--- INITIATING 25-26 NBA BACKTEST ---")
    
    while current_date <= end_dt:
        date_str = current_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Call Historical API (requires paid tier)
        url = f"https://api.the-odds-api.com/v4/historical/sports/basketball_nba/odds?apiKey={API_KEY}&regions=us,eu&markets=h2h&date={date_str}"
        response = requests.get(url)
        
        if response.status_code != 200:
            current_date += timedelta(days=1)
            continue
            
        daily_bets = 0
        daily_profit = 0.0
        games = response.json().get('data', [])
        
        for game in games:
            # Logic identically mirrors production: Isolate Pinnacle, calculate True Prob, compare to Retail
            # (Simulation code abstracted here to match the historical JSON structure)
            
            # Assume we calculate a true_prob and find a retail_odds edge > 0:
            # Mock variables for structure representation:
            true_prob = np.random.uniform(0.45, 0.55) 
            retail_dec = 2.10
            ev_pct = (true_prob * retail_dec - 1) * 100
            
            if ev_pct > 0:
                stake = quarter_kelly_stake(true_prob, retail_dec, bankroll)
                if stake > 0:
                    # Mock win condition - replace with actual score resolution API
                    won_bet = np.random.random() < true_prob 
                    profit = (stake * (retail_dec - 1)) if won_bet else -stake
                    
                    bankroll += profit
                    daily_profit += profit
                    daily_bets += 1
                    
                    bet_history.append({
                        'Date': current_date.strftime("%Y-%m-%d"),
                        'EV_Pct': ev_pct,
                        'True_Prob': true_prob,
                        'Stake': stake,
                        'Profit': profit,
                        'Won': won_bet
                    })
                    
        if daily_bets > 0:
            print(f"[{current_date.strftime('%Y-%m-%d')}] Bets: {daily_bets} | Daily ROI: {((daily_profit/INITIAL_BANKROLL)*100):.2f}% | Bankroll: ${bankroll:.2f}")
            
        current_date += timedelta(days=1)
        
    df = pd.DataFrame(bet_history)
    
    print("\n===============================")
    print("     FINAL BACKTEST RESULTS    ")
    print("===============================")
    print(f"Total Bets: {len(df)}")
    print(f"Starting Bankroll: ${INITIAL_BANKROLL:.2f}")
    print(f"Final Bankroll: ${bankroll:.2f}")
    print(f"Total ROI: {(((bankroll - INITIAL_BANKROLL) / INITIAL_BANKROLL) * 100):.2f}%")
    
    # EV Percentage Buckets Analysis
    bins = [0, 2.0, 4.0, 6.0, np.inf]
    labels = ['0.0% - 2.0%', '2.0% - 4.0%', '4.0% - 6.0%', '6.0%+']
    df['EV_Bucket'] = pd.cut(df['EV_Pct'], bins=bins, labels=labels)
    
    bucket_summary = df.groupby('EV_Bucket', observed=False).agg(
        Total_Bets=('Profit', 'count'),
        Win_Rate=('Won', 'mean'),
        Total_Profit=('Profit', 'sum')
    )
    bucket_summary['Win_Rate'] = (bucket_summary['Win_Rate'] * 100).round(2).astype(str) + '%'
    bucket_summary['Total_Profit'] = bucket_summary['Total_Profit'].round(2)
    
    print("\n--- EV BUCKET PERFORMANCE ---")
    print(bucket_summary.to_string())

if __name__ == "__main__":
    run_backtest()
