import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from research_export import build_archive
import research_export
from analysis_engine import team_games
import app as gui


def row(**changes):
    data=dict(game_id='2010_01_SD_KC',season='2010',week='1',gameday='2010-09-12',game_type='REG',
              home_team='KC',away_team='SD',home_score='17',away_score='14',
              home_moneyline='180',away_moneyline='-200',spread_line='3',
              home_spread_odds='-110',away_spread_odds='-105',div_game='1')
    data.update(changes)
    return data


def csv_bytes(rows):
    buffer=io.StringIO()
    fields=list(dict.fromkeys(key for r in rows for key in r))
    writer=csv.DictWriter(buffer,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    return buffer.getvalue().encode()


class ResearchTests(unittest.TestCase):
    def unpack(self,content):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        blob,filename,metadata=build_archive(content,as_of='2010-10-01')
        archive=zipfile.ZipFile(io.BytesIO(blob))
        self.assertEqual(set(archive.namelist()),{'nfl_research.sqlite','team_summary.csv','README.md','schema.sql'})
        self.assertIsNone(archive.testzip())
        path=Path(self.temp.name)/'database.sqlite';path.write_bytes(archive.read('nfl_research.sqlite'))
        db=sqlite3.connect(path);db.row_factory=sqlite3.Row;self.addCleanup(db.close)
        self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        return db,archive,metadata

    def test_refunds_independent_markets_future_games_and_summary(self):
        content=csv_bytes([row(),
            row(game_id='tie',gameday='2010-09-19',home_score='14',away_team='STL',spread_line='-3',div_game='0'),
            row(game_id='missing',gameday='2010-09-26',away_team='OAK',home_moneyline='',home_score='21',away_spread_odds=''),
            row(game_id='future',gameday='2010-10-10',home_score='',away_score='')])
        db,archive,meta=self.unpack(content)
        self.assertEqual(db.execute('SELECT count(*) FROM teams').fetchone()[0],32)
        self.assertEqual(db.execute('SELECT count(*) FROM games').fetchone()[0],4)
        self.assertEqual(db.execute('SELECT count(*) FROM team_games').fetchone()[0],8)
        self.assertEqual(db.execute('SELECT count(*) FROM future_games').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT count(*) FROM completed_games').fetchone()[0],3)
        push=dict(db.execute("SELECT * FROM team_games WHERE game_id='2010_01_SD_KC' AND team='KC'").fetchone())
        self.assertEqual(push['spread_bet_status'],'void')
        self.assertEqual(push['spread_refunded_stake'],10)
        self.assertEqual(push['spread_settled_stake'],0)
        self.assertEqual(push['spread_gross_return'],10)
        self.assertEqual(push['profit'],18)
        home=db.execute("SELECT * FROM team_games WHERE game_id='missing' AND team='KC'").fetchone()
        away=db.execute("SELECT * FROM team_games WHERE game_id='missing' AND team='LV'").fetchone()
        self.assertEqual((home['moneyline_available'],home['spread_available']),(0,1))
        self.assertEqual((away['moneyline_available'],away['spread_available']),(1,0))
        self.assertIsNone(home['profit']);self.assertAlmostEqual(home['spread_profit'],1000/110)
        future=db.execute("SELECT * FROM team_games WHERE game_id='future' LIMIT 1").fetchone()
        self.assertEqual(future['moneyline_placed_stake'],0);self.assertIsNone(future['profit'])
        self.assertEqual(db.execute('SELECT raw_csv FROM source_files').fetchone()[0],content)
        summaries=list(csv.DictReader(io.StringIO(archive.read('team_summary.csv').decode())))
        self.assertEqual(len(summaries),32)
        kc=next(r for r in summaries if r['team']=='KC')
        self.assertEqual(float(kc['moneyline_all_refunded_stakes']),10)
        self.assertEqual(float(kc['moneyline_all_stake']),10)
        self.assertEqual(float(kc['moneyline_all_roi_percent']),180)
        checks={r['name']:r['status'] for r in db.execute('SELECT * FROM validation_checks')}
        self.assertEqual(checks['payout_calculations'],'passed')
        self.assertEqual(checks['spread_signs'],'passed')
        # Small fixture deliberately does not represent all 32 franchises.
        self.assertFalse(meta['validation_passed'])

    def test_duplicates_and_inconsistent_results_reported_without_source_changes(self):
        content=csv_bytes([row(),row(),row(game_id='bad_result',result='999')])
        db,archive,meta=self.unpack(content)
        self.assertFalse(meta['validation_passed'])
        self.assertEqual(db.execute('SELECT count(*) FROM games').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT count(*) FROM completed_games').fetchone()[0],0)
        codes=[r[0] for r in db.execute('SELECT code FROM validation_issues')]
        self.assertIn('duplicate_or_missing_game_id',codes)
        self.assertIn('source_result_disagrees_with_scores',codes)
        self.assertEqual(db.execute('SELECT raw_csv FROM source_files').fetchone()[0],content)
        self.assertIn(b'**False**',archive.read('README.md'))

    def test_validation_detects_wrong_payout_and_spread(self):
        def corrupt(*args,**kwargs):
            records=team_games(*args,**kwargs)
            for record in records:
                record['profit']+=1
                record['team_spread']=-record['team_spread']
            return records
        with patch.object(research_export,'team_games',side_effect=corrupt):
            db,_,meta=self.unpack(csv_bytes([row()]))
        checks={r['name']:r['status'] for r in db.execute('SELECT * FROM validation_checks')}
        self.assertEqual(checks['payout_calculations'],'failed')
        self.assertEqual(checks['spread_signs'],'failed')

    def test_quote_provenance_and_unknowns(self):
        content=csv_bytes([row(moneyline_source_type='estimated_reference_price',moneyline_sportsbook='Example Book',
                              moneyline_odds_timestamp='2010-09-12T12:00:00Z',moneyline_price_timing='opening')])
        db,_,_=self.unpack(content)
        ml=db.execute("SELECT * FROM market_quotes WHERE market='moneyline' LIMIT 1").fetchone()
        self.assertEqual(ml['source_type'],'estimated_reference_price')
        self.assertEqual(ml['sportsbook'],'Example Book')
        self.assertEqual(ml['odds_timestamp'],'2010-09-12T12:00:00Z')
        spread=db.execute("SELECT * FROM market_quotes WHERE market='spread' LIMIT 1").fetchone()
        self.assertEqual(spread['source_type'],'unknown')
        self.assertIsNone(spread['sportsbook']);self.assertIsNone(spread['odds_timestamp'])

    def test_web_download_is_csrf_protected_and_self_contained(self):
        client=gui.app.test_client()
        self.assertEqual(client.post('/research.zip').status_code,403)
        with client.session_transaction() as session:session['csrf']='export-test'
        with patch('research_export.fresh_source',return_value=(csv_bytes([row()]),{'fresh_download':False})):
            response=client.post('/research.zip',data={'csrf':'export-test'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.mimetype,'application/zip')
        self.assertTrue(response.headers['Content-Disposition'].startswith('attachment; filename=NFL_Research_'))
        self.assertEqual(len(zipfile.ZipFile(io.BytesIO(response.data)).namelist()),4)


if __name__=='__main__':unittest.main()
