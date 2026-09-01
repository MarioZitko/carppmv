from datetime import date

import pytest

from app.data.catalogues.parse_date import parse_valid_from


@pytest.mark.parametrize("filename,expected", [
    # Pattern 1: DD.MM.YYYY
    ("BMW,MINI 11.01.2024..xlsx",       date(2024, 1, 11)),
    ("KIA 01.07.2013. KMAG.xlsx",       date(2013, 7, 1)),
    ("VOLVO 2013 11.11..xlsx",          date(2013, 11, 11)),
    ("Hyundai 2016 01.02..xlsx",        date(2016, 2, 1)),
    ("Volvo 01.02.2026..xlsx",          date(2026, 2, 1)),
    ("Geely 25.10.2023. najnovije.xlsx", date(2023, 10, 25)),
    ("Forthing 09.10.2023..xlsx",       date(2023, 10, 9)),

    # Pattern 2: YYYYMMDD
    ("Dacia 20130701.xls",             date(2013, 7, 1)),
    ("Autocommerce 20130701.xlsx",     date(2013, 7, 1)),

    # Pattern 3: YYYY DDMM
    ("PorscheCroatia 2020 0101.xlsx",  date(2020, 1, 1)),
    ("BMW 2020 0102.xlsx",             date(2020, 1, 2)),
    ("KIA 2019 0701.xlsx",             date(2019, 7, 1)),
    ("Renault 2014 1408.xls",          date(2014, 8, 14)),

    # Pattern 4: YYYY_MMDD
    ("toyota2015_0921.xlsx",           date(2015, 9, 21)),

    # Pattern 5: YYYY MM (month only → day=01)
    ("Dacia - 2014 01.xls",            date(2014, 1, 1)),

    # None cases
    ("HONDA CJENIK 60015 - 01.07..xls", None),

    # Edge: year out of range
    ("Brand 2012 0101.xlsx",           None),
    ("Brand 2031 0101.xlsx",           None),

    # Edge: invalid date (day 32)
    ("Brand 20130132.xlsx",            None),

    # Edge: month 13
    ("Brand 20131301.xlsx",            None),
])
def test_parse_valid_from(filename, expected):
    assert parse_valid_from(filename) == expected
