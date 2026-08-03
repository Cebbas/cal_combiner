# Changelog

Alla nämnvärda ändringar i Cal Combiner dokumenteras här.

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
