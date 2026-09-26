import os
import json
import requests
import numpy as np
import pandas as pd
import time
from nba_api.stats.endpoints import leaguedashteamstats

# --- 1. SETUP & UTILS ---
API_KEY = os.environ.get("ODDS_API_KEY")
ITERATIONS = 10000

def american_to_decimal(odds):
    if odds > 0:
        return (odds / 100) + 1
    else:
        return (100 / abs(odds)) + 1

def devig_proportional(odds1, odds2):
    dec1, dec2 = american_to_decimal(odds1), american_to_decimal(odds2)
    imp1, imp2 = 1 / dec1, 1 / dec2
    overround = imp1 + imp2
    return imp1 / overround, imp2 / overround

# --- 2. FETCH FOUR FACTORS (NBA API) WITH RETRIES ---
def get_four_factors(max_retries=3):
    # Official recommendation from nba_api docs to spoof a standard browser
    custom_headers = {
        'Host': 'stats.nba.com',
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.nba.com/',
        'Origin': 'https://www.nba.com/',
        'x-nba-stats-origin': 'stats',
        'x-nba-stats-token': 'true',
    }

    for attempt in range(max_retries):
        try:
            print(f"Fetching NBA stats, attempt {attempt + 1}...")
            stats = leaguedashteamstats.LeagueDashTeamStats(
                measure_type_detailed_defense='Four Factors',
                per_mode_detailed='Per100Possessions',
                headers=custom_headers,
                timeout=120
            ).get_data_frames()[0]
            return stats.set_index('TEAM_NAME')
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                print("Sleeping for 10 seconds before retrying to bypass NBA rate limits...")
                time.sleep(10)
            else:
                raise Exception("NBA API blocked the request from GitHub Actions IP.")

# --- 3. VECTORIZED MONTE CARLO ---
def simulate_matchup(away_stats, home_stats, iterations=ITERATIONS):
    # Fallback default values if team stats are missing slightly
    away_tov = away_stats.get('TM_TOV_PCT', 0.15)
    away_efg = away_stats.get('EFG_PCT', 0.54)
    away_fta = away_stats.get('FTA_RATE', 0.25)
    
    home_tov = home_stats.get('TM_TOV_PCT', 0.15)
    home_efg = home_stats.get('EFG_PCT', 0.54)
    home_fta = home_stats.get('FTA_RATE', 0.25)

    # Base possessions scaled by pace
    possessions = np.random.normal(loc=100, scale=4.0, size=iterations)
    
    # Simulate Away Points based on eFG% and FTRate distributions
    away_shots = possessions * (1 - away_tov)
    away_makes = np.random.binomial(away_shots.astype(int), away_efg)
    away_ft_pts = np.random.binomial(away_shots.astype(int), away_fta) * 0.75
    away_pts = (away_makes * 2) + away_ft_pts
    
    # Simulate Home Points
    home_shots = possessions * (1 - home_tov)
    home_makes = np.random.binomial(home_shots.astype(int), home_efg)
    home_ft_pts = np.random.binomial(home_shots.astype(int), home_fta) * 0.75
    home_pts = (home_makes * 2) + home_ft_pts
    
    home_wins = np.sum(home_pts > away_pts)
    return home_wins / iterations, (iterations - home_wins) / iterations

# --- 4. EXECUTE & OUTPUT ---
def main():
    try:
        four_factors = get_four_factors()
    except Exception as e:
        print(f"Stats failure: {e}")
        return # Exit gracefully so the workflow doesn't throw a raw code error
    
    if not API_KEY:
        print("Error: ODDS_API_KEY environment variable not found in GitHub Secrets.")
        return

    # Pull odds from Odds API (US market + Pinnacle benchmarking)
    odds_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/odds?regions=us,eu&markets=h2h&oddsFormat=american&apiKey={API_KEY}"
    try:
        games = requests.get(odds_url, timeout=30).json()
    except Exception as e:
        print(f"Failed to fetch from Odds API: {e}")
        return
        
    if isinstance(games, dict) and "message" in games: 
        print(f"Odds API Error: {games['message']}")
        return
    
    projections = []
    
    for game in games:
        try:
            away_team = game['away_team']
            home_team = game['home_team']
            
            # Standardize names between the two APIs
            away_lookup = away_team.replace("Los Angeles Clippers", "LA Clippers")
            home_lookup = home_team.replace("Los Angeles Clippers", "LA Clippers")
            
            if away_lookup not in four_factors.index or home_lookup not in four_factors.index:
                continue
                
            away_stats = four_factors.loc[away_lookup]
            home_stats = four_factors.loc[home_lookup]
            
            # Run simulation
            sim_away_win_prob, sim_home_win_prob = simulate_matchup(away_stats, home_stats)
            
            # Isolate Pinnacle for Sharp Baseline
            pinny_market = next((b for b in game['bookmakers'] if b['key'] == 'pinnacle'), None)
            
            if pinny_market:
                pinny_away_odds = pinny_market['markets'][0]['outcomes'][0]['price']
                pinny_home_odds = pinny_market['markets'][0]['outcomes'][1]['price']
                true_away, true_home = devig_proportional(pinny_away_odds, pinny_home_odds)
            else:
                # If pinnacle hasn't released a line, default purely to the simulation
                true_away = sim_away_win_prob
            
            # Find Retail Discrepancies
            retail_books = [b for b in game['bookmakers'] if b['key'] in ['draftkings', 'fanduel', 'betmgm', 'caesars']]
            for retail_book in retail_books:
                retail_away_odds = retail_book['markets'][0]['outcomes'][0]['price']
                retail_away_dec = american_to_decimal(retail_away_odds)
                
                # EV Calculation
                ev_pct = (true_away * retail_away_dec - 1) * 100
                
                if ev_pct > 0:
                    projections.append({
                        "away_team": away_team,
                        "home_team": home_team,
                        "bookmaker": retail_book['title'],
                        "market": f"{away_team} ML",
                        "odds": retail_away_odds,
                        "true_prob": true_away * 100,
                        "edge": ev_pct
                    })
        except Exception as e:
            print(f"Error processing {game.get('away_team')} vs {game.get('home_team')}: {e}")
            continue
            
    # Sort by highest edge and save to JSON
    projections = sorted(projections, key=lambda x: x['edge'], reverse=True)
    with open('projections.json', 'w') as f:
        json.dump(projections, f, indent=4)
        
    print(f"Generated {len(projections)} +EV projections successfully.")

if __name__ == "__main__":
    main()
