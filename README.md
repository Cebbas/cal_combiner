# Cal Combiner – Home Assistant custom integration

Slår ihop flera kalender-entiteter (Google, CalDAV, lokala, iCal-URL – allt som
redan syns som `calendar.*` i HA) till EN kalender som:

- syns som en vanlig kalender i Home Assistants kalendervy
- går att prenumerera på från valfri kalenderapp (Google Kalender, Apple
  Kalender, Outlook m.fl.) via en hemlig ICS-länk ("Lägg till kalender via URL") –
  read-only
- går att redigera direkt i kalenderappen via ETT delat CalDAV-konto för hela
  installationen (Apple Kalender, Thunderbird, DAVx5 på Android – se
  avsnitt 6; Google Kalender saknar stöd för externa CalDAV-konton och
  förblir read-only oavsett)
- automatiskt skapar sin egen skrivbara kalender som nya event hamnar i som
  standard – du behöver inte skapa eller peka ut någon kalender själv
- stödjer återkommande event (upprepning), inklusive att redigera/ta bort ett
  enstaka tillfälle i en serie
- låter dig sätta egen ikon och bild

Letar du efter aktivitetssensorer (`binary_sensor`/`sensor` byggda från
filtrerad kalenderaktivitet, t.ex. "är ett Zoo-event på gång just nu")? Det
är numera en egen, fristående integration:
[Cal Activity Sensors](https://github.com/Cebbas/cal_activity_sensors) – den
pratar bara med vanliga `calendar.*`-entiteter och behöver inte Cal Combiner
installerat.

## 1. Installation

**Manuellt:**
1. Kopiera mappen `cal_combiner/` till `config/custom_components/` på din
   HA-installation (t.ex. via Samba, SSH eller Studio Code Server-tillägget).
2. Starta om Home Assistant.

**Via HACS (custom repository):**
1. HACS → tre punkter uppe till höger → *Custom repositories*
2. Lägg till `https://github.com/Cebbas/cal_combiner` med kategori
   *Integration*
3. Sök upp "Cal Combiner" i HACS och installera, starta om HA.

## 2. Konfigurera Cal Combiner

Inställningar → Enheter & tjänster → Lägg till integration → **Cal Combiner**

- **Namn**: namnet på den sammanslagna kalendern
- **Extra källkalendrar**: valfritt vid skapandet – du kan lägga till fler
  `calendar.*`-entiteter senare i sidopanelen
- **Ikon/bild**: valfritt, går även att ändra senare

Det finns inget "skrivmål" att välja och ingen separat kalenderentitet att
hålla reda på: den sammanslagna kalendern *är* skrivmålet. Nya event du
lägger till (i panelen, i HA:s kalendervy eller via CalDAV) sparas direkt på
den, sida vid sida med de sammanslagna eventen från dina källkalendrar.

Vill du slå ihop en extern iCal-URL (t.ex. en skolkalender)? Lägg till den
först som en egen källa via Inställningar → Enheter & tjänster → Lägg till
integration → **Remote Calendar** (`ics`), och lägg sedan till den entiteten
som en extra källkalender här.

Efter konfigurering får du en notis i HA med en `feed.ics`-länk. Den länken
lägger du till i valfri kalenderapp under "prenumerera/lägg till via URL"
(byt `https://` mot `webcal://` om appen kräver det formatet – panelen visar
båda varianterna färdiga att kopiera). Om ingen "Home Assistant-URL" är
konfigurerad i Inställningar → System → Nätverk kan länken inte byggas
fullständigt; sätt en URL där och öppna panelen igen.

## 3. Sidopanel

Efter installation dyker **Cal Combiner** upp som en egen flik i sidomenyn
(kräver adminkonto), uppdelad i två flikar:

**Kalendrar**
- Se alla dina sammanslagna kalendrar som kort, med ikon och valfri bild
- Lägg till/ta bort källkalendrar via en rullgardin (inte en lång lista med
  kryssrutor) – välj en kalender och klicka "Lägg till"
- Sätt/ta bort filter per källa (inkludera/uteslut ord, regex, skiftläge)
- Skapa helt nya sammanslagna kalendrar utan att behöva peka ut något
  skrivmål – det skapas automatiskt
- Kopiera ICS-prenumerationslänken (både https och webcal) direkt
- Se en logg över senaste ändringarna direkt på kortet

**Server**
- Kontouppgifterna för det delade CalDAV-kontot (avsnitt 6): server-URL,
  användarnamn och lösenord, färdiga att kopiera in i kalenderappen
- Kryssa i vilka sammanslagna kalendrar som ska exponeras via CalDAV-kontot
  – nya kalendrar kryssas i automatiskt när de skapas, du kan kryssa ur dem
  här om du inte vill dela en viss kalender

Panelen pratar med backend via ett eget websocket-API (`cal_combiner/...`)
och kräver inte att du går igenom den vanliga inställningsdialogen, men den
gamla vägen (Inställningar → Enheter & tjänster → Konfigurera) fungerar
fortfarande parallellt.

## 4. Redigera och ta bort event

Du kan redigera och ta bort event direkt från den sammanslagna kalendern
(t.ex. via HA:s kalendervy) – event som kommer från en källkalender skickas
automatiskt vidare dit, medan event du skapat direkt på den sammanslagna
kalendern uppdateras/tas bort på plats. Om källkalendern inte stödjer
redigering/borttagning (många read-only källor, t.ex. de flesta
prenumerationskalendrar) får du ett tydligt felmeddelande istället för att
det bara misslyckas tyst.

## 5. (reserverat)

*(Numret är avsiktligt ledigt – se historiken i `CHANGELOG.md` om du undrar
varför.)*

## 6. Redigera direkt i kalenderappen (CalDAV)

Prenumerationslänken i avsnitt 2 (webcal/ICS) är alltid **read-only** – det
är en fil kalenderappen bara läser med jämna mellanrum, det finns ingen väg
tillbaka för ändringar. För att kunna skapa, redigera och ta bort event
**direkt i kalenderappen** och få det synkat till Cal Combiner behövs ett
riktigt CalDAV-konto istället.

Till skillnad från prenumerationslänken (en per sammanslagen kalender) finns
det bara **ETT CalDAV-konto för hela Cal Combiner-installationen** – du
lägger till det en gång i kalenderappen, och varje sammanslagen kalender du
kryssat i under fliken **Server** i panelen dyker upp som en egen kalender
i appen, precis som ett vanligt Google- eller iCloud-konto med flera
kalendrar.

**Vilka appar stödjer detta?**

| App | Skapa/redigera/ta bort direkt i appen? |
|---|---|
| Home Assistants egen kalendervy | Ja – fungerar redan idag, inget extra behövs |
| Apple Kalender (macOS/iOS) | Ja – lägg till som **Övrigt → Lägg till CalDAV-konto** |
| Thunderbird | Ja – **Ny kalender → På nätverket → CalDAV** |
| Android + [DAVx5](https://www.davx5.com/) | Ja |
| Google Kalender (webb, iOS, Android) | **Nej** – Google har ingen funktion för att lägga till ett externt CalDAV-konto i någon av sina appar. Det är en begränsning i Google Kalender, inte något som går att lösa härifrån. Använd prenumerationslänken (read-only) eller redigera via HA:s egen kalendervy istället |
| Outlook | Nej som standard (kräver tredjeparts-tillägg) |

**Kontouppgifter** (fliken Server i panelen):
- **Server-URL**
- **Användarnamn**: valfritt värde, kontrolleras inte
- **Lösenord**: en hemlig, delad token – samma för alla kalendrar i kontot

Precis som prenumerationslänken kräver detta att en "Home Assistant-URL" är
konfigurerad (Inställningar → System → Nätverk), och att den är nåbar från
enheten du lägger till kontot på (HTTPS rekommenderas starkt om du gör detta
över internet, eftersom lösenordet annars skickas i klartext).

Skapar du ett återkommande event (upprepning) i kalenderappen sparas det med
sin upprepningsregel – att redigera eller ta bort bara ett enstaka
tillfälle i en serie stöds också, både från appen och från HA:s egen
kalendervy.

## 7. Filtrera event per källa

Inställningar → Enheter & tjänster → Cal Combiner → **Konfigurera** →
**Redigera filter per källa**. Välj vilken källkalender du vill filtrera,
sätt sedan:

- **Fält att matcha mot**: `any` (titel+beskrivning+plats), `summary`,
  `description` eller `location`
- **Inkludera bara event som innehåller**: t.ex. `Zoo, Djurpark` – då tas
  BARA event som matchar något av orden med
- **Uteslut event som innehåller**: t.ex. `Zoo` – då tas ALLA event UTOM de
  som matchar bort
- **Tolka orden som regex**: av som standard (enkel textmatchning). Slå på
  om du vill använda regex-mönster, t.ex. `\bKund\b` för att bara matcha hela
  ordet "Kund"
- **Skiftlägeskänslig**: av som standard (Zoo = zoo = ZOO)

Du kan sätta både include och exclude samtidigt. Lämna båda tomma för att ta
bort filtret för den källan igen. Filtret gäller bara den valda
källkalendern – andra källor i samma sammanslagna kalender är opåverkade.

### Byt namn på event per källa

I panelen (fliken Kalendrar → klicka på en källa under "Filter per källa")
kan du även lägga till en eller flera **namnbytesregler** för samma källa,
längst ner i samma ruta som filtret. Varje regel är ett regex-mönster +
vad det ska ersättas med, och reglerna körs i den ordning du lagt till dem
– på titeln, efter filtreringen, innan eventet visas (kalendervy,
ICS-prenumeration och CalDAV får alla samma namn).

Exempel: en importerad lagkalender ger titlar som `Träning // Herrsenior -
BK Ljungsbro` och `Match: BK Ljungsbro - IFK Västervik (Div 3 Nordöstra
Götaland, herr 2026) // Herrsenior - BK Ljungsbro`. Två enkla regler (ingen
regex-grupp behövs):

1. Mönster ` // .*$`, ersätt med *(tomt)* – stryker " // Lagnamn" på slutet
   av alla event från källan
2. Mönster ` \([^)]*\)$`, ersätt med *(tomt)* – stryker en avslutande
   parentes, t.ex. "(Div 3 Nordöstra Götaland, herr 2026)"

Det ger `Träning` respektive `Match: BK Ljungsbro - IFK Västervik`. Vill du
dessutom byta ut just "Träning" mot något annat, lägg till en tredje regel
med mönster `^Träning$` och ersätt med t.ex. `Fotbolls Träning`.

Det vanliga config-flowet (Inställningar → Enheter & tjänster → Konfigurera)
har bara filter, inte namnbyte – namnbyte finns än så länge bara i panelen.

## 8. Flera sammanslagna kalendrar

Integrationen har inget "endast en instans"-krav – lägg till **Cal Combiner**
flera gånger (Inställningar → Enheter & tjänster → Lägg till integration →
Cal Combiner) för att bygga t.ex. en "Familj"-kalender och en separat
"Jobb"-kalender, var och en med sin egen skrivbara kalender, egna källor,
filter, ikon/bild och ICS-länk. Alla dyker upp som separata kalendrar i
samma delade CalDAV-konto (avsnitt 6), en per instans du kryssar i under
Server-fliken.

## 9. Om en källa inte svarar

Om en källkalender inte går att nå (t.ex. utgången Google-token) exkluderas
den tillfälligt och du får en notis i HA om vilken källa det gäller. Notisen
försvinner automatiskt igen så fort källan svarar normalt. Det syns även i
kalenderns "Senaste händelser"-logg i panelen.

## 10. Bygga vidare

Se `IDEAS.md` för en avbockningsbar lista över vad som är gjort och vad som
återstår.

## Filstruktur

```
custom_components/
  cal_combiner/
    __init__.py       # setup, ICS-länk-notis, registrerar panel + ws-api + CalDAV
    calendar.py         # sammanslagen kalender-entitet + delad filter-/routningslogik
    own_calendar.py        # lagring (inkl. upprepning) för event varje sammanslagen kalender äger direkt
    caldav.py                # delat CalDAV-konto (PROPFIND/REPORT/GET/PUT/DELETE), en server, flera kalendrar
    activity_log.py             # liten rullande händelselogg per kalender, visas i panelen
    config_flow.py                # UI för att lägga till/ändra en sammanslagen kalender
    http.py                         # /api/cal_combiner/... ICS-feed
    panel.py                          # registrerar sidopanelen + statiska filer
    ws_api.py                           # websocket-kommandon som panelen använder
    const.py
    manifest.json
    hacs.json
    strings.json
    translations/
      en.json
      sv.json
    www/
      cal-combiner-panel.js  # sidopanelens UI (vanilla JS, två flikar: kalendrar/server)
```
