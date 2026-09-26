import os
import json
import requests
import numpy as np
import pandas as pd
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

# --- 2. FETCH FOUR FACTORS (NBA API) ---
def get_four_factors():
    stats = leaguedashteamstats.LeagueDashTeamStats(
        measure_type_detailed_defense='Four Factors',
        per_mode_detailed='Per100Possessions'
    ).get_data_frames()[0]
    return stats.set_index('TEAM_NAME')

# --- 3. VECTORIZED MONTE CARLO ---
def simulate_matchup(away_stats, home_stats, iterations=ITERATIONS):
    # Base possessions scaled by pace
    possessions = np.random.normal(loc=100, scale=4.0, size=iterations)
    
    # Simulate Away Points based on eFG% and FTRate distributions
    away_shots = possessions * (1 - away_stats['TM_TOV_PCT'])
    away_makes = np.random.binomial(away_shots.astype(int), away_stats['EFG_PCT'])
    away_ft_pts = np.random.binomial(away_shots.astype(int), away_stats['FTA_RATE']) * 0.75
    away_pts = (away_makes * 2) + away_ft_pts
    
    # Simulate Home Points
    home_shots = possessions * (1 - home_stats['TM_TOV_PCT'])
    home_makes = np.random.binomial(home_shots.astype(int), home_stats['EFG_PCT'])
    home_ft_pts = np.random.binomial(home_shots.astype(int), home_stats['FTA_RATE']) * 0.75
    home_pts = (home_makes * 2) + home_ft_pts
    
    home_wins = np.sum(home_pts > away_pts)
    return home_wins / iterations, (iterations - home_wins) / iterations

# --- 4. EXECUTE & OUTPUT ---
def main():
    four_factors = get_four_factors()
    
    # Pull odds from Odds API (US market + Pinnacle benchmarking)
    odds_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/odds?regions=us,eu&markets=h2h&oddsFormat=american&apiKey={API_KEY}"
    games = requests.get(odds_url).json()
    
    projections = []
    
    for game in games:
        try:
            away_team = game['away_team']
            home_team = game['home_team']
            
            # Isolate Pinnacle for Sharp Baseline
            pinny_market = next((b for b in game['bookmakers'] if b['key'] == 'pinnacle'), None)
            if not pinny_market: continue
            
            pinny_away_odds = pinny_market['markets'][0]['outcomes'][0]['price']
            pinny_home_odds = pinny_market['markets'][0]['outcomes'][1]['price']
            true_away, true_home = devig_proportional(pinny_away_odds, pinny_home_odds)
            
            # Find Retail Discrepancies (DraftKings/FanDuel)
            retail_book = next((b for b in game['bookmakers'] if b['key'] in ['draftkings', 'fanduel']), None)
            if not retail_book: continue
            
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
            continue
            
    # Sort by highest edge and save to JSON
    projections = sorted(projections, key=lambda x: x['edge'], reverse=True)
    with open('projections.json', 'w') as f:
        json.dump(projections, f, indent=4)

if __name__ == "__main__":
    main()
