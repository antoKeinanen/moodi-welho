<img src="assets/icon.svg" width="64" height="64" alt="">

# Velho Tutkinto

MOODIn Telegram-botti velhon sauvan rakentamiseen. Jokainen tölkki saa oman emojin, ja sauva
piirtyy pystyyn. Ensimmäinen tölkki on alimpana ja voimakivi päällimmäisenä.

```
💎  voimakivi
🍺
🍺  0,5 l on kaksi emojia
🍋  0,33 l on yksi emoji
🥤
🥤
🍎  ensimmäinen tölkki
```

Botti käyttää Pythonia 3.12+, aiogramia 3 ja SQLitea. Käyttöliittymä on suomeksi.

## Käynnistys

```bash
cp .env.example .env      # lisää BOT_TOKEN, jonka saat @BotFatherilta
uv sync
uv run velho              # luo tietokannan (velho.db) automaattisesti
```

Testit ajetaan komennolla `uv run pytest` ja lint komennolla `uv run ruff check . && uv run ruff format .`.

Botti reagoi ryhmässä vain komentoihin, joten se ei tarvitse ylimääräisiä oikeuksia.

## Komennot

| Komento | Tehtävä |
| --- | --- |
| `/start` | Päävalikko |
| `/new` | Aloittaa sauvan tai jatkaa keskeneräistä (yksityisviestissä) |
| `/my` | Omat sauvat (myös epäonnistuneet) ja tilastot, oma pituus, tietojen poisto |
| `/gallery` | Ryhmän valmiit sauvat, kolme sivulla, kokonaan näkyvinä |
| `/stats` | Ryhmässä ryhmän tilastot ja tuloslista (myös jokaisen epäonnistumiset), yksityisviestissä omat tilastot |
| `/join`, `/leave` | Liittyy ryhmän tilastoihin ja galleriaan tai poistuu niistä. Jäsenyys on ryhmäkohtainen |
| `/help` | Ohje |

## Sauvan rakentaminen

1. Komento `/new` aloittaa sauvan ja tallentaa alkuajan. Alkuaikaa voi siirtää napista.
2. Napit "+ 0,33 l" ja "+ 0,5 l" lisäävät tölkin. Emoji valitaan napista tai lähetetään viestinä.
   Halutessaan tölkille voi valita juomalajin.
3. Kumoa-, muokkaa- ja hylkää-napit korjaavat virheet. Muokatessa voi vaihtaa tölkin emojin ja koon
   tai poistaa tölkin.
4. Nappi "Valmis" avaa valinnan sauvan huipusta. Huipulle kelpaa mikä tahansa emoji, ja sen voi
   jättää pois. Loppuaika tallentuu samalla.
5. Voimakiven koon voi kertoa jälkeenpäin.
6. Jos sauva kaatuu, nappi "Epäonnistui" kirjaa yrityksen epäonnistuneeksi. Yritys jää tilastoihin
   mutta ei näy galleriassa, vaikka siinä ei olisi vielä tölkkejä. Vain nappi "Poista kokonaan"
   poistaa yrityksen, esimerkiksi vahingossa aloitetun.

Sauvan pituus arvioidaan tölkeistä: 0,33 l on 11,5 cm ja 0,5 l on 16 cm. Jos tallennat oman
pituutesi komennolla `/my`, rakennusnäkymä näyttää, kuinka lähellä tavoitetta olet.

## Rakenne

```
src/velho/
  staff.py     sauvan malli, emoji-pinon piirto ja syötteiden jäsennys
  stats.py     tilastot yksittäisistä tölkeistä
  db.py        SQLite-skeema, migraatiot (PRAGMA user_version) ja kyselyt
  views.py     tekstit ja näppäimistöt
  handlers.py  Telegram-käsittelijät
  __main__.py  käynnistys
tests/         piirto, järjestys, tilastot, yksityisyys ja käsittelijöiden kulku
```

Tietokannassa on taulut `users`, `groups`, `memberships` (ryhmä ja käyttäjä), `staffs` ja `cans`.
Rivi `cans`-taulussa on yksi fyysinen tölkki, jolla on koko (33 tai 50 cl), emoji, valinnainen
juomalaji ja paikka sauvassa. Tutkintotilastot lasketaan näistä riveistä vain valmiille sauvoille. Epäonnistuneista yrityksistä
tilastoidaan lukumäärä, tölkit ja onnistumisprosentti. Tilastot laskevat tölkit riveistä eivätkä
emojeista, joten 0,5 l:n tölkki on yksi tölkki, vaikka se piirtyy kahtena emojina. Uusi migraatio
lisätään merkkijonona `db.MIGRATIONS`-listaan.

## Yksityisyys

- Sauva näkyy ryhmän galleriassa ja tilastoissa vain, jos tekijä on kirjoittanut `/join` siinä
  ryhmässä. Kaikki ryhmäkyselyt rajataan `memberships`-taulun avulla, joten ryhmien tiedot eivät
  sekoitu.
- Yksityisviestissä ryhmän tietoja näkee vain sen ryhmän jäsen.
- Komento `/leave` poistaa jäsenyyden heti. Valikon kohta "Poista tietoni" (`/my`) poistaa kaiken:
  sauvat, tölkit ja jäsenyydet.
- Botti tallentaa vain Telegram-tunnuksen ja etunimen.

## Toiminta käytännössä

- Keskeneräinen sauva ja odottava syöte tallentuvat tietokantaan, joten uudelleenkäynnistys ei
  hävitä mitään.
- Napit viittaavat tölkin tai sauvan tunnukseen, ja odottava syöte kuluu kerralla. Tuplapainallus ei
  siksi lisää eikä poista kahta tölkkiä.
- Viestin pituusraja on 4096 merkkiä Telegramin UTF-16-laskennalla. Liian pitkä sauva leikataan
  alhaalta, joten voimakivi pysyy näkyvissä.

## Docker

GitHub Actions rakentaa Docker-kuvan pull requesteissa. Push `main`-haaraan, `v*`-tagi tai
käsin käynnistetty työnkulku julkaisee kuvan GitHub Container Registryyn:
`ghcr.io/antokeinanen/moodi-welho`. `main` päivittää `latest`-tagin, versiotagi tuottaa
samannimisen kuvatagin ja jokainen julkaisu saa myös `sha-<koko commit-tunnus>`-tagin.
Julkaisu käyttää automaattista `GITHUB_TOKEN`-tunnusta; erillisiä salasanoja ei tarvita.
Yksityisen kuvan lataaminen vaatii kirjautumisen GHCR:ään.

```bash
docker run -d --name velho --restart unless-stopped \
  --env-file .env -e DB_PATH=/data/velho.db \
  -v velho-data:/data ghcr.io/antokeinanen/moodi-welho:latest
```

Tietokanta säilyy `velho-data`-volyymissa. `.env` annetaan vain ajon aikana;
kuvaan ei kopioida paikallisia salaisuuksia tai tietokantoja. Kuva käyttää
lukittuja tuotantoriippuvuuksia ja ajaa botin tavallisena käyttäjänä.
Paikallinen rakennus: `docker build -t velho .`.
