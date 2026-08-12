# Changelog

Alla nämnvärda ändringar i Cal Combiner dokumenteras här.

## 0.0.12 – 2026-08-07
- Ny: namnbytesregler kan nu rikta titel, beskrivning eller plats (tidigare bara titeln).
- Ny: Förhandsgranska-knapp för filter/namnbyte – visar vad ett osparat filter/namnbyte faktiskt gör mot källans riktiga kommande event (60 dagar framåt) innan man sparar.
- Ny: "Synka nu"-knapp på varje kalenderkort som tvingar en omedelbar poll av alla källor istället för att vänta upp till 5 minuter.
- Fix: trasiga regex-mönster i filter eller namnbyte gav tidigare bara en tyst varning i HA:s log – valideras nu vid spara och ger ett tydligt felmeddelande i panelen.
- Fix: tar bort kalenderns egen `OwnCalendarStore`-fil när kalendern tas bort – tidigare låg alla dess egna event kvar på disk för evigt.

## 0.0.11 – 2026-08-07
- Ny: byt namn på event per källa – en ordnad lista regex-ersättningsregler per källkalender, redigerbar i panelen under samma ruta som filtret. Körs på titeln efter filtreringen, slår igenom i kalendervyn, ICS-prenumerationen och CalDAV.

## 0.0.10 – 2026-08-07
- Fix: loggar nu varje inkommande CalDAV-request (metod/path/statuskod) för att kunna skilja "request kom aldrig fram" (t.ex. en fjärrproxy som stryper WebDAV-metoder) från "request kom fram men misslyckades tyst", efter en rapport om att PUT (nya event) från en iPhone aldrig nådde servern.

## 0.0.9 – 2026-08-07
- Fix: kvarvarande aktivitetssensor-entries från innan 0.0.7 (den typen finns inte längre här, bara i Cal Activity Sensors) kraschade `async_setup_entry` med `KeyError: 'token'` eftersom bara sammanslagna kalendrar någonsin fick en token. De tas nu bort automatiskt vid uppstart med en notis om varför.

## 0.0.8 – 2026-08-04
- Städat: dokumentationen (README/IDEAS) synkad med 0.0.7:s omskrivning, och mappen `cal_activity_sensors/` flyttad ut ur det här repot till sitt eget.

## 0.0.7 – 2026-08-04
- Ändrat: aktivitetssensorerna (`binary_sensor`/`sensor`) är utbrutna till en egen, fristående integration – [Cal Activity Sensors](https://github.com/Cebbas/cal_activity_sensors). Cal Combiner har inget "entry type"-begrepp längre.
- Ändrat: CalDAV är ombyggt från en server per sammanslagen kalender till EN delad server för hela installationen, med en kalender-collection per sammanslagen kalender du kryssar i. Ny flik "Server" i panelen ersätter kontokortet som tidigare satt på varje kalenderkort. Nya kalendrar kryssas i automatiskt.
- Fix: redigering/borttagning (via CalDAV eller HA:s egen kalendervy) av ett event från en källkalender som inte stödjer uppdatering/borttagning kraschade okontrollerat istället för att ge ett tydligt felmeddelande.
- Fix: ICS-feed-tokenjämförelsen använder nu konstant-tidsjämförelse (`hmac.compare_digest`).

## 0.0.6 – 2026-08-03
- Ny: riktig tvåvägssync via ett CalDAV-konto (server-URL/användarnamn/lösenord i panelen) – skapa, redigera och ta bort event direkt i Apple Kalender, Thunderbird eller Android+DAVx5. Google Kalender saknar stöd för externa CalDAV-konton i alla sina appar och förblir read-only via den befintliga ICS-prenumerationen.
- Ny: återkommande event (upprepning) stöds nu på den egna kalendern – skapa via HA:s kalendervy, panelen eller CalDAV; redigera/ta bort en hel serie eller bara ett enstaka tillfälle.
- Ny: aktivitetslogg per kalender/sensor i panelen ("Senaste händelser") – visar skapade/ändrade/borttagna kalendrar, filter och event samt käll-status.
- Fix: heldagsevent kunde krascha ("Expected all values to have a timezone") på grund av en datum/datetime-tolkningsbugg i både den egna kalendern och hämtning från källkalendrar.

## 0.0.5 – 2026-08-03
- Slog ihop den dolda, automatiskt skapade "(egen)"-kalenderentiteten med den sammanslagna vyn – en enda kalenderentitet visar nu både sammanslaget resultat och äger event du skapar direkt på den.

## 0.0.4 – 2026-07-29
- Fixade att panelen renderades i light DOM utan `attachShadow`, vilket lät panelens CSS läcka ut och korrupta Home Assistants eget layout utanför panelen.

## 0.0.3 – 2026-07-29
- Markerade panelens JS som `trust_external` för att undvika en `confirm()`-edge case.

## 0.0.2 – 2026-07-29
- Ersatte textfältet för bild-URL med riktig bilduppladdning (`/api/image/upload`), samma mekanism som Person/Area-bilder.

## 0.0.1 – 2026-07-29
- Nollställde versionsschemat till 0.0.x.
- Fixade en tom "Kalendrar"-flik och la till per-post-underflikar i panelen.

## Initial commit
- Första versionen av Cal Combiner: sammanslagning av flera kalenderentiteter, prenumererbar ICS-länk, egen skrivbar kalender per merge, filter per källa, aktivitetssensorer, sidopanel.
