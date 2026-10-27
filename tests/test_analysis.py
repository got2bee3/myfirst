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
    r=dict(game_id='2010_01_SD_KC',season='2010',week='1',gameday='2010-09-13',game_type='REG',home_team='KC',away_team='SD',home_score='21',away_score='14',home_moneyline='180',away_moneyline='-200',spread_line='3',home_spread_odds='-110',away_spread_odds='-105')
    r.update(updates)
    return r


class AnalysisTests(unittest.TestCase):
    def test_spread_home_away_sign_and_cover_complement(self):
        row=fixture(home_score='21',away_score='14',spread_line='3')
        home=team_games([row],'KC','2026-10-27')[0]
        away=team_games([row],'LAC','2026-10-27')[0]
        self.assertEqual(home['team_spread'],-3)
        self.assertEqual(away['team_spread'],3)
        self.assertEqual(home['spread_result'],'Cover')
        self.assertEqual(away['spread_result'],'No cover')
        self.assertAlmostEqual(home['spread_profit'],1000/110)
        self.assertEqual(away['spread_profit'],-10)
        self.assertAlmostEqual(home['spread_market_probability']+away['spread_market_probability'],1)

    def test_spread_push_is_not_game_tie(self):
        game=team_games([fixture(home_score='17',away_score='14',spread_line='3')],'KC','2026-10-27')[0]
        self.assertEqual(game['result'],'W')
        self.assertEqual(game['spread_result'],'Push')
        self.assertEqual(game['spread_profit'],0)
        stats=summarize([game],'spread')
        self.assertEqual(stats['voids'],1)
        self.assertEqual(stats['stake'],0)
        self.assertEqual(stats['paired_games'],0)
        self.assertIsNone(stats['roi'])

    def test_losing_team_can_cover_and_tied_game_can_cover(self):
        losing=team_games([fixture(home_score='20',away_score='21',spread_line='-3')],'KC','2026-10-27')[0]
        self.assertEqual(losing['result'],'L')
        self.assertEqual(losing['team_spread'],3)
        self.assertEqual(losing['spread_result'],'Cover')
        tied=team_games([fixture(home_score='14',away_score='14',spread_line='-3')],'KC','2026-10-27')[0]
        self.assertEqual(tied['result'],'T')
        self.assertEqual(tied['spread_result'],'Cover')

    def test_missing_spread_data_is_never_fabricated(self):
        rows=[fixture(spread_line=''),fixture(game_id='b',home_spread_odds=''),fixture(game_id='c',away_spread_odds='')]
        games=team_games(rows,'KC','2026-10-27')
        self.assertIsNone(games[0]['spread_profit'])
        self.assertEqual(games[0]['spread_result'],'Unknown')
        self.assertEqual(games[1]['spread_result'],'Cover')
        self.assertIsNone(games[1]['spread_profit'])
        s=summarize(games,'spread')
        self.assertEqual(s['missing_lines'],1)
        self.assertEqual(s['missing_odds'],1)
        self.assertEqual(s['bets'],1)
        self.assertEqual(s['paired_games'],0)
        self.assertEqual(s['assessed_wins'],2)

    def test_pending_spread_and_pickem(self):
        pending=team_games([fixture(home_score='',away_score='')],'KC','2026-10-27')[0]
        self.assertEqual(pending['spread_result'],'Pending')
        self.assertIsNone(pending['spread_profit'])
        pickem=team_games([fixture(spread_line='0')],'KC','2026-10-27')[0]
        self.assertEqual(pickem['team_spread'],0)
        self.assertEqual(pickem['spread_status'],'Even')

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

    def test_csv_applies_selected_filters(self):
        response=self.client.get('/download.csv?team=KC&mode=underdogs&game_type=playoffs')
        self.assertEqual(response.status_code,200)
        rows=list(csv.DictReader(io.StringIO(response.data.decode())))
        self.assertGreater(len(rows),0)
        self.assertTrue(all(r['market_status']=='Underdog' and r['game_type']!='REG' for r in rows))

    def test_spread_analysis_and_exports(self):
        query=dict(team='PIT',market='spread',mode='underdogs',game_type='regular')
        page=self.client.get('/',query_string=query)
        self.assertEqual(page.status_code,200)
        self.assertIn(b'ATS result',page.data)
        self.assertNotIn(b'name="period"',page.data)
        self.assertNotIn(b'localStorage',page.data)
        self.assertNotIn(b'Name eras',page.data)
        response=self.client.get('/download.csv',query_string=query)
        rows=list(csv.DictReader(io.StringIO(response.data.decode())))
        self.assertTrue(rows)
        self.assertTrue(all(float(r['team_spread'])>0 and r['game_type']=='REG' for r in rows))
        self.assertIn('spread_profit',rows[0])
        self.assertNotIn('era_name',rows[0])
        report=list(csv.DictReader(io.StringIO(self.client.get('/report.csv',query_string=query).data.decode())))
        self.assertEqual({r['analysis_market'] for r in report if r['section']=='market_overview'},{'spread','moneyline'})
        selected=next(r for r in report if r['section']=='bet_selection' and r['bet_filter']=='underdogs')
        games=gui.analyze(query)['games']
        expected=summarize(games,'spread')
        self.assertAlmostEqual(float(selected['profit']),expected['profit'])
        self.assertAlmostEqual(float(selected['roi_percent']),100*expected['roi'])

    def test_moneyline_regression_and_legacy_era_links(self):
        baseline=gui.analyze({'team':'PIT'})['summary']
        self.assertAlmostEqual(baseline['profit'],320.059491076,places=2)
        legacy=gui.analyze({'team':'PIT','period':'current','current_start':'invalid','current_name':'Old era'})['summary']
        self.assertEqual(legacy,baseline)

    def test_all_spread_franchises_render(self):
        for team in TEAMS:
            with self.subTest(team=team):
                self.assertEqual(self.client.get('/',query_string={'team':team,'market':'spread'}).status_code,200)

    def test_refresh_requires_csrf(self):
        self.assertEqual(self.client.post('/refresh').status_code,403)

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
