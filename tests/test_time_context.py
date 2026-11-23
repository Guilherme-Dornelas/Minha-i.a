import unittest
from datetime import datetime, timedelta, timezone

from guilherme_ai.time_context import (
    current_datetime_context,
    resolve_relative_dates,
)


class TimeContextTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(
            2026,
            11,
            20,
            21,
            19,
            tzinfo=timezone(timedelta(hours=-3)),
        )

    def test_current_time_is_normalized_to_sao_paulo(self):
        utc_time = datetime(2026, 11, 21, 0, 19, tzinfo=timezone.utc)
        self.assertEqual(
            current_datetime_context(utc_time),
            "2026-11-20T21:19-03:00 [America/Sao_Paulo]",
        )

    def test_resolves_previous_weekday_and_relative_dates(self):
        resolved = resolve_relative_dates(
            "Quem morreu na quinta-feira? O fato aconteceu ontem.",
            self.now,
        )
        self.assertIn("Quinta considerada = 19/11/2026", resolved)
        self.assertIn("Ontem = 19/11/2026", resolved)

    def test_resolves_requested_periods_including_month_boundaries(self):
        resolved = resolve_relative_dates(
            "Notícias de anteontem, hoje, semana passada, mês passado e últimos três dias",
            self.now,
        )
        self.assertIn("Anteontem = 18/11/2026", resolved)
        self.assertIn("Hoje = 20/11/2026", resolved)
        self.assertIn("Semana passada = 09/11/2026 a 15/11/2026", resolved)
        self.assertIn("Mês passado = 01/10/2026 a 31/10/2026", resolved)
        self.assertIn("Últimos 3 dias = 18/11/2026 a 20/11/2026", resolved)

    def test_explicit_dates_are_labeled_as_past_today_or_future(self):
        resolved = resolve_relative_dates(
            "19/11/2026, 20/11/2026 e 21/11/2026",
            self.now,
        )
        self.assertIn(
            "Data explícita 19/11/2026 = passada em relação a 20/11/2026",
            resolved,
        )
        self.assertIn(
            "Data explícita 20/11/2026 = hoje em relação a 20/11/2026",
            resolved,
        )
        self.assertIn(
            "Data explícita 21/11/2026 = futura em relação a 20/11/2026",
            resolved,
        )


if __name__ == "__main__":
    unittest.main()
