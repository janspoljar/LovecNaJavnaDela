# DEPLOY.md — Ročni koraki za postavitev na Hetzner

Vse spodaj narediš enkrat. Po tem gre vsak deploy avtomatsko: push na `main`
→ testi → deploy na server.

## 1. SSH ključ (če ga še nimaš)

Na svojem računalniku:

```
ssh-keygen -t ed25519 -C "jan-deploy"
```

Sprejmi privzeto pot (`C:\Users\jan\.ssh\id_ed25519`). Nastane par:
`id_ed25519` (zasebni — nikomur!) in `id_ed25519.pub` (javni).

## 2. Hetzner server

1. Registracija na https://www.hetzner.com/cloud → Cloud Console → nov projekt.
2. **Add Server**:
   - Lokacija: Falkenstein ali Nürnberg (najceneje, blizu SLO)
   - Image: **Ubuntu 24.04**
   - Tip: **CX22** (2 vCPU, 4 GB RAM, ~4 €/mes) — za začetek dovolj
   - SSH key: dodaj vsebino `id_ed25519.pub`
   - **Cloud config**: odpri `deploy/cloud-init.yaml` iz tega repa, zamenjaj
     `<TVOJ_SSH_JAVNI_KLJUC>` z vsebino `id_ed25519.pub` in prilepi celotno
     datoteko v polje "Cloud config"
3. Create & Buy. Zapiši si **IP serverja**.
4. Počakaj ~3 minute (cloud-init instalira docker, ufw, fail2ban), nato preveri:

```
ssh deploy@<IP>
docker --version    # mora delovati brez sudo
```

Root prijava in geselna prijava sta onemogočeni — to je namerno.

## 3. DNS za domeno

Pri svojem registrarju domene dodaj **A record**:

| Tip | Ime (host)            | Vrednost   |
|-----|-----------------------|------------|
| A   | alerti (ali @ ali www)| `<IP>`     |

Počakaj da se DNS propagira (preveri: `nslookup alerti.tvojadomena.si`).
Caddy si bo certifikat uredil sam ob prvem zagonu — domena MORA kazati na
server, preden zaženeš compose, sicer Let's Encrypt izziv ne uspe.

## 4. Prva postavitev na serverju

```
ssh deploy@<IP>
git clone https://github.com/janspoljar/jn-watchdog.git /opt/jn-watchdog
cd /opt/jn-watchdog
cp .env.example .env
nano .env
```

V `.env` izpolni:

```
RESEND_API_KEY=re_...          # iz Resend dashboarda
STRIPE_SECRET_KEY=             # zaenkrat pusti prazno (Faza 5)
STRIPE_WEBHOOK_SECRET=         # zaenkrat pusti prazno
STRIPE_PRICE_ID=               # zaenkrat pusti prazno
FROM_EMAIL=narocila@tvojadomena.si
DB_PATH=/data/narocila.db
PORT=5000
DOMAIN=alerti.tvojadomena.si   # tvoja prava (pod)domena
```

Zaženi:

```
docker compose up -d --build
docker compose ps        # vsi 3 servisi morajo biti "running"
curl https://alerti.tvojadomena.si/zdravje
```

Pričakovan odgovor: `{"status": "ok", ...}`.

## 5. GitHub secrets za avtomatski deploy

GitHub repo → **Settings → Secrets and variables → Actions → New repository
secret**, dodaj tri:

| Ime               | Vrednost                                          |
|-------------------|---------------------------------------------------|
| `SSH_HOST`        | IP serverja                                       |
| `SSH_USER`        | `deploy`                                          |
| `SSH_PRIVATE_KEY` | celotna vsebina `id_ed25519` (zasebni ključ, vključno z BEGIN/END vrsticama) |

## 6. Test avtomatskega deploya

```
git commit --allow-empty -m "test: deploy pipeline"
git push origin main
```

GitHub → Actions zavihek → workflow "Test & Deploy" mora biti zelen
(test job + deploy job). Nato še enkrat preveri `/zdravje`.

## 7. Selitev obstoječe baze (če imaš podatke iz Railway/lokalno)

Baza v containerju živi na volume `db_data` (pot `/data/narocila.db`).
Obstoječo bazo skopiraš noter takole:

```
scp narocila.db deploy@<IP>:/tmp/narocila.db
ssh deploy@<IP>
docker compose -f /opt/jn-watchdog/docker-compose.yml cp /tmp/narocila.db app:/data/narocila.db
docker compose -f /opt/jn-watchdog/docker-compose.yml restart app scheduler
rm /tmp/narocila.db
```

## Opombe

- `render.yaml` ni več potreben (selitev z Render/Railway) — pobrišeš ga
  lahko, ko potrdiš, da Hetzner deploy dela.
- Scheduler servis požene dnevni job ob **06:00 po času containerja (UTC)** —
  to je 07:00/08:00 SLO. Uskladitev urnika pride v Fazi 2/3.
- Stripe ključi niso potrebni za zagon — endpointi obstajajo, aktivirajo se
  v Fazi 5.
