# Cal Combiner – Home Assistant custom integration

Slår ihop flera kalender-entiteter (Google, CalDAV, lokala, iCal-URL – allt som
redan syns som `calendar.*` i HA) till EN kalender som:

- syns som en vanlig kalender i Home Assistants kalendervy
- går att prenumerera på från valfri kalenderapp (Google Kalender, Apple
  Kalender, Outlook m.fl.) via en hemlig ICS-länk ("Lägg till kalender via URL") –
  read-only
- går att redigera direkt i kalenderappen via ett riktigt CalDAV-konto (Apple
  Kalender, Thunderbird, DAVx5 på Android – se avsnitt 6; Google Kalender saknar
  stöd för externa CalDAV-konton och förblir read-only oavsett)
- automatiskt skapar sin egen skrivbara kalender som nya event hamnar i som
  standard – du behöver inte skapa eller peka ut någon kalender själv
- stödjer återkommande event (upprepning), inklusive att redigera/ta bort ett
  enstaka tillfälle i en serie
- låter dig sätta egen ikon och bild, både för kalendrar och för
  aktivitetssensorer

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
→ **Sammanslagen kalender**

- **Namn**: namnet på den sammanslagna kalendern
- **Extra källkalendrar**: valfritt vid skapandet – du kan lägga till fler
  `calendar.*`-entiteter senare i sidopanelen
- **Ikon/bild**: valfritt, går även att ändra senare

Det finns inget "skrivmål" att välja längre och ingen separat kalenderentitet
att hålla reda på: den sammanslagna kalendern *är* skrivmålet. Nya event du
lägger till (i panelen, i HA:s kalendervy eller via `calendar.create_event`)
sparas direkt på den, sida vid sida med de sammanslagna eventen från dina
källkalendrar.

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
- Lägg till/ta bort källkalendrar via en rullgardin (inte längre en lång
  lista med kryssrutor) – välj en kalender och klicka "Lägg till"
- Sätt/ta bort filter per källa (inkludera/uteslut ord, regex, skiftläge)
- Skapa helt nya sammanslagna kalendrar utan att behöva peka ut något
  skrivmål – det skapas automatiskt
- Kopiera ICS-prenumerationslänken (både https och webcal) direkt

**Sensorer**
- Bygg **aktivitetssensorer** (se avsnitt 4) med samma sorts filter, ikon och
  bild
- Välj om `binary_sensor`:n ska vara "på" när ett event pågår just nu, eller
  när ett matchande event inträffar någon gång samma dag

Panelen pratar med backend via ett eget websocket-API (`cal_combiner/...`)
och kräver inte att du går igenom den vanliga inställningsdialogen, men den
gamla vägen (Inställningar → Enheter & tjänster → Konfigurera) fungerar
fortfarande parallellt för både kalendrar och aktivitetssensorer.

## 4. Aktivitetssensorer

Utöver sammanslagna kalendrar kan du bygga fristående sensorer som filtrerar
fram en viss sorts aktivitet ur en eller flera källkalendrar – med exakt
samma filtertyp som används för kalenderfiltren (fält att matcha mot,
inkludera/uteslut ord, regex, skiftläge), samt egen ikon och bild.

Varje aktivitetssensor kan skapa:

- **`binary_sensor`**: `on` beroende på vilket läge du valt –
  antingen "ett event pågår just nu" eller "ett event inträffar någon gång
  idag" – med attribut `current_event`, `next_event`, `next_start`,
  `failed_sources`
- **`sensor`**: state = titeln på pågående (eller näst kommande) matchande
  event, attribut `matches_today`, `next_start`, `next_end`, `location`,
  `failed_sources`

Exempel: en sensor med källa = din Google-kalender och filter
"inkludera: Zoo" ger en `binary_sensor.zoo_besok` som är `on` när ett
Zoo-event pågår (eller hela dagen zoo-eventet finns, om du valt det läget),
perfekt att trigga automationer på (t.ex. stäng av larmet, sätt på
"borta"-läge, eller skicka en påminnelse).

