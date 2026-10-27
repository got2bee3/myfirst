"""Independent NFL Team Performance GUI. Never connects to MySQL."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
from datetime import datetime
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo
import urllib.request
import fcntl
from flask import Flask, render_template, request, session, redirect, url_for, flash, Response, abort
from analysis_engine import TEAMS, DEFAULT_CUTS, read_games, team_games, summarize, split_filter, price_bands

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('NFL_DATA_DIR', str(ROOT/'data')))
SOURCE='https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv'
app=Flask(__name__)
app.secret_key=os.environ.get('NFL_GUI_SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',MAX_CONTENT_LENGTH=16384)


def options(args):
    team=args.get('team','KC')
    if team not in TEAMS: raise ValueError('Choose a valid team.')
    mode=args.get('mode','all')
    if mode not in {'all','favorites','underdogs'}: raise ValueError('Choose a valid betting filter.')
    game_type=args.get('game_type','all')
    if game_type not in {'all','regular','playoffs'}: raise ValueError('Choose a valid game type.')
    cuts=[float(args.get(f'cut{i}',v)) for i,v in enumerate(DEFAULT_CUTS)]
    if any(not -100000<=v<=100000 for v in cuts) or any(a>=b for a,b in zip(cuts,cuts[1:])):
        raise ValueError('Enter five increasing, finite odds boundaries.')
    market=args.get('market','moneyline')
    if market not in {'moneyline','spread'}: raise ValueError('Choose moneyline or spread.')
    return dict(team=team,mode=mode,game_type=game_type,cuts=cuts,market=market)



def analyze(args):
    opts=options(args)
    games=team_games(read_games(DATA/'games.csv'),opts['team'],datetime.now(ZoneInfo('America/New_York')).date().isoformat())
    if opts['game_type']!='all':
        games=[g for g in games if (g['game_type']=='REG')==(opts['game_type']=='regular')]
    market=opts['market']
    selected=split_filter(games,opts['mode'],market)
    splits=[(label,summarize(split_filter(games,mode,market),market)) for label,mode in [('All games','all'),('Favorites','favorites'),('Underdogs','underdogs')]]
    seasons=[(season,summarize([g for g in selected if g['season']==season],market)) for season in sorted({g['season'] for g in selected},reverse=True)]
    overview=[(kind,summarize(split_filter(games,opts['mode'],kind),kind)) for kind in ['moneyline','spread']]
    try: meta=json.loads((DATA/'snapshot.json').read_text())
    except (OSError,ValueError): meta={}
    return dict(opts=opts,games=list(reversed(selected)),summary=summarize(selected,market),overview=overview,splits=splits,seasons=seasons,bands=price_bands(selected,opts['cuts']) if market=='moneyline' else [],meta=meta)


@app.template_filter('money')
def money(v): return '—' if v is None else f'${v:,.2f}'
@app.template_filter('percent')
def percent(v): return '—' if v is None else f'{v:.1%}'
@app.template_filter('ml')
def ml(v): return '—' if v is None else f'{v:+.0f}'


@app.template_filter('spread')
def spread(v): return '—' if v is None else 'PK' if v==0 else f'{v:+g}'


@app.get('/')
def index():
    session.setdefault('csrf',secrets.token_hex(24))
    try: context=analyze(request.args)
    except (ValueError, OSError):
        return render_template('error.html',message='Please check the team and betting filters. If the data file is missing, use Refresh historical data.',csrf=session['csrf']),400
    return render_template('index.html',teams=TEAMS,csrf=session['csrf'],**context)


@app.get('/download.csv')
def download():
    try: context=analyze(request.args)
    except (ValueError,OSError): abort(400)
    metadata=export_metadata(context)
    rows=[dict(metadata,**game) for game in context['games']]
    fields=list(metadata)+['game_id','season','week','date','game_type','opponent','venue','score','opponent_score','moneyline','opponent_moneyline','market_status','market_probability','result','profit','team_spread','opponent_spread','spread_odds','opponent_spread_odds','spread_status','spread_result','spread_profit','spread_market_probability']
    return csv_response(rows,fields,f'{context["opts"]["team"]}_games.csv')


def export_metadata(context,market=None):
    opts=context['opts']
    return dict(team=opts['team'],franchise=TEAMS[opts['team']],analysis_market=market or opts['market'],
             bet_filter=opts['mode'],schedule_filter=opts['game_type'],flat_stake=10,
             exported_at_utc=datetime.now(ZoneInfo('UTC')).isoformat(),
             source='nflverse',source_url=context['meta'].get('source',SOURCE),
             snapshot_retrieved_at=context['meta'].get('retrieved_at','Unknown'),
             snapshot_sha256=context['meta'].get('sha256','Unknown'),sportsbook='Unknown',price_timing='Unknown',
             tie_settlement='Moneyline ties and spread pushes are void, excluded from settled stake and expectations',
             period_start='2010 season',
             price_boundaries='; '.join(f'{cut:g}' for cut in opts['cuts']))


def csv_response(rows,fields,filename):
    def safe_cell(value):
        # Keep textual cells from being interpreted as spreadsheet formulas.
        if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):
            return "'"+value
        return value
    buffer=io.StringIO(newline='')
    writer=csv.DictWriter(buffer,fieldnames=fields)
    writer.writeheader()
    writer.writerows({key:safe_cell(value) for key,value in row.items()} for row in rows)
    return Response(buffer.getvalue(),content_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition':f'attachment; filename={filename}'})


@app.get('/report.csv')
def report():
    try: context=analyze(request.args)
    except (ValueError,OSError): abort(400)
    rows=[]
    def add(market,section,label,stats,bet_filter=None):
        row=export_metadata(context,market)
        row.update(section=section,group=str(label))
        if bet_filter: row['bet_filter']=bet_filter
        row.update(stats)
        row['roi_percent']=100*row.pop('roi') if stats['roi'] is not None else None
        row.pop('roi',None)
        row['outcomes_above_market']=stats['observed_wins']-stats['expected_wins']
        rows.append(row)
    market=context['opts']['market']
    for kind,stats in context['overview']: add(kind,'market_overview',kind,stats)
    for (label,stats),mode in zip(context['splits'],['all','favorites','underdogs']):
        add(market,'bet_selection',label,stats,mode)
    for label,stats in context['bands']: add('moneyline','moneyline_range',label,stats)
    for label,stats in context['seasons']: add(market,'season',label,stats)
    return csv_response(rows,list(rows[0]),f'{context["opts"]["team"]}_analysis_summary.csv')


@app.post('/refresh')
def refresh():
    if not secrets.compare_digest(request.form.get('csrf',''),session.get('csrf','!')): abort(403)
    DATA.mkdir(exist_ok=True,parents=True)
    temporary=None
    try:
        with (DATA/'.refresh.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with urllib.request.urlopen(SOURCE,timeout=45) as response:
                content=response.read(8_000_001)
            if len(content)>8_000_000: raise ValueError('Source file exceeds size limit.')
            with NamedTemporaryFile(dir=DATA,suffix='.csv',delete=False) as f:
                temporary=Path(f.name);f.write(content)
            rows=read_games(temporary)
            if len(rows)<4000: raise ValueError('Incomplete source download.')
            temporary.replace(DATA/'games.csv');temporary=None
            meta=dict(retrieved_at=datetime.now(ZoneInfo('UTC')).isoformat(),source=SOURCE,sha256=hashlib.sha256(content).hexdigest())
            (DATA/'snapshot.json').write_text(json.dumps(meta,indent=2))
        flash('Historical data refreshed. Your selected analysis is ready.','success')
    except Exception as exc:
        app.logger.warning('Historical refresh failed: %s',type(exc).__name__)
        flash('Refresh failed or another refresh is running. The previous data is preserved.','error')
    finally:
        if temporary: temporary.unlink(missing_ok=True)
    # Only redirect to this application, retaining the GET filters from the form.
    return redirect(url_for('index')+('?' + request.form.get('filters','') if request.form.get('filters') else ''))


@app.post('/research.zip')
def research_zip():
    if not secrets.compare_digest(request.form.get('csrf',''),session.get('csrf','!')): abort(403)
    from research_export import fresh_source, build_archive
    DATA.mkdir(exist_ok=True,parents=True)
    try:
        with (DATA/'.research.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            content,metadata=fresh_source()
            archive,filename,report=build_archive(content,metadata)
        return Response(archive,content_type='application/zip',headers={
            'Content-Disposition':f'attachment; filename={filename}',
            'X-Research-Validation':'passed' if report['validation_passed'] else 'discrepancies-reported'})
    except Exception as exc:
        app.logger.warning('Research export failed: %s',type(exc).__name__)
        flash('The research ZIP could not be created, or another export is running. Please try again. No source data was changed.','error')
        return redirect(url_for('index'))


if __name__=='__main__':
    app.run(host='127.0.0.1',port=5000,debug=False)
