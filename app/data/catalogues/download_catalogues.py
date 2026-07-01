"""
Download all PPMV catalogue Excel files from carina.gov.hr.

Usage:
    python -m app.data.catalogues.download_catalogues
"""

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://carina.gov.hr"
INDEX_URL = (
    "https://carina.gov.hr/trosarinsko-postupanje/dodatne-informacije-o-trosarinama-i-posebnim-porezima"
    "/posebni-porez-na-motorna-vozila-3650/informativni-kalkulator-za-izracun-ppmv-a"
    "/prodajne-cijene-od-01-07-2013/4841"
)

OUT_DIR = Path(__file__).parent
MANIFEST = OUT_DIR / "manifest.jsonl"
ERRORS_LOG = OUT_DIR / "errors.log"

CONCURRENCY = 20


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


async def fetch(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        resp = await client.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        return resp
    except httpx.HTTPError as e:
        await log_error(url, str(e))
        return None


_error_lock = asyncio.Lock()
_manifest_lock = asyncio.Lock()


async def log_error(url: str, message: str) -> None:
    async with _error_lock:
        with ERRORS_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{url}\t{message}\n")


async def log_manifest(entry: dict) -> None:
    async with _manifest_lock:
        with MANIFEST.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def already_downloaded(path: Path) -> bool:
    """Check disk first (fast), then manifest (handles partial runs)."""
    if path.exists():
        return True
    if not MANIFEST.exists():
        return False
    path_str = str(path)
    with MANIFEST.open(encoding="utf-8") as f:
        for line in f:
            try:
                if json.loads(line).get("path") == path_str:
                    return True
            except json.JSONDecodeError:
                pass
    return False


def extract_brand_links(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """
    Parse brand links from the main content <ul> that follows the page <h1>.
    Accepts every <a> inside it — no href pattern filtering — so short URLs
    like /audi-porsche-seat-skoda-volkswagen-cupra/4842 are not missed.
    """
    # Brand list lives in div.page_content > ul; pick the <ul> with the most links
    # (avoids accidentally selecting empty ULs or nav ULs higher on the page).
    candidates = soup.select("div.page_content ul") or soup.select("ul")
    if not candidates:
        return []
    ul = max(candidates, key=lambda u: len(u.select("a[href]")))

    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in ul.select("a[href]"):
        href = a["href"]
        if not href or href.startswith("javascript") or href.startswith("#"):
            continue
        full = urljoin(BASE_URL, href)
        slug = slugify(a.get_text())
        if slug and full not in seen:
            seen.add(full)
            links.append((slug, full))
    return links


def extract_year_links(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Return (year, absolute_url) pairs; matched purely on 4-digit anchor text."""
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = a["href"]
        if not href or href.startswith("javascript") or href.startswith("#"):
            continue
        text = a.get_text().strip().rstrip(".")
        if not re.fullmatch(r"\d{4}", text):
            continue
        full = urljoin(BASE_URL, href)
        if full not in seen:
            seen.add(full)
            links.append((text, full))
    return links


def extract_file_links(soup: BeautifulSoup, page_url: str) -> list[tuple[str, str]]:
    """Return (filename, absolute_url) for every .xls / .xlsx link on the page."""
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = a["href"]
        lower = href.lower()
        if not (lower.endswith(".xlsx") or lower.endswith(".xls")):
            continue
        full = urljoin(page_url, href)
        filename = Path(urlparse(full).path).name
        if full not in seen:
            seen.add(full)
            links.append((filename, full))
    return links


def next_page_url(current_url: str, soup: BeautifulSoup) -> str | None:
    """Return next-page URL, or None when Sljedeća is absent or disabled (javascript:;)."""
    for a in soup.select("a[href]"):
        if "Sljedeća" not in a.get_text():
            continue
        href = a["href"]
        if not href or href.startswith("javascript"):
            return None
        return urljoin(current_url, href)
    return None


async def download_file(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    url: str,
    dest: Path,
    brand: str,
    year: str,
    filename: str,
) -> None:
    if already_downloaded(dest):
        print(f"  [skip] {brand}/{year}/{filename}")
        return

    async with sem:
        print(f"[{brand}/{year}] downloading {filename}")
        try:
            resp = await client.get(url, follow_redirects=True, timeout=60)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"  [error] {filename}: {e}")
            await log_error(url, str(e))
            return

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    await log_manifest({"url": url, "path": str(dest), "brand": brand, "year": year, "filename": filename})


async def crawl_year_page(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    year_url: str,
    brand_slug: str,
    year: str,
) -> None:
    page_url = year_url
    tasks: list[asyncio.Task] = []

    while True:
        async with sem:
            resp = await fetch(client, page_url)
        if resp is None:
            break

        soup = BeautifulSoup(resp.text, "lxml")
        for filename, file_url in extract_file_links(soup, page_url):
            dest = OUT_DIR / brand_slug / year / filename
            tasks.append(asyncio.create_task(
                download_file(client, sem, file_url, dest, brand_slug, year, filename)
            ))

        next_url = next_page_url(page_url, soup)
        if not next_url:
            break
        page_url = next_url

    if tasks:
        await asyncio.gather(*tasks)


async def crawl_brand_page(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    brand_slug: str,
    brand_url: str,
) -> None:
    async with sem:
        resp = await fetch(client, brand_url)
    if resp is None:
        return

    soup = BeautifulSoup(resp.text, "lxml")
    year_links = extract_year_links(soup)

    if year_links:
        await asyncio.gather(*[
            crawl_year_page(client, sem, year_url, brand_slug, year)
            for year, year_url in year_links
        ])
        return

    # No year sub-pages — try files listed directly on brand page
    file_links = extract_file_links(soup, brand_url)
    if file_links:
        year = "misc"
        await asyncio.gather(*[
            asyncio.create_task(
                download_file(client, sem, file_url, OUT_DIR / brand_slug / year / filename,
                              brand_slug, year, filename)
            )
            for filename, file_url in file_links
        ])
        return

    msg = f"[SKIP] {brand_slug} {brand_url} — no year links or xlsx found"
    print(f"  [warn] {msg}")
    await log_error(brand_url, msg)


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; PPMV-catalogue-downloader/1.0; "
            "+https://github.com/MarioZitko/carPPMV)"
        )
    }

    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(headers=headers) as client:
        print(f"Fetching index: {INDEX_URL}")
        async with sem:
            resp = await fetch(client, INDEX_URL)
        if resp is None:
            print("Failed to fetch index page. Aborting.")
            return

        soup = BeautifulSoup(resp.text, "lxml")
        brand_links = extract_brand_links(soup)

        if not brand_links:
            print("No brand links found — check the page structure.")
            return

        print(f"Found {len(brand_links)} brands.")
        await asyncio.gather(*[
            crawl_brand_page(client, sem, slug, url)
            for slug, url in brand_links
        ])

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
