"""One run, 32 franchises, both markets; no MySQL or prediction model access."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import urllib.request
import zipfile
from zoneinfo import ZoneInfo
from analysis_engine import TEAMS, ALIASES, number, price, implied, team_games, summarize, split_filter

ROOT=Path(__file__).resolve().parent
SOURCE='https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv'
GROUPS={
 ('AFC','East'):['BUF','MIA','NE','NYJ'],('AFC','North'):['BAL','CIN','CLE','PIT'],
 ('AFC','South'):['HOU','IND','JAX','TEN'],('AFC','West'):['DEN','KC','LAC','LV'],
 ('NFC','East'):['DAL','NYG','PHI','WAS'],('NFC','North'):['CHI','DET','GB','MIN'],
 ('NFC','South'):['ATL','CAR','NO','TB'],('NFC','West'):['ARI','LA','SF','SEA']}
ALIGNMENT={team:(conf,div) for (conf,div),teams in GROUPS.items() for team in teams}
METRICS=['games','pending','bets_placed','bets','wins','losses','voids','pushes','placed_stakes',
 'refunded_stakes','stake','profit','roi_percent','missing_odds','missing_lines','missing_pairs',
 'assessed_wins','assessed_losses','assessed_voids','expected_wins','observed_wins','paired_games']
SPLITS=['all','favorites','underdogs','even','unknown','home','away','regular','playoffs']


def fresh_source():
    with urllib.request.urlopen(SOURCE,timeout=45) as response:
        content=response.read(8_000_001)
    if len(content)>8_000_000: raise ValueError('Source download exceeds size limit.')
    return content,dict(source_url=SOURCE,retrieved_at_utc=datetime.now(timezone.utc).isoformat(),fresh_download=True)


def insert(conn,table,row):
    keys=list(row)
    conn.execute(f'INSERT INTO {table} ({",".join(keys)}) VALUES ({",".join("?" for _ in keys)})',list(row.values()))


def market_metadata(row,market,side):
    def get(field):
        return row.get(f'{side}_{market}_{field}') or row.get(f'{market}_{field}') or row.get(field) or None
    label=get('source_type')
    types={'actual_historical_sportsbook_quote','estimated_reference_price','other','unknown'}
    return dict(source_type=label if label in types else 'other' if label else 'unknown',
                source_type_raw=label,data_source='nflverse',original_odds_source=get('original_odds_source'),
                sportsbook=get('sportsbook'),odds_timestamp=get('odds_timestamp'),
                price_timing=get('price_timing') or 'unknown',verification_status='not_independently_verified')


def subset(games,split,market):
    if split in {'all','favorites','underdogs'}: return split_filter(games,split,market)
    if split in {'even','unknown'}:
        key='spread_status' if market=='spread' else 'market_status'
        return [g for g in games if g[key]==split.title()]
    if split in {'home','away'}: return [g for g in games if g['venue'].lower()==split]
    return [g for g in games if (g['game_type']=='REG')==(split=='regular')]


def summary_stats(games,market):
    s=summarize(games,market)
    key=market+'_'
    s.update(bets_placed=sum(g[key+'placed_stake']>0 for g in games),
             pushes=s['voids'] if market=='spread' else 0,
             placed_stakes=sum(g[key+'placed_stake'] for g in games),
             refunded_stakes=sum(g[key+'refunded_stake'] for g in games),
             roi_percent=None if s['roi'] is None else s['roi']*100)
    s.pop('roi')
    return s


def build_archive(content,source_metadata=None,as_of=None):
    """Return (ZIP bytes, filename, metadata); always report source discrepancies."""
    now=datetime.now(timezone.utc)
    as_of=as_of or datetime.now(ZoneInfo('America/New_York')).date()
    if isinstance(as_of,str): as_of=date.fromisoformat(as_of)
    current_season=as_of.year if as_of.month>=3 else as_of.year-1
    source_metadata=source_metadata or {}
    schema=(ROOT/'research_schema.sql').read_text()
    issues=[];checks=[]
    def issue(severity,code,gid=None,row=None,**details):
        issues.append(dict(severity=severity,code=code,game_id=gid,source_row=row,details_json=json.dumps(details)))
    def check(name,passed,**details):
        checks.append(dict(name=name,status='passed' if passed else 'failed',details_json=json.dumps(details)))
    reader=csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
    required={'game_id','season','week','gameday','game_type','home_team','away_team','home_score','away_score'}
    missing=required-set(reader.fieldnames or [])
    if missing: issue('error','missing_required_columns',missing=sorted(missing))
    candidates=[]
    out_of_scope=0
    for lineno,row in enumerate(reader,2):
        if missing: continue
        try: season=int(row['season'])
        except (ValueError,TypeError):
            issue('error','invalid_season',row=lineno,raw=row);continue
        if not 2010<=season<=current_season or row['game_type'] not in {'REG','WC','DIV','CON','SB'}:
            out_of_scope+=1;continue
        candidates.append((lineno,row))
    counts=Counter(row['game_id'] for _,row in candidates)
    accepted=[]
    for lineno,original in candidates:
        row=dict(original)
        gid=row['game_id']
        if not gid or counts[gid]!=1:
            issue('error','duplicate_or_missing_game_id',gid,lineno,occurrences=counts[gid],raw=original);continue
        home=ALIASES.get(row['home_team'],row['home_team']);away=ALIASES.get(row['away_team'],row['away_team'])
        try:
            day=date.fromisoformat(row['gameday']);week=int(row['week'])
            if week<1 or week>30: raise ValueError('week')
        except (ValueError,TypeError):
            issue('error','invalid_date_or_week',gid,lineno,raw=original);continue
        if home not in TEAMS or away not in TEAMS or home==away:
            issue('error','invalid_franchise',gid,lineno,raw=original);continue
        hs,aws=number(row['home_score']),number(row['away_score'])
        invalid_scores=any(row[k] not in ('',None) and (number(row[k]) is None or number(row[k])<0 or not number(row[k]).is_integer()) for k in ['home_score','away_score'])
        partial=(hs is None)!=(aws is None)
        status='future' if day>as_of else 'completed' if hs is not None and aws is not None else 'incomplete'
        if invalid_scores or partial:
            status='discrepant';issue('error','invalid_or_partial_scores',gid,lineno,raw=original)
        if day>as_of and (hs is not None or aws is not None):
            issue('warning','future_game_has_scores',gid,lineno,raw=original)
        if hs is not None and aws is not None and row.get('result') not in ('',None):
            if number(row['result']) is None or abs(number(row['result'])-(hs-aws))>1e-8:
                status='discrepant';issue('error','source_result_disagrees_with_scores',gid,lineno,raw=original)
        for field in ['home_moneyline','away_moneyline','home_spread_odds','away_spread_odds']:
            row.setdefault(field,'')
            if row[field] not in ('',None) and price(row[field]) is None:
                issue('warning','invalid_american_odds',gid,lineno,field=field,raw_value=row[field])
        if row.get('spread_line') not in ('',None) and number(row['spread_line']) is None:
            issue('warning','invalid_spread_line',gid,lineno,raw_value=row['spread_line'])
        confh,divh=ALIGNMENT[home];confa,diva=ALIGNMENT[away]
        divisional=int((confh,divh)==(confa,diva));intraconference=int(confh==confa)
        if row.get('div_game') not in ('',None) and number(row['div_game'])!=divisional:
            issue('warning','source_division_flag_mismatch',gid,lineno,raw_value=row['div_game'],calculated=divisional)
        accepted.append((lineno,original,row,home,away,status,hs,aws,divisional,intraconference))
    all_team_games=defaultdict(list)
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp)
        conn=sqlite3.connect(folder/'nfl_research.sqlite')
        try:
            conn.executescript(schema)
            for team,name in TEAMS.items():
                conf,div=ALIGNMENT[team]
                insert(conn,'teams',dict(team=team,franchise_name=name,conference=conf,division=div,
                    historical_aliases_json=json.dumps([team]+[alias for alias,canonical in ALIASES.items() if canonical==team])))
            digest=hashlib.sha256(content).hexdigest()
            insert(conn,'source_files',dict(source_id=1,source_url=source_metadata.get('source_url',SOURCE),
                retrieved_at_utc=source_metadata.get('retrieved_at_utc'),sha256=digest,raw_csv=content))
            for lineno,original,row,home,away,status,hs,aws,divisional,intra in accepted:
                gid=row['game_id']
                insert(conn,'games',dict(game_id=gid,source_id=1,source_row=lineno,season=int(row['season']),week=int(row['week']),
                    game_date=row['gameday'],game_type=row['game_type'],is_playoff=int(row['game_type']!='REG'),status=status,
                    home_team=home,away_team=away,home_abbreviation_raw=row['home_team'],away_abbreviation_raw=row['away_team'],
                    home_score=hs,away_score=aws,home_moneyline_raw=original.get('home_moneyline'),away_moneyline_raw=original.get('away_moneyline'),
                    spread_line_raw=original.get('spread_line'),home_spread_odds_raw=original.get('home_spread_odds'),away_spread_odds_raw=original.get('away_spread_odds'),
                    is_divisional=divisional,is_intraconference=intra,is_interconference=1-intra,raw_json=json.dumps(original)))
                for market in ['moneyline','spread']:
                    for side in ['home','away']:
                        field=f'{side}_'+('moneyline' if market=='moneyline' else 'spread_odds')
                        insert(conn,'market_quotes',dict(game_id=gid,market=market,side=side,price_raw=original.get(field),
                            american_odds=price(row.get(field)),**market_metadata(original,market,side)))
                for team,opponent in [(home,away),(away,home)]:
                    g=team_games([row],team,as_of.isoformat())[0]
                    g.update(team=team,opponent=opponent,game_status=status,is_divisional=divisional,is_intraconference=intra,is_interconference=1-intra)
                    if status!='completed':
                        g.update(result='Pending',spread_result='Pending',profit=None,spread_profit=None)
                    g.update(moneyline_available=int(g['moneyline'] is not None),moneyline_pair_available=int(g['market_probability'] is not None),
                        spread_line_available=int(g['team_spread'] is not None),spread_available=int(g['team_spread'] is not None and g['spread_odds'] is not None),
                        spread_pair_available=int(g['team_spread'] is not None and g['spread_market_probability'] is not None),
                        moneyline_implied_probability=None if g['moneyline'] is None else implied(g['moneyline']),
                        spread_implied_probability=None if g['spread_odds'] is None else implied(g['spread_odds']))
                    for market,odds_key,result_key,profit_key,win,loss,void in [
                        ('moneyline','moneyline','result','profit','W','L','T'),('spread','spread_odds','spread_result','spread_profit','Cover','No cover','Push')]:
                        available=g[market+'_available']
                        settled=status=='completed' and available
                        outcome=g[result_key]
                        bet_status='pending' if status!='completed' else 'unavailable' if not available else 'won' if outcome==win else 'lost' if outcome==loss else 'void'
                        refund=10 if settled and outcome==void else 0
                        placed=10 if settled else 0
                        g.update({market+'_bet_status':bet_status,market+'_placed_stake':placed,market+'_refunded_stake':refund,
                            market+'_settled_stake':placed-refund,market+'_gross_return':None if not settled else placed+g[profit_key]})
                    insert(conn,'team_games',g)
                    all_team_games[team].append(g)
            # Validate independent identities, symmetry and payout arithmetic; retain discrepancies.
            check('exactly_32_franchises',len(TEAMS)==32 and len(all_team_games)==32,represented=len(all_team_games),expected=32)
            check('unique_source_game_identifiers',all(count==1 and bool(gid) for gid,count in counts.items()),duplicate_ids=[gid for gid,n in counts.items() if n>1])
            paired=defaultdict(list)
            for group in all_team_games.values():
                for g in group: paired[g['game_id']].append(g)
            mismatches=defaultdict(list)
            raw_by_id={item[2]['game_id']:item[2] for item in accepted}
            for gid,pair in paired.items():
                if len(pair)!=2:
                    mismatches['two_sides_per_game'].append(gid);continue
                a,b=pair
                if a['opponent']!=b['team'] or b['opponent']!=a['team'] or a['score']!=b['opponent_score'] or b['score']!=a['opponent_score']:
                    mismatches['opposing_records'].append(gid)
                if (a['result'],b['result']) not in {('W','L'),('L','W'),('T','T'),('Pending','Pending')}:
                    mismatches['opposing_results'].append(gid)
                if (a['spread_result'],b['spread_result']) not in {('Cover','No cover'),('No cover','Cover'),('Push','Push'),('Unknown','Unknown'),('Pending','Pending')}:
                    mismatches['opposing_spread_results'].append(gid)
                raw=raw_by_id[gid]
                rawline=number(raw.get('spread_line'))
                for g in pair:
                    expected=None if rawline is None else -rawline if g['venue']=='Home' else rawline
                    if g['team_spread']!=expected: mismatches['spread_signs'].append(gid)
                    for market,odds_key,result_key,profit_key,win,loss,void in [('moneyline','moneyline','result','profit','W','L','T'),('spread','spread_odds','spread_result','spread_profit','Cover','No cover','Push')]:
                        if g[market+'_placed_stake']:
                            odds=Decimal(str(g[odds_key]));outcome=g[result_key]
                            expected_profit=Decimal(0) if outcome==void else Decimal(-10) if outcome==loss else Decimal(10)*(Decimal(100)/-odds if odds<0 else odds/Decimal(100))
                            if abs(g[profit_key]-float(expected_profit))>1e-8: mismatches['payout_calculations'].append(gid)
                            expected_refund=10 if outcome==void else 0
                            if g[market+'_refunded_stake']!=expected_refund or g[market+'_settled_stake']!=10-expected_refund:
                                mismatches['stake_and_refund_accounting'].append(gid)
                for key in ['market_probability','spread_market_probability']:
                    if a[key] is not None and b[key] is not None and abs(a[key]+b[key]-1)>1e-10:
                        mismatches['paired_probabilities'].append(gid)
            for name in ['two_sides_per_game','opposing_records','opposing_results','opposing_spread_results','spread_signs','payout_calculations','stake_and_refund_accounting','paired_probabilities']:
                bad=sorted(set(mismatches[name]));check(name,not bad,discrepancy_count=len(bad))
                for gid in bad:issue('error',name,gid)
            summary_rows=[]
            for team in TEAMS:
                games=all_team_games[team]
                output=dict(team=team,franchise_name=TEAMS[team],conference=ALIGNMENT[team][0],division=ALIGNMENT[team][1])
                for market in ['moneyline','spread']:
                    for split in SPLITS:
                        stats=summary_stats(subset(games,split,market),market)
                        insert(conn,'betting_summary',dict(team=team,market=market,split=split,season=0,stats_json=json.dumps(stats)))
                        for metric in METRICS:output[f'{market}_{split}_{metric}']=stats[metric]
                    for season in sorted({g['season'] for g in games}):
                        stats=summary_stats([g for g in games if g['season']==season],market)
                        insert(conn,'betting_summary',dict(team=team,market=market,split='all',season=season,stats_json=json.dumps(stats)))
                summary_rows.append(output)
            statuses=Counter(item[5] for item in accepted)
            season_counts={str(season):dict(Counter(item[5] for item in accepted if int(item[2]['season'])==season)) for season in sorted({int(item[2]['season']) for item in accepted})}
            coverage={}
            for market in ['moneyline','spread']:
                rows=[g for group in all_team_games.values() for g in group]
                coverage[market]=dict(completed_team_records=sum(g['game_status']=='completed' for g in rows),
                    completed_records_without_required_market=sum(g['game_status']=='completed' and not g[market+'_available'] for g in rows),
                    eligible_records=sum(g[market+'_placed_stake']>0 for g in rows),
                    placed_stakes=sum(g[market+'_placed_stake'] for g in rows),refunded_stakes=sum(g[market+'_refunded_stake'] for g in rows))
            check('source_records_without_errors',not any(i['severity']=='error' for i in issues),errors=sum(i['severity']=='error' for i in issues))
            check('sqlite_foreign_keys',not conn.execute('PRAGMA foreign_key_check').fetchall())
            metadata=dict(run_timestamp_utc=now.isoformat(),as_of_date=as_of.isoformat(),date_timezone='America/New_York',
                source_url=source_metadata.get('source_url',SOURCE),source_retrieved_at_utc=source_metadata.get('retrieved_at_utc'),
                fresh_download=source_metadata.get('fresh_download',False),source_sha256=digest,source_bytes=len(content),
                seasons=[2010,current_season],games=len(accepted),team_game_records=sum(map(len,all_team_games.values())),game_status_counts=dict(statuses),
                completed_date_min=min((i[2]['gameday'] for i in accepted if i[5]=='completed'),default=None),
                completed_date_max=max((i[2]['gameday'] for i in accepted if i[5]=='completed'),default=None),
                season_coverage=season_counts,market_coverage=coverage,source_rows_out_of_scope=out_of_scope,
                validation_passed=all(c['status']=='passed' for c in checks),issue_counts=dict(Counter(i['code'] for i in issues)))
            for key,value in metadata.items():insert(conn,'run_metadata',dict(key=key,value_json=json.dumps(value)))
            for row in checks:insert(conn,'validation_checks',row)
            for row in issues:insert(conn,'validation_issues',row)
            conn.commit()
            integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
            if integrity!='ok':raise RuntimeError('SQLite integrity check failed')
        finally:conn.close()
        buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=list(summary_rows[0]));writer.writeheader();writer.writerows(summary_rows)
        readme=make_readme(metadata,checks)
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(folder/'nfl_research.sqlite','nfl_research.sqlite')
            z.writestr('team_summary.csv',buffer.getvalue())
            z.writestr('README.md',readme)
            z.writestr('schema.sql',schema)
        return archive.getvalue(),f'NFL_Research_{as_of:%Y%m%d}.zip',metadata


def make_readme(m,checks):
    results='\n'.join(f"| {c['name']} | {c['status']} | {c['details_json']} |" for c in checks)
    return f'''# NFL Research: all 32 franchises, moneylines and spreads

Run UTC: {m['run_timestamp_utc']}. As-of date: {m['as_of_date']} in America/New_York.
Completed game dates: {m['completed_date_min']} through {m['completed_date_max']}.
Seasons requested: 2010 through {m['seasons'][1]}. Regular season and all playoff rounds included.
Unique accepted games: {m['games']}. Team-game records: {m['team_game_records']} (two per game).
Status counts: {json.dumps(m['game_status_counts'])}.
Validation passed: **{m['validation_passed']}**. Discrepancy counts: {json.dumps(m['issue_counts'])}.
Completion is inferred from both valid populated source final-score fields and a game date on/before the cutoff, not from a separate live game-status service.

## Source, provenance and coverage

Dataset: nflverse schedules, {m['source_url']}.
Fresh download: {m['fresh_download']}. Source retrieval UTC: {m['source_retrieved_at_utc'] or 'Unknown (local snapshot)'}.
Original bytes SHA-256: {m['source_sha256']}. The complete unmodified input CSV bytes are embedded in source_files.raw_csv.
Source row data is also preserved in games.raw_json. No input file is edited to pass validation.
Source type, sportsbook, odds timestamp and opening/closing designation are preserved when explicitly supplied per price.
The current standard nflverse schedule does not supply reliable quote-level provenance: these attributes remain unknown.
**Prices are historical dataset values of unspecified provenance, not certified sportsbook quotes or verified closing odds.**
No default -110 prices, no estimated replacements, no odds timestamp inferred from kickoff or retrieval time.
market_quotes.source_type distinguishes actual_historical_sportsbook_quote, estimated_reference_price, other and unknown only when supplied. Such labels are source claims; verification_status remains not_independently_verified.
Market coverage counts (team records, not distinct games): {json.dumps(m['market_coverage'])}.
Season coverage: {json.dumps(m['season_coverage'])}.
Current season is in progress. Historical canceled/unplayed games omitted by the source cannot be reconstructed. This archive checks internal consistency, not independent schedule completeness.

## Tables and identifiers

- teams: 32 stable franchises with AFC/NFC, division and historical abbreviation aliases. OAK/LV, SD/LAC and STL/LA/LAR are combined. Alignment is valid for the 2010-present study interval.
- games: **one row per unique source game_id**, scores, original text odds/spreads, source row, raw JSON and game status. For game counts use this table or COUNT(DISTINCT game_id), never count team_games as distinct games.
- team_games: **two rows per game**, primary key (game_id, team), one perspective per franchise. venue is the source Home/Away designation; neutral-site games still have designated sides (see games.raw_json.location). game_status distinguishes completed, future, incomplete and discrepant.
- market_quotes: four rows per game (two markets × two sides), raw and usable American odds and quote provenance. NULL means missing/unusable, not zero.
- betting_summary: long-format statistics JSON per team/market/split/season. season=0 is full-history; nonzero seasons have split=all.
- run_metadata: run, checksum, date and coverage details as JSON values.
- validation_checks and validation_issues: machine-readable outcomes and discrepancies. Duplicate or invalid-identity rows are quarantined, not arbitrarily selected. Their original bytes remain in source_files; issue details identify affected source rows.
- completed_games/completed_team_games and unsettled_games/unsettled_team_games: separate views. future_games contains dates beyond the cutoff. Incomplete/discrepant games have no settled bets even when some input values exist.

Fields: season is NFL season, not calendar year; week and game_type (REG/WC/DIV/CON/SB) preserve source meaning. is_playoff distinguishes postseason. is_divisional means same division and conference; is_intraconference includes divisional games; is_interconference means AFC vs NFC. These are derived independently; source flags remain in raw_json and disagreements are reported.
score/opponent_score, moneyline/opponent_moneyline, team_spread/opponent_spread and spread_odds/opponent_spread_odds use the selected team perspective. games.spread_line_raw preserves nflverse's expected home winning margin; home handicap is its negative, away handicap is its positive.
market_probability and spread_market_probability are no-vig probabilities; moneyline_implied_probability and spread_implied_probability are unnormalized own-price implied probabilities. Spread probabilities refer to non-push outcomes.
moneyline_available requires a valid own moneyline; spread_available requires a valid line and own spread odds. Pair availability is separate. A missing opponent price prevents no-vig expectations and moneyline role classification, but not realized returns at a valid own price.

## Settlement and money

Flat stake is **$10 risked per eligible bet** in each market independently. Odds must be finite integer American odds with absolute value >=100. Original invalid strings remain preserved and are reported.
Winning net: 10*odds/100 for positive odds; 10*100/abs(odds) for negative odds. Losing net: -10. Moneyline ties and spread pushes: 0 net and $10 refunded.
Spread result uses score-opponent_score+team_spread: positive=Cover, negative=No cover, zero=Push. A game tie can cover a nonzero spread.
*_placed_stake includes stakes later refunded; *_refunded_stake tracks refunds; *_settled_stake = placed minus refunded. *_gross_return = placed stake + net profit. Pending/unavailable bets have zero stakes and NULL profit, not a zero-return bet.
**ROI = net profit / settled stakes**, excluding refunded pushes/ties. Zero settled stakes produces NULL ROI. Calculations retain unrounded floating-point payouts; rounding only presentation totals can differ from sportsbook cent-by-cent settlement.
Moneyline favorites compare both implied probabilities. Spread favorites have negative handicaps; spread underdogs positive handicaps. Even/pick’em and unknown classifications have separate groups.

## team_summary.csv

Exactly 32 rows, one per franchise. Prefixes moneyline_ or spread_, then split (all/favorites/underdogs/even/unknown/home/away/regular/playoffs), then statistic.
bets_placed includes refunded bets; bets is settled non-refunded bets. wins/losses mean winning/losing bets (covers/non-covers for spread); voids includes moneyline ties or spread pushes. pushes is spread-only. placed_stakes/refunded_stakes/stake are dollars; profit is net dollars; roi_percent is percentage points, e.g. 5 means 5%. Missing odds and missing lines are separate; assessed_* results include known outcomes without requiring a usable price. expected_wins and observed_wins use the same paired-price, non-void sample; paired_games is its size. games is completed game count and pending is all unsettled records.
All source game wins/losses/ties can also be counted from completed_team_games.result independently of betting availability. Split columns are separate marginal summaries; do not add all+home+away or market totals together as independent samples. Opposing sides are correlated observations, not independent games.

## Validation

| Check | Status | Details |
|---|---|---|
{results}

Review validation_issues before analysis whenever validation_passed is false. No discrepancy is corrected by changing source values. Missing odds are coverage gaps, not validation failures. Source checksum and embedded raw bytes allow reproduction without network access.

Example SQLite queries:
```sql
SELECT COUNT(*) FROM completed_games;
SELECT team, SUM(moneyline_settled_stake), SUM(profit) FROM completed_team_games GROUP BY team;
SELECT * FROM validation_issues;
SELECT team, market, stats_json FROM betting_summary WHERE split='all' AND season=0;
```
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,help='Explicit local snapshot instead of fresh source download')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'exports')
    parser.add_argument('--as-of',type=date.fromisoformat,help='Optional reproducible cutoff YYYY-MM-DD')
    args=parser.parse_args()
    if args.input:
        content=args.input.read_bytes();metadata=dict(source_url=SOURCE,fresh_download=False)
    else:content,metadata=fresh_source()
    archive,filename,report=build_archive(content,metadata,args.as_of)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    target=args.output_dir/filename
    with tempfile.NamedTemporaryFile(dir=args.output_dir,delete=False) as f:
        temporary=Path(f.name);f.write(archive)
    temporary.replace(target)
    print(f'Created {target}: {report["games"]} unique games, {report["team_game_records"]} team-game records.')
    print('Validation passed:',report['validation_passed'])
    print('Issues:',report['issue_counts'])
    return 0 if report['validation_passed'] else 2


if __name__=='__main__':raise SystemExit(main())
