"""Catalogue brand -> de.wikipedia brand article, and the title prefixes that
identify that brand's model articles.

Why candidates rather than one title: on de.wikipedia the bare marque name is
often not the marque article. "Jaguar" is the animal, "Hyundai" the chaebol,
"Volvo" the truck/industrial group. The crawl resolves the candidate list in
order and takes the first title that exists and is not a disambiguation page,
so a rename or redirect upstream degrades to the next candidate instead of
silently crawling the wrong article.

``link_prefixes`` is the filter for plain wikilinks inside a model section
(sections.extract_model_links). It is per-brand because sub-marques break the
simple "starts with the brand name" rule: Land Rover's models include "Range
Rover …", Mercedes' include "Mercedes-AMG …".

Keys are the exact ``Catalogue.brand`` values (app/catalogue/brands.py is the
source of truth for those spellings) — not free text.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BrandArticle:
    brand: str
    candidates: tuple[str, ...]
    link_prefixes: tuple[str, ...]
    # Additional articles crawled ALONGSIDE the resolved candidate, each run
    # through section-matching independently and their links unioned. Needed
    # where one marque's range is split across two articles that don't link to
    # each other — MG's historical British range and its modern Chinese range
    # are separate de.wikipedia articles, and the catalogue contains both eras.
    extra_articles: tuple[str, ...] = ()


BRAND_ARTICLES: dict[str, BrandArticle] = {
    # "Mercedes-Benz" is a marque overview whose vehicle section is a
    # routing table by vehicle TYPE (Pkw / Vans / Lkw / Bus) — crawling it
    # yields 7 category articles and no models. "Mercedes-Benz-Pkw" is the
    # actual passenger-car index (~150 model articles under "Produktlinien").
    # It has no "Modell*" heading, so it escalates to Phase 1 by design.
    "Mercedes-Benz": BrandArticle(
        "Mercedes-Benz",
        ("Mercedes-Benz-Pkw", "Mercedes-Benz", "Mercedes-Benz Group"),
        ("Mercedes-Benz", "Mercedes-AMG", "Mercedes-Maybach", "Mercedes Benz"),
    ),
    "Kia": BrandArticle("Kia", ("Kia", "Kia Corporation", "Kia Motors"), ("Kia",)),
    "Renault": BrandArticle("Renault", ("Renault",), ("Renault", "Alpine")),
    "Opel": BrandArticle("Opel", ("Opel",), ("Opel",)),
    "Land Rover": BrandArticle(
        "Land Rover",
        ("Land Rover", "Land Rover (Marke)", "Jaguar Land Rover"),
        ("Land Rover", "Range Rover", "Landrover"),
    ),
    # "Fiat" is a disambiguation page and "Fiat S.p.A." is the holding
    # company (no model list at all). "Fiat (Marke)" is the marque article,
    # and its "Modelle der Marke Fiat" section fuzzy-matches normally.
    "Fiat": BrandArticle(
        "Fiat",
        ("Fiat (Marke)", "Fiat Automobiles", "Fiat S.p.A."),
        ("Fiat",),
    ),
    "Jaguar": BrandArticle(
        "Jaguar",
        ("Jaguar Cars", "Jaguar (Automarke)", "Jaguar Land Rover"),
        ("Jaguar",),
    ),
    "Volvo": BrandArticle(
        "Volvo",
        ("Volvo Cars", "Volvo Car Corporation", "Volvo Personvagnar", "Volvo"),
        ("Volvo",),
    ),
    "Dacia": BrandArticle("Dacia", ("Dacia", "Automobile Dacia"), ("Dacia",)),
    "Hyundai": BrandArticle(
        "Hyundai",
        ("Hyundai Motor Company", "Hyundai", "Hyundai Motor"),
        ("Hyundai",),
    ),
    # ---- added at full-scope expansion (all catalogue brands bar the
    # near-zero-volume ones in EXCLUDED_BRANDS). Candidate order matters: the
    # first that exists and isn't a disambiguation page wins, so put the
    # marque article ahead of the holding-company/disambiguation name.
    "Volkswagen": BrandArticle(
        "Volkswagen",
        ("Volkswagen", "Volkswagen Pkw", "Volkswagen AG"),
        ("Volkswagen", "VW"),
    ),
    "Audi": BrandArticle("Audi", ("Audi", "Audi AG"), ("Audi",)),
    "Škoda": BrandArticle(
        "Škoda", ("Škoda Auto", "Škoda"), ("Škoda", "Skoda")
    ),
    "Seat": BrandArticle(
        "Seat", ("Seat (Unternehmen)", "SEAT", "Seat"), ("Seat", "SEAT")
    ),
    "Toyota": BrandArticle(
        "Toyota", ("Toyota", "Toyota Motor Corporation"), ("Toyota",)
    ),
    # The "BMW" article is the corporate one — its "Produktpalette" section
    # lists only the current range (15 links). "BMW (Automarke)" is the marque
    # article, with per-era Modellgeschichte sections (160 links).
    "BMW": BrandArticle(
        "BMW", ("BMW (Automarke)", "BMW"), ("BMW",)
    ),
    "Porsche": BrandArticle(
        "Porsche",
        ("Porsche", "Porsche AG", "Dr. Ing. h. c. F. Porsche"),
        ("Porsche",),
    ),
    "Peugeot": BrandArticle("Peugeot", ("Peugeot",), ("Peugeot",)),
    "Alfa Romeo": BrandArticle("Alfa Romeo", ("Alfa Romeo",), ("Alfa Romeo",)),
    "Citroën": BrandArticle(
        "Citroën", ("Citroën",), ("Citroën", "Citroen")
    ),
    "Jeep": BrandArticle("Jeep", ("Jeep", "Jeep (Marke)"), ("Jeep",)),
    "Nissan": BrandArticle(
        "Nissan", ("Nissan", "Nissan Motor"), ("Nissan", "Datsun")
    ),
    "Abarth": BrandArticle("Abarth", ("Abarth", "Abarth & C."), ("Abarth",)),
    # "Mini (Automarke)" is brand history with ~2 model links; the model list
    # is on "Mini (BMW Group)".
    "MINI": BrandArticle(
        "MINI",
        ("Mini (BMW Group)", "Mini (Automarke)"),
        ("Mini", "MINI"),
    ),
    # The "Maserati" article's "Serienfahrzeuge" section has 4 links; the
    # dedicated list article enumerates 54.
    "Maserati": BrandArticle(
        "Maserati",
        ("Liste von Maserati-Serienfahrzeugen", "Maserati"),
        ("Maserati",),
    ),
    "Mitsubishi": BrandArticle(
        "Mitsubishi", ("Mitsubishi Motors", "Mitsubishi"), ("Mitsubishi",)
    ),
    "Cupra": BrandArticle("Cupra", ("Cupra", "Cupra (Automarke)"), ("Cupra",)),
    "Honda": BrandArticle("Honda", ("Honda", "Honda Motor"), ("Honda",)),
    "DS": BrandArticle(
        "DS", ("DS Automobiles", "DS (Automarke)"), ("DS",)
    ),
    "Lancia": BrandArticle("Lancia", ("Lancia",), ("Lancia",)),
    "Chevrolet": BrandArticle("Chevrolet", ("Chevrolet",), ("Chevrolet",)),
    # "MG (Automarke)" does not exist and "MG Rover Group" redirects to the
    # Rover article — the first mapping attempt crawled Rover by accident.
    # The marque is split in two: modern (Chinese-owned, what the catalogue's
    # 162 rows actually are) and historical British.
    "MG": BrandArticle(
        "MG",
        ("MG (chinesische Automarke)", "MG (britische Automarke)"),
        ("MG",),
        extra_articles=("MG (britische Automarke)",),
    ),
    "SsangYong": BrandArticle(
        "SsangYong",
        ("SsangYong Motor Company", "KG Mobility", "SsangYong"),
        ("SsangYong", "KG Mobility"),
    ),
    "Subaru": BrandArticle("Subaru", ("Subaru",), ("Subaru",)),
    "Infiniti": BrandArticle("Infiniti", ("Infiniti",), ("Infiniti",)),
    "smart": BrandArticle(
        "smart",
        ("Smart (Automarke)", "Smart (Automobilhersteller)", "Smart"),
        ("Smart",),
    ),
    "Geely": BrandArticle("Geely", ("Geely", "Geely Auto"), ("Geely",)),
    "Suzuki": BrandArticle("Suzuki", ("Suzuki", "Suzuki Motor"), ("Suzuki",)),
}

# Catalogue brands deliberately NOT crawled: ~28 rows between them, which is
# not worth an article-mapping entry or the crawl requests
# (docs/WIKIPEDIA_CO2_PLAN.md §Explicitly out of scope). Kept as data so the
# exclusion is auditable rather than implicit in an omission.
EXCLUDED_BRANDS: tuple[str, ...] = ("BAIC", "Forthing", "Foton", "Isuzu", "Lynk & Co")

# Default crawl scope: every mapped brand. This was the ten highest-volume
# brands during the first build; it is now all catalogue brands bar
# EXCLUDED_BRANDS. Order is roughly by catalogue row volume so that a run
# interrupted partway has covered the brands that matter most.
PHASE_0_BRANDS: tuple[str, ...] = (
    "Volkswagen", "Audi", "Škoda", "Opel", "Seat", "Toyota", "Kia",
    "Mercedes-Benz", "BMW", "Renault", "Fiat", "Porsche", "Peugeot", "Volvo",
    "Hyundai", "Dacia", "Alfa Romeo", "Citroën", "Jeep", "Land Rover",
    "Nissan", "Abarth", "MINI", "Maserati", "Mitsubishi", "Cupra", "Jaguar",
    "Honda", "DS", "Lancia", "Chevrolet", "MG", "SsangYong", "Subaru",
    "Infiniti", "smart", "Geely", "Suzuki",
)


def get_brand_article(brand: str) -> BrandArticle:
    try:
        return BRAND_ARTICLES[brand]
    except KeyError:
        raise KeyError(
            f"No de.wikipedia article mapping for brand {brand!r}. "
            f"Known: {sorted(BRAND_ARTICLES)}"
        ) from None
