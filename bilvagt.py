#!/usr/bin/env python3
"""Bilvagten - gratis daglig bilsøgning til GitHub Actions.

Søger på de sider, der tillader automatiske søgninger i deres robots.txt
(carandclassic.com, classic-trader.com og finn.no), gemmer hvad der er set i
data/seen.json, bygger en webside i docs/index.html og sender evt. en mail
med de nye biler.

Kræver: requests, beautifulsoup4
"""
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.abspath(__file__))
AGENTS_FILE = os.path.join(ROOT, "agenter.json")
SEEN_FILE = os.path.join(ROOT, "data", "seen.json")
PAGE_FILE = os.path.join(ROOT, "docs", "index.html")

UA = "Bilvagten/1.0 (personlig bilsøgning; github.com)"
HEADERS = {"User-Agent": UA, "Accept-Language": "da,en;q=0.8"}
DELAY = 2.0            # sekunder mellem kald til samme side
MAX_NEW_DETAILS = 40   # maks. annoncesider der hentes pr. side pr. kørsel
ACTIVE_DAYS = 7        # en annonce regnes som aktiv, hvis den er set inden for så mange dage
NORDIC = {"DK", "NO", "SE"}

COUNTRY_NAMES = {
    "DK": "Danmark", "NO": "Norge", "SE": "Sverige", "DE": "Tyskland", "NL": "Holland",
    "BE": "Belgien", "FR": "Frankrig", "IT": "Italien", "ES": "Spanien", "AT": "Østrig",
    "CH": "Schweiz", "PL": "Polen", "FI": "Finland", "GB": "Storbritannien", "UK": "Storbritannien",
    "IE": "Irland", "PT": "Portugal", "CZ": "Tjekkiet", "LU": "Luxembourg", "GR": "Grækenland",
    "EE": "Estland", "HU": "Ungarn", "US": "USA",
}
COUNTRY_WORDS = {
    "denmark": "DK", "danmark": "DK", "norway": "NO", "norge": "NO", "sweden": "SE", "sverige": "SE",
    "germany": "DE", "deutschland": "DE", "netherlands": "NL", "belgium": "BE", "france": "FR",
    "italy": "IT", "spain": "ES", "austria": "AT", "switzerland": "CH", "poland": "PL",
    "finland": "FI", "united kingdom": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "ireland": "IE", "portugal": "PT", "luxembourg": "LU", "greece": "GR", "estonia": "EE",
    "hungary": "HU", "czech": "CZ", "usa": "US", "united states": "US",
}

# ---------------------------------------------------------------- sider
SITES = [
    {
        "key": "carandclassic",
        "name": "carandclassic.com",
        "search": "https://www.carandclassic.com/search?q={q}",
        "ad": re.compile(r"^https://www\.carandclassic\.com/(?:car|l|la)/C\d+/?$|^https://www\.carandclassic\.com/make-an-offer/[\w-]+$", re.I),
        "id": lambda u: (re.search(r"/(C\d+)", u) or re.search(r"([\w]+)$", u)).group(1).lower(),
        "country": None,
    },
    {
        "key": "classictrader",
        "name": "classic-trader.com",
        "search": "https://www.classic-trader.com/uk/cars/search?fulltext={q}",
        "ad": re.compile(r"^https://www\.classic-trader\.com/uk/cars/listing/[\w-]+/[\w-]+/[\w-]+/\d{4}/\d+/?$", re.I),
        "id": lambda u: re.search(r"/(\d+)/?$", u).group(1),
        "country": None,
    },
    {
        "key": "finn",
        "name": "finn.no",
        "search": "https://www.finn.no/mobility/search/car?q={q}",
        "ad": re.compile(r"^https://www\.finn\.no/mobility/item/\d+/?$", re.I),
        "id": lambda u: re.search(r"/(\d+)/?$", u).group(1),
        "country": "NO",
    },
]

# ---------------------------------------------------------------- hjælpere
_robots = {}
_last_call = {}
session = requests.Session()
session.headers.update(HEADERS)


def allowed(url):
    """Respekter sidens robots.txt."""
    host = urlparse(url).scheme + "://" + urlparse(url).netloc
    rp = _robots.get(host)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            r = session.get(host + "/robots.txt", timeout=20)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])
        _robots[host] = rp
    return rp.can_fetch(UA, url)


