# Nasadenie na Linux server

Návod počíta s **Linux serverom** (pripravené pre **Debian 13 „trixie“**, malo by fungovať aj na Ubuntu 22.04 / 24.04
a Debiane 12; potrebný je Python 3.10+, Debian 13 má 3.13), s prístupom cez SSH a právami `sudo` a s doménou
(ďalej `DOMAIN`, napr. `app.example.com`), ktorej **DNS A záznam** smeruje na IP servera. U poskytovateľa domény
vytvor záznam typu A (pre IPv6 aj AAAA) s názvom `app` v zóne `example.com` a hodnotou = IP servera.

Všade nižšie nahraď `app.example.com` svojou doménou. Najjednoduchšie je nastaviť si ju raz v termináli
a príkazy potom kopírovať tak, ako sú:

```bash
export DOMAIN=app.example.com        # <-- sem daj svoju doménu
```

(Premenná platí len v aktuálnej SSH relácii; po odhlásení ju treba nastaviť znova.)

Architektúra: `internet → nginx (HTTPS, limity) → gunicorn (aplikácia) → SQLite`.
Aplikácia nikdy nepočúva priamo na internete, iba na `127.0.0.1:8000`.

---

## 1. Čo je v balíku

`dist/examcards-deploy.zip` (vytvoríš ho príkazom `python build_package.py`) obsahuje kód aplikácie, konfiguračné
šablóny (`deploy/`) a tento návod. **Neobsahuje** databázu, heslá, kľúč relácií, `.venv`, žiadne predmety ani obrázky –
tie vzniknú až na serveri.

## 2. Príprava servera (raz)

Čerstvý Debian 13 často nemá `sudo`. Ak sa prihlasuješ ako `root`, v celom návode `sudo` jednoducho vynechaj
(alebo ho doinštaluj: `apt install sudo`). Odporúča sa pracovať ako bežný používateľ so `sudo`.

```bash
sudo apt update && sudo apt install -y python3 python3-venv nginx certbot python3-certbot-nginx ufw unzip
sudo adduser --system --group --home /opt/examcards examcards
sudo mkdir -p /opt/examcards/app /var/lib/examcards/data /var/lib/examcards/subjects /var/lib/examcards/pictures
```

## 3. Nahratie a inštalácia

Z tvojho počítača nahraj balík na server:

```bash
scp dist/examcards-deploy.zip pouzivatel@IP_SERVERA:/tmp/
```

Na serveri:

```bash
sudo unzip -o /tmp/examcards-deploy.zip -d /opt/examcards/app
sudo python3 -m venv /opt/examcards/venv
sudo /opt/examcards/venv/bin/pip install -r /opt/examcards/app/requirements.txt

# obsah, ktorý sa mení za behu, žije mimo kódu (aktualizácie ho neprepíšu)
sudo cp /opt/examcards/app/picture_of_the_day/README.txt /var/lib/examcards/pictures/    # obrázky dňa pridaj sem
sudo chown -R examcards:examcards /var/lib/examcards
sudo chown -R root:root /opt/examcards/app          # kód je pre službu len na čítanie
```

Predmety (JSON súbory) buď vytvoríš v aplikácii (**Admin → Predmety**), alebo ich skopíruješ do
`/var/lib/examcards/subjects/`. Formát je popísaný v `subjects/README.md`.

## 4. Konfigurácia

```bash
sudo cp /opt/examcards/app/deploy/examcards.env.example /etc/examcards.env
sudo sed -i "s/app\.example\.com/$DOMAIN/" /etc/examcards.env
sudo chown root:examcards /etc/examcards.env && sudo chmod 640 /etc/examcards.env
```

Súbor `/etc/examcards.env` obsahuje `APP_ENV=production` (zapne bezpečné cookies a HSTS),
`ALLOWED_HOSTS` (aplikácia odpovie len na túto adresu, požiadavky s inou hlavičkou `Host` odmietne),
`TRUST_PROXY=1` a cesty k dátam. Kľúč na podpisovanie relácií sa vygeneruje sám do
`/var/lib/examcards/data/secret_key`.

