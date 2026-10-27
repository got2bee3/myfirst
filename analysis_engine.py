"""Historical analysis only. No model or database dependencies."""
import bisect
import csv
from datetime import date
from math import isfinite

TEAMS = {
 'ARI':'Arizona Cardinals','ATL':'Atlanta Falcons','BAL':'Baltimore Ravens',
 'BUF':'Buffalo Bills','CAR':'Carolina Panthers','CHI':'Chicago Bears',
 'CIN':'Cincinnati Bengals','CLE':'Cleveland Browns','DAL':'Dallas Cowboys',
 'DEN':'Denver Broncos','DET':'Detroit Lions','GB':'Green Bay Packers',
 'HOU':'Houston Texans','IND':'Indianapolis Colts','JAX':'Jacksonville Jaguars',
 'KC':'Kansas City Chiefs','LAC':'Los Angeles Chargers','LA':'Los Angeles Rams',
 'LV':'Las Vegas Raiders','MIA':'Miami Dolphins','MIN':'Minnesota Vikings',
 'NE':'New England Patriots','NO':'New Orleans Saints','NYG':'New York Giants',
 'NYJ':'New York Jets','PHI':'Philadelphia Eagles','PIT':'Pittsburgh Steelers',
 'SEA':'Seattle Seahawks','SF':'San Francisco 49ers','TB':'Tampa Bay Buccaneers',
 'TEN':'Tennessee Titans','WAS':'Washington Commanders'}
ALIASES = {'SD':'LAC','STL':'LA','LAR':'LA','OAK':'LV','WSH':'WAS'}
DEFAULT_CUTS = [-200,-150,0,150,200]


def number(value):
    try:
        n = float(value)
        return n if isfinite(n) else None
    except (ValueError, TypeError):
        return None


def price(value):
    n = number(value)
    return n if n is not None and abs(n) >= 100 and n == int(n) else None


def implied(ml):
    return -ml / (-ml+100) if ml < 0 else 100 / (ml+100)