def fetch(url):
    if not allowed(url):
        raise PermissionError("robots.txt tillader ikke " + url)
    host = urlparse(url).netloc
    wait = DELAY - (time.time() - _last_call.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_call[host] = time.time()
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def num(s):
    """'12.500,00' / '33,464' / '£ 18 995' / 52000.0 -> heltal."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    s = str(s).strip()
    s = re.sub(r"[.,]\d{1,2}$", "", s)  # fjern øre/cent
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else None


def ld_objects(soup):
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                out.append(o)
                for k in ("@graph", "itemListElement", "item", "offers", "mainEntity"):
                    v = o.get(k)
                    if isinstance(v, list):
                        stack.extend(v)
                    elif isinstance(v, dict):
                        stack.append(v)
            elif isinstance(o, list):
                stack.extend(o)
    return out


def meta(soup, prop):
    t = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return norm(t.get("content")) if t and t.get("content") else ""


def guess_country(text):
    low = " " + text.lower() + " "
    for word, code in COUNTRY_WORDS.items():
        if " " + word in low:
            return code
    return ""


# ---------------------------------------------------------------- søgning
def search_links(site, query):
    url = site["search"].format(q=quote_plus(query))
    soup = BeautifulSoup(fetch(url), "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"]).split("?")[0].split("#")[0].rstrip("/")
        if site["ad"].match(href) and href not in links:
            links.append(href)
    return links


def ad_details(site, url):
    soup = BeautifulSoup(fetch(url), "html.parser")
    title = meta(soup, "og:title") or norm(soup.title.string if soup.title else "")
    desc = meta(soup, "og:description")
    image = meta(soup, "og:image")
    price = currency = km = year = None
    country = site["country"] or ""
    for o in ld_objects(soup):
        offers = o.get("offers")
        if isinstance(offers, dict):
            price = price or num(offers.get("price") or offers.get("lowPrice"))
            currency = currency or offers.get("priceCurrency")
            addr = ((offers.get("availableAtOrFrom") or {}).get("address") or {})
            if isinstance(addr, dict) and not country:
                country = str(addr.get("addressCountry") or "")[:2].upper()
        if o.get("price") and not price:
            price = num(o.get("price"))
            currency = currency or o.get("priceCurrency")
        odo = o.get("mileageFromOdometer")
        if isinstance(odo, dict) and not km:
            km = num(odo.get("value"))
            if km and str(odo.get("unitCode", "")).upper() in ("SMI", "MI"):
                km = round(km * 1.609)
        for k in ("vehicleModelDate", "productionDate", "modelDate", "dateVehicleFirstRegistered"):
            if o.get(k) and not year:
                m = re.search(r"(19|20)\d{2}", str(o.get(k)))
                year = int(m.group(0)) if m else None
        if isinstance(o.get("image"), str) and not image:
            image = o["image"]
    text = norm(soup.get_text(" "))[:20000]
    if not year:
        m = re.search(r"\b(19[5-9]\d|20[0-2]\d)\b", title) or re.search(r"\b(19[5-9]\d|20[0-2]\d)\b", desc)
        year = int(m.group(0)) if m else None
    if not km:
        m = re.search(r"(\d{1,3}(?:[ .,]\d{3})+|\d{2,6})\s?(km|miles|mil)\b", desc + " " + text, re.I)
        if m:
            km = num(m.group(1))
            if m.group(2).lower() == "miles":
                km = round(km * 1.609)
            elif m.group(2).lower() == "mil" and site["country"] in ("NO", "SE"):
                km = km * 10  # skandinavisk mil = 10 km
    if not price:
        cur = r"(€|£|kr\.?|NOK|SEK|DKK|EUR|GBP)"
        amount = r"(\d{1,3}(?:[ .,\u00a0]\d{3})+|\d{4,7})"
        hay = desc + " " + text
        m = re.search(cur + r"\s?" + amount, hay)
        pair = (m.group(1), m.group(2)) if m else None
        if not pair:
            m = re.search(amount + r"\s?" + cur, hay)
            pair = (m.group(2), m.group(1)) if m else None
        if pair:
            price = num(pair[1])
            kr = {"NO": "NOK", "SE": "SEK"}.get(site["country"] or "", "DKK")
            currency = {"€": "EUR", "£": "GBP", "kr": kr, "kr.": kr}.get(pair[0], pair[0])
    if not country:
        country = guess_country(desc + " " + text[:3000])
    sold = bool(re.search(r"\b(sold|solgt|verkauft|såld)\b", (title + " " + desc).lower()))
    return {
        "title": title, "image_url": image if image.startswith("https://") else "",
        "price": price, "currency": currency or "", "km": km, "year": year,
        "country": country or "", "sold": sold,
    }


def relevant(agent, title):
    t = " " + title.lower() + " "
    if not all(w.lower() in t for w in agent.get("skal_indeholde", [])):
        return False
    return not any(w.lower() in t for w in agent.get("udeluk", []))


def variant(agent, title):
    t = title.lower()
    if "turbo s" in t:
        return "Turbo S"
    if "turbo" in t:
        return "Turbo"
    return agent["navn"]


# ---------------------------------------------------------------- side og mail
CSS = """
:root{--bg:#f3f4f6;--surface:#fff;--fg:#1b1d22;--muted:#5f6571;--line:#dcdfe5;--accent:#b3202a;--new-bg:#fbe9ea}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--surface:#1c1f24;--fg:#e8eaee;--muted:#9aa1ad;--line:#2d3139;--accent:#e2545c;--new-bg:#3a1d20;color-scheme:dark}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 Archivo,system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:28px 16px 48px;display:grid;gap:24px}
.code{font:700 12px "Archivo Narrow","Arial Narrow",sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
h1{font:700 clamp(30px,6vw,44px)/1.05 "Archivo Narrow","Arial Narrow",sans-serif;margin:4px 0}
h2{font:700 26px "Archivo Narrow","Arial Narrow",sans-serif;margin:8px 0 0}
h3{font:700 18px "Archivo Narrow","Arial Narrow",sans-serif;margin:0;color:var(--muted)}
.sub{color:var(--muted);margin:0;max-width:65ch}
.status{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:13px;color:var(--muted);border-block:1px solid var(--line);padding:10px 0}
.status b{color:var(--fg)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden;display:flex;flex-direction:column}
.card.new{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.card img,.card .noimg{width:100%;aspect-ratio:4/3;object-fit:cover;background:var(--line);display:block}
.card .noimg{display:grid;place-items:center;color:var(--muted);font-size:13px}
.body{padding:10px 12px 12px;display:grid;gap:4px;font-size:14px}
.body .t{font-weight:600}
.body .m{color:var(--muted);font-variant-numeric:tabular-nums}
.pill{display:inline-block;font-size:11px;font-weight:600;padding:1px 7px;border-radius:99px;background:var(--accent);color:var(--surface);margin-right:6px}
a{color:var(--accent)}
.empty{background:var(--surface);border:1px dashed var(--line);border-radius:8px;padding:16px;color:var(--muted)}
section{display:grid;gap:12px}
"""


def fmt(n):
    return f"{n:,}".replace(",", ".") if isinstance(n, int) else "—"


def card(l, today):
    new = l["first_seen"] == today
    img = (f'<img src="{html.escape(l["image_url"])}" alt="" loading="lazy" referrerpolicy="no-referrer">'
           if l.get("image_url") else '<div class="noimg">Intet billede</div>')
    price = f'{fmt(l["price"])} {html.escape(l.get("currency") or "")}' if l.get("price") else "Pris ikke oplyst"
    land = COUNTRY_NAMES.get(l.get("country", ""), l.get("country") or "Ukendt land")
    return (f'<a class="card{" new" if new else ""}" href="{html.escape(l["url"])}" target="_blank" rel="noopener" style="text-decoration:none;color:inherit">'
            f'{img}<div class="body"><div class="t">{"<span class=pill>Ny</span>" if new else ""}{html.escape(l.get("model") or "")} · {l.get("year") or "—"}</div>'
            f'<div class="m">{fmt(l.get("km"))} km · {price}</div>'
            f'<div class="m">{html.escape(land)} · {html.escape(l["site"])} · fundet {l["first_seen"]}</div></div></a>')


def build_page(agents, seen, status, today):
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=ACTIVE_DAYS)).strftime("%Y-%m-%d")
    parts = []
    for a in agents:
        items = [l for l in seen.values() if l.get("agent") == a["navn"] and l["last_seen"] >= cutoff and not l.get("sold")]
        items.sort(key=lambda l: (l["first_seen"], l.get("year") or 0), reverse=True)
        nordic = [l for l in items if l.get("country") in NORDIC]
        rest = [l for l in items if l.get("country") not in NORDIC]
        sec = [f'<section><h2>{html.escape(a["navn"])}</h2>']
        for label, lst in (("Danmark, Norge &amp; Sverige", nordic), ("Resten af Europa", rest)):
            sec.append(f"<h3>{label} · {len(lst)}</h3>")
            sec.append('<div class="grid">' + "".join(card(l, today) for l in lst) + "</div>" if lst
                       else '<div class="empty">Ingen biler her lige nu.</div>')
        sec.append("</section>")
        parts.append("".join(sec))
    st = " ".join(f"<span>{html.escape(k)}: <b>{html.escape(v)}</b></span>" for k, v in status.items())
    now = datetime.now(ZoneInfo("Europe/Copenhagen")).strftime("%d-%m-%Y kl. %H:%M")
    return f"""<!doctype html><html lang="da"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bilvagten</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo+Narrow:wght@700&family=Archivo:wght@400;600&display=swap">
<style>{CSS}</style></head><body><div class="wrap">
<header><span class="code">Gratis daglig søgning · GitHub Actions</span><h1>Bilvagten</h1>
<p class="sub">Biler fundet på carandclassic.com, classic-trader.com og finn.no. Røde kort er nye i dag. Kort forsvinder, når annoncen ikke er set i {ACTIVE_DAYS} dage.</p></header>
<div class="status"><span>Opdateret <b>{now}</b></span>{st}</div>
{"".join(parts)}
</div></body></html>"""


def send_mail(new_items):
    user, pw, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS"), os.environ.get("MAIL_TO")
    if not (user and pw and to) or not new_items:
        return
    lines = []
    for l in sorted(new_items, key=lambda l: (l.get("country") not in NORDIC, l["agent"])):
        price = f'{fmt(l["price"])} {l.get("currency") or ""}' if l.get("price") else "pris ikke oplyst"
        land = COUNTRY_NAMES.get(l.get("country", ""), l.get("country") or "ukendt land")
        lines.append(f'{l["agent"]}: {l.get("model")} · {l.get("year") or "?"} · {fmt(l.get("km"))} km · {price} · {land}\n  {l["url"]}')
    body = f"{len(new_items)} nye biler fundet af Bilvagten:\n\n" + "\n\n".join(lines)
    page = os.environ.get("PAGE_URL")
    if page:
        body += f"\n\nSe alle biler: {page}"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"Bilvagten: {len(new_items)} nye biler"
    msg["From"], msg["To"] = user, to
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", "465"))) as s:
        s.login(user, pw)
        s.sendmail(user, [x.strip() for x in to.split(",")], msg.as_string())


# ---------------------------------------------------------------- kørsel
def main():
    today = datetime.now(ZoneInfo("Europe/Copenhagen")).strftime("%Y-%m-%d")
    agents = json.load(open(AGENTS_FILE, encoding="utf-8"))
    seen = json.load(open(SEEN_FILE, encoding="utf-8")) if os.path.exists(SEEN_FILE) else {}
    status, new_items = {}, []
    for site in SITES:
        found = 0
        try:
            for a in agents:
                links = search_links(site, a["soeg"])
                details_left = MAX_NEW_DETAILS
                for url in links:
                    key = f'{site["key"]}-{site["id"](url)}'
                    if key in seen:
                        seen[key]["last_seen"] = today
                        if not seen[key].get("skip"):
                            found += 1
                        continue
                    if details_left <= 0:
                        break
                    details_left -= 1
                    try:
                        d = ad_details(site, url)
                    except (requests.RequestException, PermissionError) as e:
                        print(f"  springer over {url}: {e}", file=sys.stderr)
                        continue
                    if d["sold"] or not relevant(a, d["title"]):
                        seen[key] = {"skip": True, "title": d["title"], "last_seen": today}
                        continue
                    item = dict(d, url=url, site=site["name"], agent=a["navn"], model=variant(a, d["title"]),
                                first_seen=today, last_seen=today)
                    seen[key] = item
                    new_items.append(item)
                    found += 1
            status[site["name"]] = f"{found} bil" + ("" if found == 1 else "er")
        except PermissionError:
            status[site["name"]] = "ikke tilladt (robots.txt)"
        except requests.RequestException as e:
            status[site["name"]] = "fejl: " + type(e).__name__
        print(site["name"], status[site["name"]])
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(PAGE_FILE), exist_ok=True)
    json.dump(seen, open(SEEN_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    open(PAGE_FILE, "w", encoding="utf-8").write(build_page(agents, seen, status, today))
    print(f"{len(new_items)} nye biler")
    try:
        send_mail(new_items)
    except Exception as e:  # mailfejl må ikke stoppe resten
        print("Kunne ikke sende mail:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