## 5. Prvý administrátor

Aplikácia nemá **žiadny predvolený účet**. Prvého admina vytvor ručne (zadáš si vlastné silné heslo):

```bash
sudo -u examcards bash -c 'set -a; . /etc/examcards.env; set +a; cd /opt/examcards/app && /opt/examcards/venv/bin/python manage_users.py add MENO --admin --name "Zobrazované meno"'
```

Ďalších používateľov už vytváraš v aplikácii: **Admin → Používatelia → + Nový používateľ**.

## 6. Spustenie aplikácie

```bash
sudo cp /opt/examcards/app/deploy/examcards.service /etc/systemd/system/examcards.service
sudo systemctl daemon-reload
sudo systemctl enable --now examcards
sudo systemctl status examcards          # má byť "active (running)"
journalctl -u examcards -f               # živý log (Ctrl+C na ukončenie)
```

## 7. nginx a HTTPS (Let's Encrypt)

```bash
sudo cp /opt/examcards/app/deploy/examcards-proxy.conf /etc/nginx/examcards-proxy.conf
sudo cp /opt/examcards/app/deploy/nginx-examcards.conf /etc/nginx/sites-available/$DOMAIN
sudo sed -i "s/app\.example\.com/$DOMAIN/" /etc/nginx/sites-available/$DOMAIN
sudo ln -s /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/$DOMAIN
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d $DOMAIN --redirect     # certifikát + presmerovanie na HTTPS
```

Certbot si obnovuje certifikát sám (`systemctl list-timers | grep certbot`). Certifikát sa nevydá, kým DNS záznam
domény neukazuje na tento server.

## 8. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Port 8000 sa **nemá** otvárať – aplikácia je dostupná len cez nginx.

## 9. Zálohy

Používame `systemd` časovač (Debian 13 nemá predinštalovaný `cron`):

```bash
sudo cp /opt/examcards/app/deploy/examcards-backup.service /etc/systemd/system/
sudo cp /opt/examcards/app/deploy/examcards-backup.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now examcards-backup.timer
systemctl list-timers examcards-backup.timer          # ukáže, kedy pobeží nabudúce
sudo systemctl start examcards-backup.service         # vyskúšaj hneď jednu zálohu
ls -l /var/lib/examcards/data/backups/
```

Každú noc o 3:15 sa vytvorí konzistentná kópia databázy do `/var/lib/examcards/data/backups/` (ostáva posledných 14).
Zálohy na **tom istom** serveri nechránia pred jeho stratou – raz za čas si stiahni `/var/lib/examcards/` k sebe:

```bash
scp -r pouzivatel@IP_SERVERA:/var/lib/examcards ./zaloha-examcards
```

## 10. Kontrola po nasadení

- [ ] `https://DOMAIN` sa otvorí s platným certifikátom, `http://` presmeruje na `https://`.
- [ ] Prihlásenie funguje; žiadny predvolený účet (napr. `admin/admin`) neexistuje.
- [ ] V prehliadači (F12 → Application → Cookies) je cookie `__Host-session` s príznakmi *Secure* a *HttpOnly*.
- [ ] `curl -sI https://DOMAIN/login` ukáže hlavičky `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`.
- [ ] `sudo ss -ltnp | grep 8000` ukáže `127.0.0.1:8000` (nie `0.0.0.0`).
- [ ] Pridaj obrázky do `/var/lib/examcards/pictures/` – zobrazia sa na hlavnej stránke (bez reštartu). Súbory musia byť čitateľné
      pre používateľa `examcards` (`sudo chown -R examcards:examcards /var/lib/examcards/pictures`).
- [ ] Voliteľne: <https://securityheaders.com> a <https://www.ssllabs.com/ssltest/> by mali dať dobré známky.

## 11. Aktualizácia na novú verziu

```bash
scp dist/examcards-deploy.zip pouzivatel@IP_SERVERA:/tmp/      # z tvojho počítača
```

