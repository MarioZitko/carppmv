"""Hardcoded Croatian PPMV tax tables.

Sources (verified directly, not from secondary aggregators):
- Tables 1, 4 (value/VN-PC) and 2, 3, 5, 6 (eco/ON-EN): Uredba o načinu
  izračuna i visinama sastavnica za izračun posebnog poreza na motorna
  vozila, NN 156/22 (narodne-novine.nn.hr/clanci/sluzbeni/2022_12_156_2525.html)
- Depreciation table (Tablica 1 of the Pravilnik, note: same "Tablica 1"
  name as the Uredba's value table, but a different table in a different
  document) + post-180-month reduction rule + month-counting rule:
  Pravilnik o posebnom porezu na motorna vozila, čl. 9, pročišćeni tekst
  NN 1/17, 2/18, 1/20, 32/21 (cvh.hr/gradani/propisi-i-upute/pravilnici/
  zakon-o-posebnom-porezu-na-motorna-vozila/pravilnik-o-posebnom-porezu-
  na-motorna-vozila/)

Engine.py does a linear scan over these — tables are short (a handful of
brackets, or a few dozen for depreciation) and rebuilt rarely, so no need
for bisect/indexing.

Naming note: the Uredba has its OWN "Tablica 1" (value/VN-PC component,
vehicles reg. up to 31.12.2020) which is unrelated to the Pravilnik's
"Tablica 1" (depreciation %). To avoid collisions, this module suffixes
value/eco tables with their Uredba table number and depreciation with
its own descriptive name.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ValueBracket:
    """One row of a vrijednosna komponenta (VN/PC) table."""
    lower_bound_eur: float
    upper_bound_eur: float | None  # None = open-ended top bracket
    fixed_amount_vn: float
    percent_pc: float  # e.g. 0.03 for 3%


@dataclass(frozen=True)
class EcoBracket:
    """One row of an ekološka komponenta (ON/EN) table — NEDC or WLTP, per fuel."""
    lower_bound_co2: float
    upper_bound_co2: float | None
    fixed_amount_on: float
    rate_per_gkm_en: float


@dataclass(frozen=True)
class DepreciationBracket:
    """One row of the Pravilnik's Tablica 1 — % of as-new PPMV owed, by age
    in months. Half-open [min_months, max_months) to match the source's
    "X mjeseci do Y mjeseci" wording (e.g. "0 dana do 1 mjesec" = [0, 1))."""
    min_months: int
    max_months: int  # exclusive upper bound
    percent: float  # e.g. 0.4156 for 41.56%


# =====================================================================
# Uredba Tablica 1 — vrijednosna komponenta (VN/PC), vehicles registered
# up to 31.12.2020 (NEDC era)
# =====================================================================
VALUE_TABLE_PRE_2021: tuple[ValueBracket, ...] = (
    ValueBracket(0, 13272.28, 0, 0.0),
    ValueBracket(13272.29, 19908.42, 0, 0.0),
    ValueBracket(19908.43, 26544.56, 265.45, 0.03),
    ValueBracket(26544.57, 33180.70, 464.53, 0.05),
    ValueBracket(33180.71, 39816.84, 796.34, 0.07),
    ValueBracket(39816.85, 46452.98, 1260.87, 0.09),
    ValueBracket(46452.99, 53089.12, 1858.12, 0.11),
    ValueBracket(53089.13, 59725.26, 2588.10, 0.13),
    ValueBracket(59725.27, 66361.40, 3450.79, 0.14),
    ValueBracket(66361.41, 72997.54, 4379.85, 0.15),
    ValueBracket(72997.55, 79633.69, 5375.27, 0.16),
    ValueBracket(79633.70, None, 6437.05, 0.17),
)

# =====================================================================
# Uredba Tablica 4 — vrijednosna komponenta (VN/PC), vehicles registered
# from 1.1.2021 (WLTP era). Same price brackets as Table 1, different
# VN/% values (lower, since the eco component carries more weight here).
# =====================================================================
VALUE_TABLE_POST_2021: tuple[ValueBracket, ...] = (
    ValueBracket(0, 13272.28, 0, 0.0),
    ValueBracket(13272.29, 19908.42, 0, 0.0),
    ValueBracket(19908.43, 26544.56, 0, 0.0),
    ValueBracket(26544.57, 33180.70, 398.17, 0.03),
    ValueBracket(33180.71, 39816.84, 597.25, 0.05),
    ValueBracket(39816.85, 46452.98, 929.06, 0.07),
    ValueBracket(46452.99, 53089.12, 1393.59, 0.09),
    ValueBracket(53089.13, 59725.26, 1990.84, 0.11),
    ValueBracket(59725.27, 66361.40, 2720.82, 0.13),
    ValueBracket(66361.41, 72997.54, 3583.51, 0.15),
    ValueBracket(72997.55, 79633.69, 4578.93, 0.16),
    ValueBracket(79633.70, None, 5640.71, 0.17),
)

# =====================================================================
# Uredba Tablica 2 — ekološka komponenta, diesel, NEDC (reg. up to 31.12.2020)
# =====================================================================
ECO_TABLE_DIESEL_NEDC: tuple[EcoBracket, ...] = (
    EcoBracket(70, 85, 24.55, 7.30),
    EcoBracket(85, 120, 134.05, 23.23),
    EcoBracket(120, 140, 947.10, 152.63),
    EcoBracket(140, 170, 3999.70, 165.90),
    EcoBracket(170, 200, 8976.70, 179.18),
    EcoBracket(200, None, 14352.10, 192.45),
)

# =====================================================================
# Uredba Tablica 3 — ekološka komponenta, petrol/LPG/CNG/other non-diesel,
# NEDC (reg. up to 31.12.2020)
# =====================================================================
ECO_TABLE_PETROL_NEDC: tuple[EcoBracket, ...] = (
    EcoBracket(75, 90, 12.61, 4.65),
    EcoBracket(90, 120, 82.36, 17.92),
    EcoBracket(120, 140, 619.96, 59.73),
    EcoBracket(140, 170, 1814.56, 92.91),
    EcoBracket(170, 200, 4601.86, 159.27),
    EcoBracket(200, None, 9379.96, 172.54),
)

# =====================================================================
# Uredba Tablica 5 — ekološka komponenta, diesel, WLTP (reg. from 1.1.2021)
# =====================================================================
ECO_TABLE_DIESEL_WLTP: tuple[EcoBracket, ...] = (
    EcoBracket(95, 125, 11.28, 13.94),
    EcoBracket(125, 155, 429.48, 24.55),
    EcoBracket(155, 190, 1165.98, 146.00),
    EcoBracket(190, 215, 6275.98, 165.90),
    EcoBracket(215, 255, 10423.48, 179.18),
    EcoBracket(255, None, 17590.68, 205.72),
)

# =====================================================================
# Uredba Tablica 6 — ekološka komponenta, petrol/LPG/CNG/other non-diesel,
# WLTP (reg. from 1.1.2021)
# =====================================================================
ECO_TABLE_PETROL_WLTP: tuple[EcoBracket, ...] = (
    EcoBracket(95, 125, 3.32, 5.97),
    EcoBracket(125, 155, 182.42, 18.58),
    EcoBracket(155, 175, 739.82, 73.66),
    EcoBracket(175, 200, 2213.02, 96.22),
    EcoBracket(200, 240, 4618.52, 129.40),
    EcoBracket(240, None, 9794.52, 218.99),
)

# Uredba Tablica 7 (motorcycle/ATV displacement coefficients) intentionally
# not transcribed — out of scope per MASTER_PLAN_v7 §2.3. Motorcycles/ATVs
# use a different formula (PP = O × KO) which calculate_ppmv() does not
# implement; FuelType has no motorcycle variant.

# =====================================================================
# Pravilnik Tablica 1 — depreciation by age in months (čl. 9 st. 2)
# Full table, [min_months, max_months) half-open, source: CVH pročišćeni
# tekst NN 1/17, 2/18, 1/20, 32/21.
# =====================================================================
DEPRECIATION_TABLE: tuple[DepreciationBracket, ...] = (
    DepreciationBracket(0, 1, 0.96),
    DepreciationBracket(1, 2, 0.93),
    DepreciationBracket(2, 3, 0.90),
    DepreciationBracket(3, 4, 0.88),
    DepreciationBracket(4, 5, 0.86),
    DepreciationBracket(5, 6, 0.84),
    DepreciationBracket(6, 7, 0.82),
    DepreciationBracket(7, 8, 0.81),
    DepreciationBracket(8, 9, 0.80),
    DepreciationBracket(9, 10, 0.79),
    DepreciationBracket(10, 11, 0.78),
    DepreciationBracket(11, 12, 0.77),
    DepreciationBracket(12, 13, 0.7604),
    DepreciationBracket(13, 14, 0.7508),
    DepreciationBracket(14, 15, 0.7412),
    DepreciationBracket(15, 16, 0.7316),
    DepreciationBracket(16, 17, 0.7220),
    DepreciationBracket(17, 18, 0.7124),
    DepreciationBracket(18, 19, 0.7028),
    DepreciationBracket(19, 20, 0.6932),
    DepreciationBracket(20, 21, 0.6836),
    DepreciationBracket(21, 22, 0.6740),
    DepreciationBracket(22, 23, 0.6644),
    DepreciationBracket(23, 24, 0.65),
    DepreciationBracket(24, 26, 0.6358),
    DepreciationBracket(26, 28, 0.6216),
    DepreciationBracket(28, 30, 0.6074),
    DepreciationBracket(30, 32, 0.5932),
    DepreciationBracket(32, 34, 0.5790),
    DepreciationBracket(34, 36, 0.5648),
    DepreciationBracket(36, 38, 0.5506),
    DepreciationBracket(38, 40, 0.5364),
    DepreciationBracket(40, 42, 0.5222),
    DepreciationBracket(42, 44, 0.5080),
    DepreciationBracket(44, 46, 0.4938),
    DepreciationBracket(46, 48, 0.4796),
    DepreciationBracket(48, 51, 0.4636),
    DepreciationBracket(51, 54, 0.4476),
    DepreciationBracket(54, 57, 0.4316),
    DepreciationBracket(57, 60, 0.4156),
    DepreciationBracket(60, 64, 0.4006),
    DepreciationBracket(64, 68, 0.3856),
    DepreciationBracket(68, 72, 0.3706),
    DepreciationBracket(72, 78, 0.3526),
    DepreciationBracket(78, 84, 0.3346),
    DepreciationBracket(84, 90, 0.3166),
    DepreciationBracket(90, 96, 0.2986),
    DepreciationBracket(96, 102, 0.2806),
    DepreciationBracket(102, 108, 0.2626),
    DepreciationBracket(108, 114, 0.2446),
    DepreciationBracket(114, 120, 0.2266),
    DepreciationBracket(120, 132, 0.2172),
    DepreciationBracket(132, 144, 0.2112),
    DepreciationBracket(144, 156, 0.2052),
    DepreciationBracket(156, 168, 0.1992),
    DepreciationBracket(168, 180, 0.1932),
)

# Pravilnik čl. 9 st. 3: after 180 months, the depreciation percent is
# further reduced by 0.6 percentage points per full 12-month period,
# up to and including 360 months (at which point it is frozen).
DEPRECIATION_TABLE_MAX_MONTHS = 180
DEPRECIATION_REDUCTION_PER_12MO = 0.006
DEPRECIATION_FLOOR_MONTHS = 360
