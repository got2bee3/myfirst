import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import date

from analysis_engine import read_games,team_games,summarize,price_bands,TEAMS,implied
import app as gui


def fixture(**updates):
    r=dict(game_id='2010_01_SD_KC',season='2010',week='1',gameday='2010-09-13',game_type='REG',home_team='KC',away_team='SD',home_score='21',away_score='14',home_moneyline='180',away_moneyline='-200')
    r.update(updates)
    return r


class AnalysisTests(unittest.TestCase):
    def test_flat_bet_payouts_and_vig(self):
        rows=[fixture(),fixture(game_id='b',gameday='2010-09-20',home_score='3',home_moneyline='-200',away_moneyline='180'),fixture(game_id='c',gameday='2010-09-27',home_moneyline='-200',away_moneyline='180')]
        games=team_games(rows,'KC','2026-10-26')
        s=summarize(games)
        self.assertAlmostEqual(s['profit'],18-10+5)
        self.assertAlmostEqual(s['roi'],13/30)
        self.assertAlmostEqual(games[0]['market_probability'],implied(180)/(implied(180)+implied(-200)))
        self.assertEqual(games[0]['market_status'],'Underdog')

    def test_tie_void_and_missing_prices(self):
        games=team_games([fixture(home_score='14'),fixture(game_id='b',home_moneyline=''),fixture(game_id='c',away_moneyline='')],'KC','2026-10-26')
        s=summarize(games)
        self.assertEqual(s['voids'],1)
        self.assertEqual(s['bets'],1)
        self.assertEqual(s['missing_odds'],1)
        self.assertEqual(s['missing_pairs'],2)
        self.assertEqual(s['paired_games'],0)
        self.assertAlmostEqual(s['profit'],18)

    def test_relocations_and_future_score_exclusion(self):
        games=team_games([fixture(),fixture(game_id='b',gameday='2027-01-01')],'LAC','2026-10-26')
        self.assertEqual(len(games),2)
        self.assertEqual(games[0]['result'],'L')
        self.assertEqual(games[1]['result'],'Pending')
        self.assertIsNone(games[1]['profit'])

    def test_price_boundaries_count_each_game_once(self):
        values=[-250,-200,-150,-100,100,150,200,250]
        games=team_games([fixture(game_id=str(i),home_moneyline=str(v)) for i,v in enumerate(values)],'KC','2026-10-26')
        bands=price_bands(games,[-200,-150,0,150,200])
        self.assertEqual([s['bets'] for _,s in bands],[2,1,1,2,1,1])
        self.assertEqual(sum(s['bets'] for _,s in bands),8)


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.client=gui.app.test_client()

    def test_every_franchise_renders(self):
        for team in TEAMS:
            with self.subTest(team=team):
                response=self.client.get('/',query_string={'team':team})
                self.assertEqual(response.status_code,200)
                self.assertIn(b'Game ledger',response.data)

    def test_era_validation_and_selection(self):
        self.assertEqual(self.client.get('/?previous_start=2010-01-01&previous_end=2020-01-01&current_start=2019-01-01').status_code,400)
        self.assertEqual(self.client.get('/?period=current').status_code,400)
        response=self.client.get('/?team=KC&period=previous&previous_start=2010-01-01&previous_end=2011-02-01')
        self.assertEqual(response.status_code,200)
        self.assertIn('10–7'.encode(),response.data)

    def test_csv_applies_selected_filters(self):
        response=self.client.get('/download.csv?team=KC&mode=underdogs&game_type=playoffs')
        self.assertEqual(response.status_code,200)
        rows=list(csv.DictReader(io.StringIO(response.data.decode())))
        self.assertGreater(len(rows),0)
        self.assertTrue(all(r['market_status']=='Underdog' and r['game_type']!='REG' for r in rows))

    def test_refresh_requires_csrf(self):
        self.assertEqual(self.client.post('/refresh').status_code,403)

    def test_named_eras_and_comments_in_summary_export(self):
        query=dict(team='DET',current_name='Dan Campbell era',
                   current_comments='New coach, new approach\nReview the rebuild.',
                   current_start='2021-01-01',period='current')
        response=self.client.get('/report.csv',query_string=query)
        self.assertEqual(response.status_code,200)
        rows=list(csv.DictReader(io.StringIO(response.data.decode())))
        current=next(r for r in rows if r['section']=='comparison' and r['period']=='current')
        self.assertEqual(current['era_name'],query['current_name'])
        self.assertEqual(current['era_comments'],query['current_comments'])
        self.assertEqual(current['period_start'],'2021-01-01')
        self.assertEqual(current['flat_stake'],'10')
        self.assertEqual(current['sportsbook'],'Unknown')
        self.assertAlmostEqual(float(current['roi_percent']),100*float(current['profit'])/float(current['stake']))
        self.assertEqual(len([r for r in rows if r['section']=='moneyline_range']),6)
        self.assertTrue(any(r['section']=='season' for r in rows))

    def test_game_export_labels_era_without_changing_calculations(self):
        query=dict(team='PIT',current_name='Post-Roethlisberger',
                   current_comments='Quarterback retired',current_start='2022-01-01')
        rows=list(csv.DictReader(io.StringIO(self.client.get('/download.csv',query_string=query).data.decode())))
        old=next(r for r in rows if r['date']<'2022-01-01')
        new=next(r for r in rows if r['date']>='2022-01-01')
        self.assertEqual(old['game_era'],'full')
        self.assertEqual(new['game_era_name'],query['current_name'])
        self.assertEqual(new['game_era_comments'],query['current_comments'])
        baseline=gui.analyze({'team':'PIT'})['summary']
        self.assertEqual(gui.analyze(query)['summary'],baseline)

    def test_era_text_is_escaped_in_html_and_spreadsheet_formulas(self):
        query=dict(current_start='2022-01-01',current_name='=1+1',
                   current_comments='<script>alert(1)</script>',period='current')
        page=self.client.get('/',query_string=query)
        self.assertNotIn(b'<script>alert(1)</script>',page.data)
        rows=list(csv.DictReader(io.StringIO(self.client.get('/report.csv',query_string=query).data.decode())))
        current=next(r for r in rows if r['period']=='current')
        self.assertEqual(current['era_name'],"'=1+1")

    def test_era_name_and_comment_limits(self):
        self.assertEqual(self.client.get('/report.csv',query_string={'current_name':'x'*101}).status_code,400)
        self.assertEqual(self.client.get('/download.csv',query_string={'current_comments':'x'*1001}).status_code,400)

    def test_failed_refresh_preserves_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/'games.csv').write_text('prior data')
            with patch.object(gui,'DATA',path),patch('urllib.request.urlopen',side_effect=OSError('offline')):
                with self.client.session_transaction() as session:
                    session['csrf']='test-token'
                response=self.client.post('/refresh',data={'csrf':'test-token'})
                self.assertEqual(response.status_code,302)
                self.assertEqual((path/'games.csv').read_text(),'prior data')


if __name__=='__main__': unittest.main()
