# Bilvagten

Gratis daglig søgning efter biler. GitHub kører et lille script hver morgen kl. 07:00 (06:00 om vinteren). Scriptet søger på **carandclassic.com**, **classic-trader.com** og **finn.no**. Resultatet lægges på en gratis webside med billeder, og du kan få en mail, når der dukker nye biler op.

Det koster ingenting. Repositoriet skal være *public* for at få gratis GitHub Pages og ubegrænset Actions-tid. Det er kun søgeresultaterne, der bliver offentlige. Din mailadgangskode ligger som en hemmelighed (secret) og er aldrig synlig.

## Sådan sætter du det op (ca. 10 minutter)

1. **Opret en GitHub-konto** på github.com, hvis du ikke har en.
2. **Lav et nyt repository.** Klik på **+** øverst til højre, vælg **New repository**, kald det `bilvagten`, vælg **Public** og tryk **Create repository**.
3. **Upload filerne.** På den tomme repo-side trykker du **uploading an existing file**. Træk alt indholdet fra den udpakkede mappe ind, også den skjulte mappe `.github`, og tryk **Commit changes**.
   - På Mac er `.github` skjult i Finder. Tryk `Cmd + Shift + .` for at se den.
4. **Giv scriptet lov til at gemme.** Gå til **Settings → Actions → General**. Under *Workflow permissions* vælger du **Read and write permissions** og trykker **Save**.
5. **Slå websiden til.** Gå til **Settings → Pages**. Under *Branch* vælger du `main` og mappen `/docs` og trykker **Save**. Efter et minut ligger siden på `https://DIT-BRUGERNAVN.github.io/bilvagten/`.
6. **Prøv det.** Gå til fanen **Actions**, vælg **Bilvagten** og tryk **Run workflow**. Efter 1–3 minutter er siden opdateret.

### Mail om nye biler (valgfrit)

Gmail kræver en særlig *app-adgangskode*:

1. Gå til myaccount.google.com/apppasswords (totrinsbekræftelse skal være slået til), lav en app-adgangskode med navnet "Bilvagten" og kopier de 16 tegn.
2. Gå til **Settings → Secrets and variables → Actions → New repository secret** i dit repo og opret disse tre:

| Navn | Værdi |
|---|---|
| `SMTP_USER` | din Gmail-adresse |
| `SMTP_PASS` | app-adgangskoden (16 tegn) |
| `MAIL_TO` | adressen, der skal have mailen (flere adresser kan adskilles med komma) |

Du får kun en mail, når der er nye biler. Bruger du ikke Gmail, kan du tilføje `SMTP_HOST` og `SMTP_PORT` (SSL) for din egen mailudbyder.

## Flere biler (søgeagenter)

Ret filen `agenter.json` direkte på GitHub (blyant-ikonet) og tilføj en blok pr. bil:

```json
[
  {
    "navn": "Porsche 944 Turbo / Turbo S",
    "soeg": "porsche 944 turbo",
    "skal_indeholde": ["944", "turbo"],
    "udeluk": ["944 s2", "924", "968", "dele", "parts"]
  },
  {
    "navn": "BMW E30 M3",
    "soeg": "bmw e30 m3",
    "skal_indeholde": ["m3"],
    "udeluk": ["e36", "e46", "dele", "parts"]
  }
]
```

- `soeg`: det, der skrives i sidernes søgefelt.
- `skal_indeholde`: ord, der alle skal stå i annoncens titel.
- `udeluk`: annoncer, hvor et af disse ord står i titlen, springes over.

## Godt at vide

- Scriptet overholder hver sides `robots.txt` og venter 2 sekunder mellem hvert kald. Hvis en side ændrer sine regler eller sit design, står det under "Status" øverst på websiden.
- Første kørsel kan finde biler, som Claude-søgningen ikke fandt. De er markeret som nye.
- GitHub kører somme tider planlagte jobs 5–30 minutter for sent.
- GitHub sætter planlagte jobs på pause, hvis der ikke er sket noget i et repository i 60 dage. Scriptets egne daglige commits tæller normalt med, men får du en mail fra GitHub om det, så tryk bare **Enable workflow** under Actions.

---

## Gratis mails fra de andre sider

mobile.de, autoscout24, bilbasen og bilweb tillader ikke automatiske søgninger. Det samme gælder måske blocket. Til gengæld har de selv gratis søgeagenter, der sender en mail eller en app-besked, når en ny bil passer til din søgning. Menunavnene kan ændre sig, men det fungerer sådan her:

| Side | Sådan gør du |
|---|---|
| **bilbasen.dk** | Log ind, søg efter "Porsche 944 Turbo" og tryk **Gem søgning**. Vælg mail eller notifikation. |
| **mobile.de** | Søg på *Porsche → 944*, skriv "Turbo" i fritekstfeltet og tryk **Suche speichern**. Slå e-mail-besked til (Suchauftrag). |
| **autoscout24** | Søg på *Porsche → 944*, skriv "Turbo" i søgefeltet og tryk **Suche speichern / Save search**. Slå e-mail-besked til. |
| **blocket.se** | Søg efter "porsche 944 turbo" under *Bilar* og tryk **Bevaka / Spara sökning**. Beskeden kommer i appen eller på mail. |
| **bytbil.com / bilweb.se** | Søg efter bilen og brug **Bevaka** eller **Spara sökning**, hvis siden har det. |
| **veteranposten.dk** | Se om siden har en søgeagent eller nyhedsmail. Ellers dækker bilbasen de fleste danske annoncer. |

Med alerts på disse sider og Bilvagten til de tre andre er alle 11 sider dækket gratis.