Skapa/redigera/ta bort dem enklast via sidopanelen (avsnitt 3), eller via
Inställningar → Enheter & tjänster → Lägg till integration → Cal Combiner →
Aktivitetssensor.

## 5. Redigera och ta bort event

Du kan redigera och ta bort event direkt från den sammanslagna kalendern
(t.ex. via HA:s kalendervy) – event som kommer från en källkalender skickas
automatiskt vidare dit, medan event du skapat direkt på den sammanslagna
kalendern uppdateras/tas bort på plats.

## 6. Redigera direkt i kalenderappen (CalDAV)

Prenumerationslänken i avsnitt 2 (webcal/ICS) är alltid **read-only** – det
är en fil kalenderappen bara läser med jämna mellanrum, det finns ingen väg
tillbaka för ändringar. För att kunna skapa, redigera och ta bort event
**direkt i kalenderappen** och få det synkat till Cal Combiner behövs ett
riktigt CalDAV-konto istället, vilket panelen också ger dig (samma kort som
prenumerationslänken, under "Redigera direkt i kalenderappen").

**Vilka appar stödjer detta?**

| App | Skapa/redigera/ta bort direkt i appen? |
|---|---|
| Home Assistants egen kalendervy | Ja – fungerar redan idag, inget extra behövs |
| Apple Kalender (macOS/iOS) | Ja – lägg till som **Övrigt → Lägg till CalDAV-konto** |
| Thunderbird | Ja – **Ny kalender → På nätverket → CalDAV** |
| Android + [DAVx5](https://www.davx5.com/) | Ja |
| Google Kalender (webb, iOS, Android) | **Nej** – Google har ingen funktion för att lägga till ett externt CalDAV-konto i någon av sina appar. Det är en begränsning i Google Kalender, inte något som går att lösa härifrån. Använd prenumerationslänken (read-only) eller redigera via HA:s egen kalendervy istället |
| Outlook | Nej som standard (kräver tredjeparts-tillägg) |

**Kontouppgifter** (från panelen, per sammanslagen kalender):
- **Server-URL**
- **Användarnamn**: valfritt värde, kontrolleras inte
- **Lösenord**: samma hemliga token som prenumerationslänken använder

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

## 8. Flera sammanslagna kalendrar

Integrationen har inget "endast en instans"-krav – lägg till **Cal Combiner**
flera gånger (Inställningar → Enheter & tjänster → Lägg till integration →
Cal Combiner) för att bygga t.ex. en "Familj"-kalender och en separat
"Jobb"-kalender, var och en med sin egen skrivbara kalender, egna källor,
filter, ikon/bild och ICS-länk.

## 9. Om en källa inte svarar

Om en källkalender inte går att nå (t.ex. utgången Google-token) exkluderas
den tillfälligt och du får en notis i HA om vilken källa det gäller. Notisen
försvinner automatiskt igen så fort källan svarar normalt.

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
    caldav.py                # minimal CalDAV-server (PROPFIND/REPORT/GET/PUT/DELETE) för tvåvägssync
    activity.py               # delad coordinator + tidshjälpfunktioner för aktivitetssensorer
    activity_log.py             # liten rullande händelselogg per kalender/sensor, visas i panelen
    binary_sensor.py               # aktivitetssensor: på/av (nu eller idag)
    sensor.py                        # aktivitetssensor: aktuellt/nästa event
    config_flow.py                     # UI för att lägga till/ändra (meny: kalender/sensor)
    http.py                              # /api/cal_combiner/... ICS-feed
    panel.py                               # registrerar sidopanelen + statiska filer
    ws_api.py                                # websocket-kommandon som panelen använder
    const.py
    manifest.json
    hacs.json
    strings.json
    translations/
      en.json
      sv.json
    www/
      cal-combiner-panel.js  # sidopanelens UI (vanilla JS, två flikar: kalendrar/sensorer)
```
