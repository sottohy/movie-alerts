import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests
import vox_notify as v


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.getcwd()
        os.chdir(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(os.chdir, self.previous)
        self.baseline = {
            'avengers-doomsday': {'title': 'Avengers: Doomsday', 'url': '/movies/avengers-doomsday', 'genre': 'Action', 'booking_open': False},
            'horror': {'title': 'Horror film', 'url': '/movies/horror', 'genre': 'Horror', 'booking_open': False},
        }
        Path('state.json').write_text(json.dumps(self.baseline))
        self.current = copy.deepcopy(self.baseline)
        for film in self.current.values():
            film['booking_open'] = True
        for name, value in [('NTFY_HORROR_TOPIC', 'horror-topic'), ('NTFY_DOOMSDAY_TOPIC', 'doomsday-topic'), ('NTFY_ERROR_TOPIC', 'errors-topic')]:
            patcher = patch.object(v, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_schedules_do_not_consume_each_others_alerts(self):
        with patch.object(v, 'listing', side_effect=lambda _: copy.deepcopy(self.current)), patch.object(v, 'notify') as notify:
            self.assertEqual(v.run('doomsday'), 0)
            self.assertFalse(Path('state_horror.json').exists())
            self.assertEqual(notify.call_args.args[1], 'doomsday-topic')
            self.assertEqual(v.run('horror'), 0)
            self.assertEqual(notify.call_args.args[1], 'horror-topic')
            self.assertEqual(notify.call_count, 2)
            v.run('doomsday')
            v.run('horror')
            self.assertEqual(notify.call_count, 2)

    def test_blocking_reports_error_without_advancing_state(self):
        response = requests.Response()
        response.status_code = 403
        with patch.object(v, 'listing', side_effect=requests.HTTPError(response=response)), patch.object(v, 'notify_error') as error:
            self.assertEqual(v.run('doomsday'), 1)
            self.assertIn('403', error.call_args.args[1])
            self.assertFalse(Path('state_doomsday.json').exists())

    def test_empty_listing_is_failure(self):
        with patch.object(v, 'get', return_value='<html>Access denied</html>'):
            with self.assertRaisesRegex(RuntimeError, 'No films parsed'):
                v.listing('comingsoon')

    def test_missing_doomsday_reports_failure(self):
        with patch.object(v, 'listing', return_value={'horror': self.current['horror']}), patch.object(v, 'notify_error') as error:
            self.assertEqual(v.run('doomsday'), 1)
            error.assert_called_once()
            self.assertFalse(Path('state_doomsday.json').exists())

    def test_delivery_failure_does_not_advance_state(self):
        with patch.object(v, 'listing', side_effect=lambda _: copy.deepcopy(self.current)), patch.object(v, 'notify', side_effect=requests.Timeout()), patch.object(v, 'notify_error') as error:
            self.assertEqual(v.run('doomsday'), 1)
            error.assert_called_once()
            self.assertFalse(Path('state_doomsday.json').exists())

    def test_genre_failure_reports_error(self):
        self.current['horror']['genre'] = None
        Path('state.json').write_text('{}')
        with patch.object(v, 'listing', side_effect=lambda _: copy.deepcopy(self.current)), patch.object(v, 'fetch_genre', side_effect=RuntimeError('Genre parsing failed')), patch.object(v, 'notify_error') as error:
            self.assertEqual(v.run('horror'), 1)
            error.assert_called_once()
            self.assertFalse(Path('state_horror.json').exists())


if __name__ == '__main__':
    unittest.main()
