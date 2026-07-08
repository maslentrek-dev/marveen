# Watchdog userbot session -- Arnold lépései (egyszeri, interaktív)

A cél: a `store/.watchdog-userbot.session` létrehozása, amivel az inbound-probe
(deafness watchdog) 3 percenként pingeli a botot, és a keepalive fájl model-token
nélkül frissül. Előfeltétel: a `fix/inbound-probe-target` branch merge-ölve
(enélkül a prober Arnold privát chatjébe DM-ezne a bot helyett!).

## 0. Ami már kész (Geordi, 2026-07-08)

- `.watchdog-venv` létrehozva, telethon 1.43.2 telepítve (pinned).
- Prober cél-fix: a ping a bot @username-jére megy (getMe-ből feloldva).
- Login script: a telefonszámot a creds JSON-ból olvassa, forrást nem kell szerkeszteni.

## 1. Prober fiók (dedikált Telegram user fiók)

Kell egy KÜLÖN telefonszám (tartalék SIM / másodlagos szám). NEM a bot, és NEM
Arnold fő fiókja. Telepítsd rá a Telegramot (vagy web.telegram.org), hogy a
belépési kódot fogadni tudd.

## 2. API kulcsok (a prober fiókkal belépve)

1. https://my.telegram.org -> Login (a PROBER számmal)
2. API development tools -> Create application (név/platform mindegy)
3. Jegyezd fel: `api_id` (szám) és `api_hash` (hex string)

## 3. Creds fájl a Mac minin (terminál, marveen mappa)

```bash
cd /Users/gruzmanarnold/marveen
cat > store/.watchdog-userbot.json << 'EOF'
{"api_id": IDE_AZ_API_ID, "api_hash": "IDE_AZ_API_HASH", "phone": "+4219XXXXXXXX"}
EOF
chmod 600 store/.watchdog-userbot.json
```

## 4. Login (két lépés, a kód a prober fiókba érkezik)

```bash
.watchdog-venv/bin/python3 scripts/watchdog-userbot-login.py request
# -> "CODE_REQUEST_SENT" és a prober fiókba jön egy belépési kód
.watchdog-venv/bin/python3 scripts/watchdog-userbot-login.py signin 12345
# 2FA esetén: ... signin 12345 'a2FAjelszó'
# -> "SIGNED_IN id=<user_id> user=<username> phone=<phone>"
```

A `SIGNED_IN` sorban kiírt `id` a prober fiók user id-ja -- ez kell az 5. lépéshez.
Siker után létrejön a `store/.watchdog-userbot.session` (0600).

## 5. Allowlist (kötelező kapu)

A saját termináljában (nem Telegramon!) futtatandó: `/telegram:access` a fő
(picard) sessionben, és a prober fiók user id-jának engedélyezése. Enélkül a
plugin eldobja a pingeket és a watchdog süketnek látná a csatornát.

## 6. Ellenőrzés (Geordi/Picard végzi, nem Arnold)

- `store/dashboard.log`: "inbound-prober: connected" majd "sent ping" sorok
- `store/.watchdog-probe-last-sent` és `store/.channel-keepalive` 3 percenként frissül
- Az ELSŐ 2-3 ciklust felügyelve nézzük: ha a marker nem kerül be a fő session
  transcriptjébe, a watchdog respawnolna -- ilyenkor azonnal le kell állítani
  (session fájl átnevezése elég: a prober safe no-op lesz).

## Nyitott döntés élesítés ELŐTT (Picard/Arnold)

A ping bekerül a fő session inputjába, tehát MINDEN ping egy LLM-turn:
3 perces intervallumnál ~480 turn/nap a picard sessionben. Opciók:
1. PROBE_INTERVAL_MS emelése (pl. 15 perc = ~96 turn/nap), és akkor a
   wedge-küszöbök 10/25 helyett 20/40 percre lőve (a küszöb nem lehet a
   probe-intervallum alatt).
2. Plugin-oldali __wd_ping szűrés (transcript-ingest igen, model-turn nem) --
   ehhez a Channels plugin támogatása kell, felderítendő.
3. Elfogadjuk a turn-égetést a fő session megbízhatóságáért cserébe.
