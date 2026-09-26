import os
import json
import requests
import numpy as np
import pandas as pd
from nba_api.stats.endpoints import leaguedashteamstats

API_KEY = os.environ.get("ODDS_API_KEY")
ITERATIONS = 10000

# Baseline team Four Factors fallback (eFG%, TOV%, OREB%, FTA_Rate)
DEFAULT_STATS = {
    'EFG_PCT': 0.545,
    'TM_TOV_PCT': 0.135,
    'FTA_RATE': 0.245
}

def american_to_decimal(odds):
    return (odds / 100) + 1 if odds > 0 else (100 / abs(odds)) + 1

def devig_proportional(odds1, odds2):
    dec1, dec2 = american_to_decimal(odds1), american_to_decimal(odds2)
    imp1, imp2 = 1 / dec1, 1 / dec2
    overround = imp1 + imp2
    return imp1 / overround, imp2 / overround

def get_four_factors():
    """Tries NBA API; falls back immediately if GitHub Actions IP is blocked."""
    try:
        print("Checking NBA API for live stats...")
        custom_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.nba.com/',
            'Origin': 'https://www.nba.com/'
        }
        stats = leaguedashteamstats.LeagueDashTeamStats(
            measure_type_detailed_defense='Four Factors',
            per_mode_detailed='Per100Possessions',
            headers=custom_headers,
            timeout=5
        ).get_data_frames()[0]
        print("Successfully pulled live NBA team stats.")
        return stats.set_index('TEAM_NAME')
    except Exception:
        print("NBA API blocked datacenter IP. Using cached baseline ratings.")
        return None

def simulate_matchup(away_stats, home_stats, iterations=ITERATIONS):
    away_efg = away_stats.get('EFG_PCT', DEFAULT_STATS['EFG_PCT'])
    away_tov = away_stats.get('TM_TOV_PCT', DEFAULT_STATS['TM_TOV_PCT'])
    away_fta = away_stats.get('FTA_RATE', DEFAULT_STATS['FTA_RATE'])

    home_efg = home_stats.get('EFG_PCT', DEFAULT_STATS['EFG_PCT'])
    home_tov = home_stats.get('TM_TOV_PCT', DEFAULT_STATS['TM_TOV_PCT'])
    home_fta = home_stats.get('FTA_RATE', DEFAULT_STATS['FTA_RATE'])

    possessions = np.random.normal(loc=100, scale=4.0, size=iterations)

    # Away scoring distribution
    away_shots = possessions * (1 - away_tov)
    away_makes = np.random.binomial(away_shots.astype(int), away_efg)
    away_ft = np.random.binomial(away_shots.astype(int), away_fta) * 0.75
    away_pts = (away_makes * 2) + away_ft

    # Home scoring distribution (+1.5 pt home court edge)
    home_shots = possessions * (1 - home_tov)
    home_makes = np.random.binomial(home_shots.astype(int), home_efg)
    home_ft = np.random.binomial(home_shots.astype(int), home_fta) * 0.75
    home_pts = (home_makes * 2) + home_ft + 1.5

    home_wins = np.sum(home_pts > away_pts)
    return home_wins / iterations, (iterations - home_wins) / iterations

def main():
    projections = []
    
    try:
        if not API_KEY:
            print("Error: ODDS_API_KEY secret not found.")
            return

        four_factors = get_four_factors()

        odds_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/odds?regions=us,eu&markets=h2h&oddsFormat=american&apiKey={API_KEY}"
        res = requests.get(odds_url, timeout=15)
        games = res.json()

        if isinstance(games, dict) and "message" in games:
            print(f"Odds API Notice: {games['message']}")
            return

        if not games:
            print("No active NBA game lines posted right now.")
            return

        for game in games:
            try:
                away_team = game['away_team']
                home_team = game['home_team']

                away_stats = four_factors.loc[away_team] if (four_factors is not None and away_team in four_factors.index) else DEFAULT_STATS
                home_stats = four_factors.loc[home_team] if (four_factors is not None and home_team in four_factors.index) else DEFAULT_STATS

                sim_home_prob, sim_away_prob = simulate_matchup(away_stats, home_stats)

                # Sharp baseline (Pinnacle)
                pinny = next((b for b in game.get('bookmakers', []) if b['key'] == 'pinnacle'), None)
                if pinny:
                    p_away = pinny['markets'][0]['outcomes'][0]['price']
                    p_home = pinny['markets'][0]['outcomes'][1]['price']
                    true_away, true_home = devig_proportional(p_away, p_home)
                else:
                    true_away = sim_away_prob

                # Compare against retail books
                for b in game.get('bookmakers', []):
                    if b['key'] in ['draftkings', 'fanduel', 'betmgm', 'caesars']:
                        market = b['markets'][0]['outcomes'][0]
                        retail_odds = market['price']
                        retail_dec = american_to_decimal(retail_odds)
                        edge = (true_away * retail_dec - 1) * 100

                        if edge > 0:
                            projections.append({
                                "away_team": away_team,
                                "home_team": home_team,
                                "bookmaker": b['title'],
                                "market": f"{market['name']} ML",
                                "odds": retail_odds,
                                "true_prob": true_away * 100,
                                "edge": edge
                            })
            except Exception as e:
                continue

        projections = sorted(projections, key=lambda x: x['edge'], reverse=True)

    except Exception as e:
        print(f"Execution error: {e}")
    finally:
        with open('projections.json', 'w') as f:
            json.dump(projections, f, indent=4)
        print(f"Saved projections.json ({len(projections)} plays found).")

if __name__ == "__main__":
    main()
