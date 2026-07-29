# Cal Combiner – idélista / checklista

## Grundfunktioner
- [x] Slå ihop flera kalender-entiteter (Google/CalDAV/lokal/iCal-URL) till en kalender
- [x] Syns i Home Assistants inbyggda kalendervy
- [x] Prenumererbar ICS-länk (webcal://) för valfri kalenderapp, skyddad med hemlig token
- [x] Skapa nya events via den sammanslagna kalendern (skrivs till kalenderns egen, automatiskt skapade kalender)
- [x] Stöd för flera separata sammanslagna kalendrar (en integrationsinstans per kalender)
- [x] Varje sammanslagen kalender skapar automatiskt sin egen skrivbara kalender som standard-skrivmål – inget separat "Local Calendar"-steg krävs längre
- [x] Man behöver inte välja/skapa någon kalender alls för att lägga till en aktivitetssensor

## Filter per källa
- [x] Inkludera event som innehåller vissa ord (t.ex. bara "Zoo")
- [x] Exkludera event som innehåller vissa ord (t.ex. allt utom "Zoo")
- [x] Välj vilket fält som matchas: titel / beskrivning / plats / alla
- [x] Skiftlägeskänslig eller ej
- [x] Regex-läge (mönster istället för ren textmatchning)

## Redigering
- [x] Redigera event via den sammanslagna kalendern (skickas vidare till rätt källa)
- [x] Ta bort event via den sammanslagna kalendern (skickas vidare till rätt källa)
- [x] `create_event` anropar källkalenderns entitet direkt istället för att gå via `calendar.create_event`-tjänsten (undviker schemamismatch mellan entitets- och tjänste-nycklar)

## Robusthet
- [x] Options-flow uppdaterat för att undvika kommande HA-deprecation (self.config_entry)
- [x] Felindikator när en källkalender inte svarar (attribut `failed_sources` + notis vid nytt fel, notis försvinner när felet är löst)
- [x] ICS-prenumerationslänken byggs med `homeassistant.helpers.network.get_url` (extern → intern → IP-fallback) istället för att bara läsa `external_url`/`internal_url`, så länken faktiskt fungerar när inget av dem är satt fullständigt
- [ ] Repair-issue (istället för bara persistent_notification) så felet syns i Inställningar → Repairs
- [ ] Retry/backoff om en källa svarar ostabilt istället för att direkt räknas som "failed" för hela pollningsintervallet

## Aktivitetssensorer
- [x] Bygg fristående sensorer (`binary_sensor`/`sensor`) från filtrerade kalenderaktiviteter
- [x] Återanvänder samma filtertyp som kalenderfiltren (fält, inkludera/uteslut, regex, skiftläge)
- [x] `binary_sensor`: valbart läge – på/av just nu, ELLER på om ett matchande event inträffar någon gång samma dag
- [x] `sensor`: state = aktuellt/nästa matchande event + attribut (antal idag, plats, start/slut)
- [x] Hanterbara via både sidopanelen och vanliga Inställningar → Enheter & tjänster
- [ ] Fler sensor-typer, t.ex. "minuter kvar till nästa match" eller "antal matchande event denna vecka"
- [ ] Möjlighet att koppla en automation-mall direkt från panelen (förslag på trigger-YAML)

## Utseende
- [x] Egen ikon per kalender och per aktivitetssensor
- [x] Egen bild per kalender och per aktivitetssensor, uppladdad direkt i panelen via HA:s inbyggda bilduppladdning (`/api/image/upload`, samma mekanism som Person/Area-bilder) istället för en URL-textfält
- [ ] Bildfältet i det vanliga config-flowet (Inställningar → Enheter & tjänster) är fortfarande en textrad för URL, eftersom HA saknar en generisk bilduppladdnings-selector för config flows – uppladdning finns bara i sidopanelen

## Sidopanel
- [x] Två flikar: Kalendrar och Sensorer, i en stil som liknar HA:s inbyggda paneler
- [x] Varje kalender/sensor får sin egen under-flik (pill-tabs) under Kalendrar/Sensorer, plus en "+"-flik för att skapa ny
- [x] Rullgardin + "Lägg till"-knapp för att välja källkalendrar istället för en lång kryssrutelista
- [x] Filter (inkludera/uteslut/regex/skiftläge) redigerbara direkt i panelen
- [x] Kopiera ICS-länk (både https och webcal) direkt i panelen
- [x] Ikon- och bildväljare för både kalendrar och sensorer
- [x] Kortrenderingen är felskyddad (try/catch per kort) så ett trasigt kort visar ett läsbart felmeddelande istället för att lämna hela fliken tom
- [ ] Drag-och-släpp / färgkodning per källa i panelen (mer avancerad frontend, likt vacuum scheduler)
- [ ] Visa `failed_sources`-status i panelen (just nu bara synligt som entity-attribut/notis)

## Trevligt-att-ha (ej påbörjat)
- [ ] Device-gruppering för entiteterna i UI:t
- [ ] Färgkodning per källkalender i HA:s inbyggda kalendervy (utanför panelen)
- [ ] Konfigurerbart pollningsintervall (idag hårdkodat till 5 min) via options flow eller panelen
- [ ] Stöd för att skriva uppdateringar tillbaka till en annan källa än ursprungskällan (flytta event mellan kalendrar)

## Buggar (fixade)
- [x] Panelen renderades i light DOM utan `attachShadow`, så `<style>:host{...}</style>` matchade ingenting (våra egna storleksregler gällde aldrig) samtidigt som våra vanliga tagg-/klassväljare (`button`, `select`, `input[type="text"]`, `h1`, `*`) läckte ut och gällde globalt i HELA Home Assistant-appen, inte bara panelen. Fixat genom att faktiskt använda `this.attachShadow({mode:"open"})` och rendera allt inuti shadow-roten.

## Kända begränsningar
- Recurring events hanteras som redan expanderade instanser inom tidsfönstret – redigering av en hel serie sker i källkalendern, inte i merge-kalendern
- Den egna, automatiskt skapade kalendern stödjer inte återkommande event (RRULE) – varje event lagras som ett enskilt tillfälle
- `calendar.get_events`/entitetsmetoderna för update/delete kräver en tillräckligt ny Home Assistant-version (2023.8+ ungefär) som stödjer `return_response` och entity-baserad update/delete
