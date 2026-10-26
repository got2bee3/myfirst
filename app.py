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
    dates={key:args.get(key,'').strip() for key in ['previous_start','previous_end','current_start','current_end']}
    for v in dates.values():
        if v:
            datetime.strptime(v,'%Y-%m-%d')
            if v<'2010-01-01': raise ValueError('Era dates must be on or after January 1, 2010.')
    for prefix in ['previous','current']:
        a,b=dates[prefix+'_start'],dates[prefix+'_end']
        if b and not a: raise ValueError('An era end date also requires a start date.')
        if a and b and a>b: raise ValueError('Era start must precede its end date.')
    if dates['previous_start'] and not dates['previous_end']:
        raise ValueError('Choose an end date for the previous era.')
    if dates['previous_start'] and dates['current_start'] and dates['previous_end']>=dates['current_start']:
        raise ValueError('Previous and current eras must not overlap.')
    period=args.get('period','full')
    if period not in {'full','previous','current'}: raise ValueError('Choose a valid comparison period.')
    if period!='full' and not dates[period+'_start']:
        raise ValueError('Choose dates for that era first.')
    return dict(team=team,mode=mode,game_type=game_type,cuts=cuts,dates=dates,period=period)


def analyze(args):
    opts=options(args)
    games=team_games(read_games(DATA/'games.csv'),opts['team'],datetime.now(ZoneInfo('America/New_York')).date().isoformat())
    if opts['game_type']!='all':
        games=[g for g in games if (g['game_type']=='REG')==(opts['game_type']=='regular')]
    periods={'full':games}
    for key in ['previous','current']:
        start,end=opts['dates'][key+'_start'],opts['dates'][key+'_end']
        periods[key]=None if not start else [g for g in games if g['date']>=start and (not end or g['date']<=end)]
    selected=split_filter(periods[opts['period']],opts['mode'])
    comparisons=[(key,None if group is None else summarize(split_filter(group,opts['mode']))) for key,group in periods.items()]
    splits=[(label,summarize(split_filter(periods[opts['period']],mode))) for label,mode in [('All games','all'),('Favorites','favorites'),('Underdogs','underdogs')]]
    seasons=[(season,summarize([g for g in selected if g['season']==season])) for season in sorted({g['season'] for g in selected},reverse=True)]
    try: meta=json.loads((DATA/'snapshot.json').read_text())
    except (OSError,ValueError): meta={}
    return dict(opts=opts,games=list(reversed(selected)),summary=summarize(selected),comparisons=comparisons,splits=splits,seasons=seasons,bands=price_bands(selected,opts['cuts']),meta=meta)


@app.template_filter('money')
def money(v): return '—' if v is None else f'${v:,.2f}'
@app.template_filter('percent')
def percent(v): return '—' if v is None else f'{v:.1%}'
@app.template_filter('ml')
def ml(v): return '—' if v is None else f'{v:+.0f}'


@app.get('/')
def index():
    session.setdefault('csrf',secrets.token_hex(24))
    try: context=analyze(request.args)
    except (ValueError, OSError):
        return render_template('error.html',message='Please check the filters and era dates. If the data file is missing, use Refresh historical data.',csrf=session['csrf']),400
    return render_template('index.html',teams=TEAMS,csrf=session['csrf'],**context)


@app.get('/download.csv')
def download():
    try: context=analyze(request.args)
    except (ValueError,OSError): abort(400)
    buffer=io.StringIO()
    fields=['game_id','season','week','date','game_type','opponent','venue','score','opponent_score','moneyline','opponent_moneyline','market_status','market_probability','result','profit']
    writer=csv.DictWriter(buffer,fieldnames=fields)
    writer.writeheader();writer.writerows(context['games'])
    return Response(buffer.getvalue(),mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename={context["opts"]["team"]}_moneyline_study.csv'})


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


if __name__=='__main__':
    app.run(host='127.0.0.1',port=5000,debug=False)
