# Cal Combiner – idélista / checklista

## Grundfunktioner
- [x] Slå ihop flera kalender-entiteter (Google/CalDAV/lokal/iCal-URL) till en kalender
- [x] Syns i Home Assistants inbyggda kalendervy
- [x] Prenumererbar ICS-länk (webcal://) för valfri kalenderapp, skyddad med hemlig token
- [x] Skapa nya events via den sammanslagna kalendern (sparas direkt på den, inget separat "Local Calendar"-steg krävs)
- [x] Stöd för flera separata sammanslagna kalendrar (en integrationsinstans per kalender)
- [x] En enda kalenderentitet per sammanslagen kalender – den visar det sammanslagna resultatet OCH äger de event du skapar direkt på den (tidigare skapades en dold, förvirrande andra "(egen)"-entitet för det ändamålet, borttagen)
- [x] Aktivitetssensorerna är utbrutna till en egen integration ([Cal Activity Sensors](https://github.com/Cebbas/cal_activity_sensors)) – Cal Combiner har inget "entry type"-begrepp längre, varje instans är alltid en sammanslagen kalender

## Filter per källa
- [x] Inkludera event som innehåller vissa ord (t.ex. bara "Zoo")
- [x] Exkludera event som innehåller vissa ord (t.ex. allt utom "Zoo")
- [x] Välj vilket fält som matchas: titel / beskrivning / plats / alla
- [x] Skiftlägeskänslig eller ej
- [x] Regex-läge (mönster istället för ren textmatchning)
- [x] Byt namn på event per källa: en ordnad lista regex-ersättningsregler (`re.sub`-semantik, `\1` osv för matchade grupper) som körs efter filtreringen, innan eventet visas/exponeras (kalendervy, ICS-feed, CalDAV). Löser t.ex. att en importerad lagkalender alltid lägger till " // Lagnamn" på slutet, eller att "Träning" ska heta "Fotbolls Träning".
- [x] Varje namnbytesregel har ett eget fält-val (titel/beskrivning/plats) istället för att bara kunna byta titeln – en källa som proppar skräp i beskrivningen kan städas med samma regelmotor.
- [x] Namnbytesregler går att flytta upp/ner i panelen (↑/↓ per rad, numrerade) – viktigt eftersom regler som `^Träning$` eller `\([^)]*\)$` är ankrade och bara matchar efter att en tidigare regel städat bort resten av strängen; innan detta gick fel ordning bara att fixa genom att radera och lägga till reglerna på nytt.
- [x] Regex-mönster (filter och namnbyte) valideras server-side vid spara (`re.compile`) – ett trasigt mönster gav tidigare bara en tyst varning i HA:s log, nu ett synligt felmeddelande i panelen istället för att sparas som att det fungerade.
- [x] Förhandsgranska-knapp: visar vad ett inte-ännu-sparat filter/namnbyte skulle göra mot källans riktiga kommande event (60 dagar framåt, upp till 15 träffar, "före → efter" per event) innan man sparar.

## Redigering
- [x] Redigera event via den sammanslagna kalendern (skickas vidare till rätt källa)
- [x] Ta bort event via den sammanslagna kalendern (skickas vidare till rätt källa)
- [x] `create_event` anropar källkalenderns entitet direkt istället för att gå via `calendar.create_event`-tjänsten (undviker schemamismatch mellan entitets- och tjänste-nycklar)
- [x] Återkommande event (RRULE) på den egna kalendern: skapa, visa expanderat i rätt datumintervall, redigera/ta bort hela serien eller bara ett enstaka tillfälle (`recurrence_id`, lagras som `exdates`/`overrides` på master-eventet)
- [x] Redigering/borttagning av ett event från en källkalender som inte stödjer `UPDATE_EVENT`/`DELETE_EVENT` gav tidigare en okontrollerad krasch (t.ex. `AttributeError`) som bubblade upp som ett generiskt 500-fel/synkfel – både via HA:s egen kalendervy och via CalDAV. Källkalenderns `supported_features` kollas nu innan anropet; ett tydligt felmeddelande ("källkalendern stödjer inte redigering/borttagning") skickas tillbaka istället.

## Tvåvägssync (CalDAV)
- [x] Minimal CalDAV-server (`caldav.py`): OPTIONS, PROPFIND (fast egenskapsuppsättning), REPORT `calendar-query`, GET/PUT/DELETE per event – registrerat direkt på `hass.http.app.router` eftersom `HomeAssistantView` inte stödjer PROPFIND/REPORT
- [x] Basic Auth (valfritt användarnamn, ett delat lösenord för hela kontot) – egen kontroll i varje handler, går inte via HA:s inbyggda auth-middleware
- [x] Exponerar både egna event OCH sammanslagna externa källor (redigering av externa vidarebefordras till rätt källa, precis som HA:s egen kalendervy redan gör)
- [x] En CalDAV-resurs per event-uid; ett återkommande event serialiseras som master-VEVENT (med RRULE) + en VEVENT per enstaka-tillfälle-ändring (RECURRENCE-ID) i samma resurs – så representeras upprepning faktiskt i iCalendar-formatet, inte en resurs per tillfälle
- [x] **Ombyggt från "en CalDAV-server per sammanslagen kalender" till EN delad server för hela installationen** som en riktig calendar-home-set med flera kalender-collections (`/api/cal_combiner/dav` = principal, `/api/cal_combiner/dav/{entry_id}` = en kalender) – matchar hur riktiga CalDAV-konton fungerar (ett konto, flera kalendrar) istället för att tvinga ett separat konto per kalender
- [x] Delad inställningsfil (`{token, included, known}`) håller reda på lösenordet och vilka kalendrar som är exponerade; nya sammanslagna kalendrar kryssas i automatiskt första gången de skapas (oavsett om de skapas via panelen eller vanliga Inställningar), men respekteras om användaren senare kryssar ur dem
- [x] Kontouppgifter (server-URL/användarnamn/lösenord) + kryssruteliste för vilka kalendrar som ingår, synliga och redigerbara i en egen flik ("Server") i panelen
- [x] Verifierat med ett fristående interop-test (det oberoende Python-biblioteket `caldav`, inte vår egen kod) mot en riktig aiohttp-server i minnet: discovery, skapa/lista/ändra/ta bort engångsevent, återkommande event med RRULE, redigera ett enstaka tillfälle via RECURRENCE-ID, samt att fel/utebliven inloggning faktiskt avvisas (401) – **bör köras om** efter omskrivningen till delad server/flera collections, se Tester nedan
- [ ] `sync-collection` REPORT (inkrementell synk via versionsräknare + tombstones) – `calendar-query` täcker redan all funktionalitet, detta är bara en effektivitetsvinst klienter redan hanterar frånvaron av
- [ ] Google Kalender kan aldrig få detta – ingen "lägg till externt CalDAV-konto"-funktion finns i Google Kalender (webb/iOS/Android). Apple Kalender, Thunderbird och Android+DAVx5 stödjer det.

## Robusthet
- [x] Options-flow uppdaterat för att undvika kommande HA-deprecation (self.config_entry)
- [x] Felindikator när en källkalender inte svarar (attribut `failed_sources` + notis vid nytt fel, notis försvinner när felet är löst)
- [x] ICS-prenumerationslänken byggs med `homeassistant.helpers.network.get_url` (extern → intern → IP-fallback) istället för att bara läsa `external_url`/`internal_url`, så länken faktiskt fungerar när inget av dem är satt fullständigt
- [x] Tar bort kalenderns egen `OwnCalendarStore`-fil (`.storage/cal_combiner_own_<entry_id>`) när kalendern tas bort – tidigare låg alla dess egna event kvar på disk för evigt eftersom `ws_delete_entry` bara städade aktivitetsloggen och CalDAV-inställningarna, inte den egna kalenderns lagring
- [ ] Repair-issue (istället för bara persistent_notification) så felet syns i Inställningar → Repairs
- [ ] Retry/backoff om en källa svarar ostabilt istället för att direkt räknas som "failed" för hela pollningsintervallet
- [ ] Reauth-flow (`async_step_reauth`) så en källa med utgången token (t.ex. Google) kan återautentiseras direkt istället för att integrationen behöver tas bort och läggas till igen
- [ ] Diagnostics-stöd (`diagnostics.py`) för att exportera felsökningsdata via HA:s inbyggda diagnostics-gränssnitt

## Utseende
- [x] Egen ikon per kalender
- [x] Egen bild per kalender, uppladdad direkt i panelen via HA:s inbyggda bilduppladdning (`/api/image/upload`, samma mekanism som Person/Area-bilder) istället för en URL-textfält
- [ ] Bildfältet i det vanliga config-flowet (Inställningar → Enheter & tjänster) är fortfarande en textrad för URL, eftersom HA saknar en generisk bilduppladdnings-selector för config flows – uppladdning finns bara i sidopanelen

## Sidopanel
- [x] Två flikar: Kalendrar och Server (tidigare Kalendrar/Sensorer – Sensorer-fliken flyttade till Cal Activity Sensors egen panel när den blev en egen integration)
- [x] Varje kalender får sin egen under-flik (pill-tabs) under Kalendrar, plus en "+"-flik för att skapa ny
- [x] Rullgardin + "Lägg till"-knapp för att välja källkalendrar istället för en lång kryssrutelista
- [x] Filter (inkludera/uteslut/regex/skiftläge) redigerbara direkt i panelen
- [x] Kopiera ICS-länk (både https och webcal) direkt i panelen
- [x] Ikon- och bildväljare per kalender
- [x] Kortrenderingen är felskyddad (try/catch per kort) så ett trasigt kort visar ett läsbart felmeddelande istället för att lämna hela fliken tom
- [x] Serverfliken: CalDAV-kontouppgifter + kryssruteliste för vilka kalendrar som exponeras, med spara-knapp
- [ ] Drag-och-släpp / färgkodning per källa i panelen (mer avancerad frontend, likt vacuum scheduler)
- [x] Visa `failed_sources`-status i panelen – täcks av aktivitetsloggen (källa svarar inte/svarar igen loggas per kort)
- [x] Aktivitetslogg per kalender ("Senaste händelser"-lista längst ner på varje kort): källa/filter tillagd/ändrad/borttagen, event skapat/uppdaterat/borttaget, källa svarar inte/svarar igen. Egen liten `Store` per entry (`activity_log.py`), rullande fönster på de 50 senaste händelserna, städas när entryn tas bort.
- [x] "Synka nu"-knapp på varje kalenderkort som tvingar en omedelbar poll av alla källor (`coordinator.async_refresh()`) istället för att vänta upp till 5 minuter på nästa schemalagda uppdatering.

## Tester
- [ ] Automatiserade tester (unit-tester för filterlogik, ICS-generering, create/update/delete-vidarebefordran) – idag kör CI bara hassfest/HACS-validering, ingen faktisk testsvit
- [ ] Köra om CalDAV-interop-testet mot den nya delade servern (flera collections under samma konto, inte en collection per konto som tidigare)

## Trevligt-att-ha (ej påbörjat)
- [ ] Device-gruppering för entiteterna i UI:t
- [ ] Färgkodning per källkalender i HA:s inbyggda kalendervy (utanför panelen)
- [ ] Konfigurerbart pollningsintervall (idag hårdkodat till 5 min) via options flow eller panelen
- [ ] Stöd för att skriva uppdateringar tillbaka till en annan källa än ursprungskällan (flytta event mellan kalendrar)

## Buggar (fixade)
- [x] Panelen renderades i light DOM utan `attachShadow`, så `<style>:host{...}</style>` matchade ingenting (våra egna storleksregler gällde aldrig) samtidigt som våra vanliga tagg-/klassväljare (`button`, `select`, `input[type="text"]`, `h1`, `*`) läckte ut och gällde globalt i HELA Home Assistant-appen, inte bara panelen. Fixat genom att faktiskt använda `this.attachShadow({mode:"open"})` och rendera allt inuti shadow-roten.
- [x] `_parse(value)` i `own_calendar.py` (och motsvarande i `calendar.py`s källhämtning) provade `parse_datetime` före `parse_date`. `parse_datetime` "lyckas" även för en ren datumsträng (som en naiv midnatts-datetime), vilket bröt heldagsevent – de kraschade i `CalendarEvent`s validering ("Expected all values to have a timezone"). Hittades via ett test som faktiskt skapade ett heldags-återkommande event end-to-end. Fixat genom att pröva `parse_date` först.
- [x] Trailing-slash-mismatch i CalDAV: kontots URL delades ut med avslutande `/` men routen registrerades utan, så `PROPFIND` gav 404 direkt. Hittades via ett interop-test mot en riktig server (inte bara enhetstester av vår egen kod). Fixat genom att registrera båda varianterna.
- [x] Redigering/borttagning via CalDAV (och HA:s egen kalendervy) av ett event som kom från en källkalender utan stöd för uppdatering/borttagning kraschade okontrollerat istället för att ge ett tydligt fel – se "Redigering" ovan.

## Kända begränsningar
- Recurring events från EXTERNA källkalendrar hanteras som redan expanderade instanser inom tidsfönstret (så kommer `calendar.get_events` från HA:s egna kalenderintegrationer) – redigering av en hel serie sker i källkalendern, inte i merge-kalendern. Den egna kalendern (och CalDAV-servern) stödjer däremot fullt ut återkommande event, se "Redigering" och "Tvåvägssync" ovan.
- `calendar.get_events`/entitetsmetoderna för update/delete kräver en tillräckligt ny Home Assistant-version (2023.8+ ungefär) som stödjer `return_response` och entity-baserad update/delete
- CalDAV-servern implementerar den praktiska delmängden av RFC 4791 som Apple Kalender/Thunderbird/DAVx5 faktiskt använder (fast egenskapsuppsättning i PROPFIND istället för full dynamisk förhandling, ingen `sync-collection` än) – inte hela specifikationen