def read_games(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        required = {'game_id','season','week','gameday','game_type','home_team','away_team','home_score','away_score','home_moneyline','away_moneyline'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Schedule file is missing required columns.')
        rows = list(reader)
    ids = set()
    for r in rows:
        if not r['game_id'] or r['game_id'] in ids:
            raise ValueError('Schedule file contains missing or duplicate game IDs.')
        ids.add(r['game_id'])
        home = ALIASES.get(r['home_team'], r['home_team'])
        away = ALIASES.get(r['away_team'], r['away_team'])
        if home not in TEAMS or away not in TEAMS or home == away:
            raise ValueError('Schedule file has invalid franchise mappings.')
        date.fromisoformat(r['gameday'])
        int(r['season']); int(r['week'])
        scores = [number(r['home_score']), number(r['away_score'])]
        if any(s is not None and (s < 0 or s != int(s)) for s in scores):
            raise ValueError('Schedule file has invalid scores.')
        if (scores[0] is None) != (scores[1] is None):
            raise ValueError('Schedule file has a partial final score.')
    return rows


def team_games(rows, team, today):
    result = []
    for r in rows:
        if int(r['season']) < 2010 or r['game_type'] not in {'REG','WC','DIV','CON','SB'}:
            continue
        home = ALIASES.get(r['home_team'], r['home_team'])
        away = ALIASES.get(r['away_team'], r['away_team'])
        if team not in (home, away):
            continue
        is_home = home == team
        side, other = ('home','away') if is_home else ('away','home')
        score, oppscore = number(r[f'{side}_score']), number(r[f'{other}_score'])
        complete = score is not None and oppscore is not None and r['gameday'] <= today
        ml, oppml = price(r[f'{side}_moneyline']), price(r[f'{other}_moneyline'])
        p = implied(ml)/(implied(ml)+implied(oppml)) if ml is not None and oppml is not None else None
        status = 'Unknown' if p is None else 'Favorite' if p > .5 else 'Underdog' if p < .5 else 'Even'
        outcome = 'Pending' if not complete else 'W' if score>oppscore else 'L' if score<oppscore else 'T'
        profit = None if outcome == 'Pending' or ml is None else 0 if outcome == 'T' else -10 if outcome == 'L' else 10*(100/-ml if ml<0 else ml/100)
        source_spread = number(r.get('spread_line'))
        spread = None if source_spread is None else -source_spread if is_home else source_spread
        spread_odds = price(r.get(f'{side}_spread_odds'))
        opponent_spread_odds = price(r.get(f'{other}_spread_odds'))
        adjusted_margin = None if not complete or spread is None else score-oppscore+spread
        spread_result = 'Pending' if not complete else 'Unknown' if adjusted_margin is None else 'Cover' if adjusted_margin>0 else 'No cover' if adjusted_margin<0 else 'Push'
        spread_profit = None if spread_result in {'Pending','Unknown'} or spread_odds is None else 0 if spread_result=='Push' else -10 if spread_result=='No cover' else 10*(100/-spread_odds if spread_odds<0 else spread_odds/100)
        spread_probability = implied(spread_odds)/(implied(spread_odds)+implied(opponent_spread_odds)) if spread_odds is not None and opponent_spread_odds is not None else None
        spread_status = 'Unknown' if spread is None else 'Favorite' if spread<0 else 'Underdog' if spread>0 else 'Even'
        result.append(dict(game_id=r['game_id'],season=int(r['season']),week=int(r['week']),date=r['gameday'],game_type=r['game_type'],
            opponent=r[f'{other}_team'],venue='Home' if is_home else 'Away',score=score,opponent_score=oppscore,
            moneyline=ml,opponent_moneyline=oppml,market_probability=p,market_status=status,result=outcome,profit=profit,
            team_spread=spread,opponent_spread=None if spread is None else -spread,spread_odds=spread_odds,
            opponent_spread_odds=opponent_spread_odds,spread_status=spread_status,spread_result=spread_result,
            spread_profit=spread_profit,spread_market_probability=spread_probability))
    return sorted(result,key=lambda r:(r['date'],r['game_id']))


def summarize(games, market='moneyline'):
    completed = [g for g in games if g['result']!='Pending']
    odds_key,outcome_key,profit_key,probability_key = ('spread_odds','spread_result','spread_profit','spread_market_probability') if market=='spread' else ('moneyline','result','profit','market_probability')
    win,loss,void = ('Cover','No cover','Push') if market=='spread' else ('W','L','T')
    assessable = [g for g in completed if market!='spread' or g['team_spread'] is not None]
    priced = [g for g in assessable if g[odds_key] is not None]
    settled = [g for g in priced if g[outcome_key] in {win,loss}]
    paired = [g for g in settled if g[probability_key] is not None]
    profit = sum(g[profit_key] for g in priced)
    stake = len(settled)*10
    return dict(games=len(completed),pending=len(games)-len(completed),bets=len(settled),voids=sum(g[outcome_key]==void for g in priced),
        wins=sum(g[outcome_key]==win for g in settled),losses=sum(g[outcome_key]==loss for g in settled),profit=profit,stake=stake,
        roi=profit/stake if stake else None,missing_odds=sum(g[odds_key] is None for g in assessable),
        missing_pairs=sum(g[probability_key] is None for g in assessable),missing_lines=len(completed)-len(assessable),
        assessed_wins=sum(g[outcome_key]==win for g in assessable),assessed_losses=sum(g[outcome_key]==loss for g in assessable),assessed_voids=sum(g[outcome_key]==void for g in assessable),
        expected_wins=sum(g[probability_key] for g in paired),observed_wins=sum(g[outcome_key]==win for g in paired),paired_games=len(paired))


def split_filter(games, selection, market='moneyline'):
    if selection=='all': return list(games)
    label={'favorites':'Favorite','underdogs':'Underdog'}[selection]
    return [g for g in games if g['spread_status' if market=='spread' else 'market_status']==label]


def price_bands(games, cuts):
    groups=[[] for _ in range(6)]
    for g in games:
        if g['moneyline'] is not None: groups[bisect.bisect_left(cuts,g['moneyline'])].append(g)
    labels=[f'ML ≤ {cuts[0]:+g}']+[f'{cuts[i-1]:+g} < ML ≤ {cuts[i]:+g}' for i in range(1,5)]+[f'ML > {cuts[-1]:+g}']
    return [(label,summarize(group)) for label,group in zip(labels,groups)]