```bash
sudo systemctl stop examcards
sudo unzip -o /tmp/examcards-deploy.zip -d /opt/examcards/app
sudo /opt/examcards/venv/bin/pip install -r /opt/examcards/app/requirements.txt
sudo chown -R root:root /opt/examcards/app
sudo systemctl start examcards
```

Dáta (`/var/lib/examcards`) sa nemenia. Nové stĺpce v databáze sa pridajú automaticky pri štarte.

## 12. Obnovenie z poruchy

- Zmazaný/poškodený predmet: skopíruj JSON súbor naspäť do `/var/lib/examcards/subjects/`.
- Poškodená databáza: `sudo systemctl stop examcards`, skopíruj zálohu z `backups/` na `/var/lib/examcards/data/cards.db`
  (zmaž pritom súbory `cards.db-wal` a `cards.db-shm`), `sudo systemctl start examcards`.
- Zabudnuté heslo admina: `sudo -u examcards bash -c 'set -a; . /etc/examcards.env; set +a; cd /opt/examcards/app && /opt/examcards/venv/bin/python manage_users.py passwd MENO'`.

---

# Bezpečnostný prehľad

**Overené automaticky:** `pip-audit` (žiadne známe zraniteľnosti v pripnutých závislostiach), `bandit` (statická analýza;
zvyšné upozornenia sú falošné poplachy – zložený SQL obsahuje len pevné názvy stĺpcov, hodnoty idú vždy cez parametre)
a automatické testy (`tests/`).

| Oblasť | Ako je to ošetrené |
|---|---|
| Predvolené účty | Žiadne. Prvý admin sa zakladá ručne cez `manage_users.py` |
| Hádanie hesiel | Počítadlá v databáze, per používateľ+IP (5 pokusov / 5 min) aj per IP (50 pokusov); skutočná IP sa berie z nginx (`TRUST_PROXY`); nginx navyše limituje `/login` |
| Relácie | Po zmene alebo resete hesla sa odhlásia všetky ostatné zariadenia; zablokovaný používateľ je odhlásený okamžite |
| Cookies a HTTPS | V produkcii `Secure`, `HttpOnly`, `SameSite=Lax`, prefix `__Host-`, HSTS na rok |
| Hlavička `Host` | Povolené sú len hostitelia z `ALLOWED_HOSTS` |
| Hlavičky | Prísna CSP bez inline skriptov, `X-Frame-Options`, `Permissions-Policy`, `Cross-Origin-*` |
| Heslá | Salted scrypt hash; rovnaká chyba aj čas odpovede pre neexistujúceho používateľa |
| Formuláre a API | CSRF token pri každej zmene; všetok používateľský text sa vkladá ako text (žiadne XSS); všetky SQL dopyty s parametrami |
| Nahrávané obrázky | Overujú sa podľa obsahu (nie prípony), náhodné názvy, limit 2 MB, SVG sa nikdy neservíruje; bez prihlásenia nie sú dostupné; z obrázkov dňa je dostupný len dnešný |
| Spam | Max. 10 komentárov za minútu na používateľa |
| Súborový systém | Cesty chránené proti `../`; kľúč relácií s právami `600`; služba smie zapisovať len do `/var/lib/examcards` |
| Záznamy | Neúspešné prihlásenia (IP) a akcie adminov sa zapisujú do logu (`journalctl -u examcards`) |

**Odporúčania, ktoré aplikácia sama nerieši**

- **SSH len cez kľúč** (`PasswordAuthentication no`) a `unattended-upgrades` na automatické bezpečnostné aktualizácie OS.
- **fail2ban** čítajúci riadky „Failed sign-in from …“ z `journalctl -u examcards` (dodatočné blokovanie IP na firewalle).
- **Dvojfaktorové prihlásenie** pre adminov – aplikácia ho nemá.
- Zálohy držať aj **mimo servera**.
- Hlásenia o chybách v JSON súboroch predmetov vidí admin iba po anglicky.
- Všetci prihlásení vidia prezývky ostatných online používateľov (zámerná funkcia; stav *Neviditeľný* ich skryje).
