#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from generate import normalize_salary


class SalaryNormalizationTests(unittest.TestCase):
    def test_eur_month_needs_no_original_label(self):
        self.assertEqual(normalize_salary(4000, "month", "EUR"), ("€4K/mo", ""))

    def test_convertible_currency_keeps_original(self):
        self.assertEqual(normalize_salary(4000, "month", "USD"), ("€3.7K/mo", "$4K/mo"))

    def test_unsupported_currency_preserves_original_without_fake_eur(self):
        self.assertEqual(normalize_salary(100000, "year", "PLN"), ("", "PLN 100K/yr"))


if __name__ == "__main__":
    unittest.main()
