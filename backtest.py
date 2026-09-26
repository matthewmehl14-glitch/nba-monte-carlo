import requests
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
from nba_api.stats.endpoints import scoreboardv2

API_KEY = "YOUR_API_KEY"
START_DATE = "2025-10-24T12:00:00Z"
END_DATE = "2026-04-15T12:00:00Z"
INITIAL_BANKROLL = 1000.0
FLAT_BET_AMOUNT = 25.0

def american_to_decimal(odds):
    return (odds / 100) + 1 if odds > 0 else (100 / abs(odds)) + 1

def run_backtest():
    current_date = datetime.strptime(START_DATE, "%Y-%m-%dT%H:%M:%SZ")
    end_dt = datetime.strptime(END_DATE, "%Y-%m-%dT%H:%M:%SZ")
    
    bankroll = INITIAL_BANKROLL
    total_wagered = 0.0
    bet_history = []
    
    # Spoof a standard web browser to bypass the NBA's anti-scraping blocks
    custom_headers = {
        'Host': 'stats.nba.com',
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Referer': 'https://www.nba.com/',
        'Origin': 'https://www.nba.com/',
    }
    
    print("--- INITIATING 25-26 NBA BACKTEST WITH REAL BOX SCORES ---")
    print("Note: This will take a few minutes to run. A 2-second delay is added between dates to prevent IP bans.\n")
    
    while current_date <= end_dt:
        date_str = current_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        nba_date_str = current_date.strftime("%Y-%m-%d")
        
        # 1. Fetch Historical Odds (Requires Paid Tier)
        url = f"https://api.the-odds-api.com/v4/historical/sports/basketball_nba/odds?apiKey={API_KEY}&regions=us,eu&markets=h2h&date={date_str}"
        response = requests.get(url)
        
        if response.status_code != 200:
            current_date += timedelta(days=1)
            continue
            
        games = response.json().get('data', [])
        if not games:
            print(f"[{nba_date_str}] No historical odds found.")
            current_date += timedelta(days=1)
            continue
            
        # 2. Fetch Actual Game Scores for this Date from NBA API
        try:
            board = scoreboardv2.ScoreboardV2(game_date=nba_date_str, headers=custom_headers, timeout=30)
            line_scores = board.line_score.get_data_frame()
            time.sleep(2) # Mandatory pause to protect your IP
        except Exception as e:
            print(f"[{nba_date_str}] Skipped: NBA API blocked or failed ({e})")
            current_date += timedelta(days=1)
            continue
            
        if line_scores.empty:
            print(f"[{nba_date_str}] No NBA games scheduled.")
            current_date += timedelta(days=1)
            continue
            
        daily_bets = 0
        daily_profit = 0.0
        
        # 3. Process Each Game
        for game in games:
            away_team = game['away_team']
            home_team = game['home_team']
            
            # Extract mascot to match with the NBA API's TEAM_NAME field (e.g., "Lakers" matches "Los Angeles Lakers")
            away_mascot = away_team.split(" ")[-1]
            home_mascot = home_team.split(" ")[-1]
            
            try:
                # Search the daily box score for the teams involved in the Odds API line
                away_score_row = line_scores[line_scores['TEAM_NAME'].str.contains(away_mascot, case=False, na=False)]
                home_score_row = line_scores[line_scores['TEAM_NAME'].str.contains(home_mascot, case=False, na=False)]
                
                if away_score_row.empty or home_score_row.empty:
                    continue # Team didn't play or name mismatch
                    
                away_pts = float(away_score_row.iloc[0]['PTS'])
                home_pts = float(home_score_row.iloc[0]['PTS'])
                
                if pd.isna(away_pts) or pd.isna(home_pts):
                    continue # Game was cancelled or hasn't finished
                    
                # We have the real final score:
                actual_away_won = (away_pts > home_pts)
                
            except Exception:
                continue # Skip on data parsing errors
            
            # --- Betting & Simulation Logic ---
            # NOTE: For the actual live backtest, this is where you insert the Python simulation 
            # logic from generate_projections.py to calculate true_prob using historical team stats.
            # We mock the simulation output here so you can test the grading engine framework immediately.
            
            true_prob_away = np.random.uniform(0.45, 0.55) # Replace with: sim_away_win_prob
            retail_dec = 2.10 # Replace with: american_to_decimal(retail_away_odds)
            
            ev_pct = (true_prob_away * retail_dec - 1) * 100
            
            if ev_pct > 0:
                stake = FLAT_BET_AMOUNT
                
                # Grade the bet using the ACTUAL box score result we just scraped
                won_bet = actual_away_won 
                profit = (stake * (retail_dec - 1)) if won_bet else -stake
                
                bankroll += profit
                total_wagered += stake
                daily_profit += profit
                daily_bets += 1
                
                bet_history.append({
                    'Date': nba_date_str,
                    'Matchup': f"{away_team} @ {home_team}",
                    'Score': f"{int(away_pts)} - {int(home_pts)}",
                    'EV_Pct': ev_pct,
                    'True_Prob': true_prob_away,
                    'Stake': stake,
                    'Profit': profit,
                    'Won': won_bet
                })
                    
        if daily_bets > 0:
            print(f"[{nba_date_str}] Scrape successful. Bets: {daily_bets} | Daily Profit: ${daily_profit:.2f} | Bankroll: ${bankroll:.2f}")
        else:
            print(f"[{nba_date_str}] Scrape successful. No +EV bets found.")
            
        current_date += timedelta(days=1)
        
    df = pd.DataFrame(bet_history)
    
    print("\n===============================")
    print("     FINAL BACKTEST RESULTS    ")
    print("===============================")
    if df.empty:
        print("No bets were placed during this timeframe.")
        return
        
    print(f"Total Bets: {len(df)}")
    print(f"Flat Bet Size: ${FLAT_BET_AMOUNT:.2f}")
    print(f"Total Risked: ${total_wagered:.2f}")
    print(f"Starting Bankroll: ${INITIAL_BANKROLL:.2f}")
    print(f"Final Bankroll: ${bankroll:.2f}")
    
    total_profit = bankroll - INITIAL_BANKROLL
    print(f"Total Net Profit: ${total_profit:.2f}")
    
    if total_wagered > 0:
        print(f"ROI (Profit / Total Risked): {((total_profit / total_wagered) * 100):.2f}%")
    
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
