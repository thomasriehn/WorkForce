# WorkForce im LXC unter Proxmox VE

Prüfdatum aller Quellen: **2026-11-10**. **Nichts hiervon wurde auf einem echten Proxmox-Host ausgeführt.**
Kennzeichnung: **belegt** = steht so in der zitierten offiziellen Quelle (Kürzel wie [P1], Liste in Abschnitt 9) ·
**abgeleitet** = Schlussfolgerung aus Belegtem, nicht getestet · **nicht getestet / Planungsannahme** = nicht
ausgeführt bzw. nicht gemessen.

## 1. Einordnung und ehrlicher Hinweis

WorkForce läuft als Docker-Compose-Anwendung (`db`, `migrate`, `web`, `worker`, `scheduler`). Docker im LXC heißt:
Container im Container auf dem Kernel des Proxmox-Hosts. Was Proxmox dazu offiziell sagt:

- Dokumentation 9.2.13 [P1]: „While running lightweight “Application Containers” directly offers significant
  advantages over a full VM, for use cases demanding maximum isolation and the ability to live-migrate, nesting
  containers inside a Proxmox QEMU VM remains a recommended practice.“
- FAQ [P5]: „It is not recommended to run docker directly on your Proxmox VE host.“ Und: „For use cases requiring
  container orchestration or live migration, it is still recommended to run them inside a Proxmox QEMU virtual machine.“
- Dokumentation 8.4 [P13] (Proxmox VE 8 ist laut FAQ seit 2026-08 außerhalb der Unterstützung): „If you want to run
  application containers, for example, Docker images, it is recommended that you run them inside a Proxmox QEMU VM.“
  Dieser Satz steht in der 9.2-Dokumentation nicht mehr.

**Klartext:** Die offizielle Empfehlung für Docker-Workloads ist die VM. In 9.2 ist sie auf maximale Isolation,
Live-Migration und Orchestrierung eingegrenzt, aber nirgends in den gelesenen Seiten wird Docker im LXC als
empfohlener oder zugesicherter Betrieb beschrieben – erwähnt wird es nur beim Schalter `keyctl` [P2] und als
Problemfeld in den Release Notes [P4]. Die seit 9.1 möglichen „Application Containers“ aus OCI-Images sind etwas
anderes (ein Image je LXC, „technology preview“ [P1]); Compose-Unterstützung ist nur ein Roadmap-Ziel [P4].

Der LXC ist die gewünschte Zielumgebung. Dafür spricht: kein zweiter Kernel, RAM wird nicht fest reserviert. Dagegen:
geteilter Host-Kernel („In general, full virtual machines provide better isolation.“ [P1]); keine Live-Migration, nur
Neustart-Migration [P1]; `nesting` legt procfs und sysfs des Hosts gegenüber dem Gast offen [P2]; Docker hängt am
Zusammenspiel von Host-Kernel, AppArmor-Profil des LXC und runc – Störungen nach Updates sind für 9.0 und 9.1 belegt
[P4][P12]. Hinweis aus der Community, nicht offiziell: In den Kommentaren zum Bugzilla-Eintrag 7006 raten Nutzer
deshalb zur VM; ein runc-Maintainer hält den Betrieb im LXC dort für vertretbar.

**Alternative: gleiche Compose-Datei in einer VM.** Debian-13-VM mit denselben Startwerten, danach Abschnitt 3 ab
Schritt 4 unverändert. Es entfallen `nesting`/`keyctl`, die UID-Verschiebung und die Abhängigkeit vom AppArmor-Profil
des Hosts. Sinnvoll, wenn der Host auch weniger vertrauenswürdige Gäste trägt, Live-Migration gebraucht wird, nur
ZFS-Storage vorhanden ist (Abschnitt 2) oder Docker im LXC nach einem Update nicht mehr startet. Nicht getestet.

## 2. Voraussetzungen

| Punkt | Vorgabe | Beleg / Status |
|---|---|---|
| Proxmox VE | 9.2 – aktuelles Stable (ISO 9.2-1 vom 21.05.2026; Debian 13 „Trixie“, Kernel 7.0, LXC 7.0, ZFS 2.4; Doku-Version 9.2.13 vom 24.09.2026). Proxmox VE 8: EOL 2026-08. | belegt [P4][P5][P10] |
| Paketstand des Hosts | aktuell (`apt update`, `apt full-upgrade`). Belegte Korrekturen für Docker im LXC: Paket pve-container 6.0.3 und Proxmox VE 9.1. | belegt [P4][P5][P12] |
| LXC-Template | Debian 13: `debian-13-standard_13.6-1_amd64.tar.zst` (am Prüfdatum im offiziellen Template-Verzeichnis, Datei vom 14.07.2026). Docker unterstützt „Debian Trixie 13 (stable)“ und „Debian Bookworm 12 (oldstable)“; Debian 12 hat laut FAQ-Tabelle Debian-EOL 2026-07. | belegt [P11][D1][P5]; Betrieb nicht getestet |
| Containertyp | unprivilegiert (`unprivileged: 1`) – „This is the default option when creating a new container.“ Seit 9.0 auch über API und CLI. | belegt [P1][P4] |
| Features | `nesting=1,keyctl=1` (Wortlaut unten) | belegt [P2]; ob das genügt: nicht getestet |
| Nicht setzen | `fuse` („can potentially cause I/O deadlocks“), `mknod` („This is experimental.“), `mount` („negative effects on the container’s security“), `force_rw_sys` – nichts davon wird gebraucht | belegt [P2] |
| cgroup | nur v2: v1 wurde „removed entirely with Proxmox VE 9.0“. Debian 13 erfüllt die Anforderung (systemd ≥ 231). | belegt [P1][P4] |
| AppArmor / seccomp | Standardprofil unverändert | belegt [P1] |
| Storage der Root-Disk | bevorzugt ein Storage, das ein Raw-Image mit ext4 anlegt (z. B. LVM-thin); ZFS nur nach eigenem Test | teils belegt, teils abgeleitet (unten) |
| Ressourcen, Netz | 2 Kerne, 4096 MB RAM, 1024 MB Swap, 40 GB Root-Disk; Bridge mit fester Adresse, ausgehend HTTPS und DNS | Planungsannahme (Abschnitte 5 und 6) |

**Wortlaut `keyctl`** [P2]: „For unprivileged containers only: Allow the use of the keyctl() system call. This is
required to use docker inside a container.“ Vorbehalt im selben Absatz: „Essentially, you can choose between running
systemd-networkd or docker.“ Im LXC darf das Netz also nicht über systemd-networkd laufen (Prüfung:
`systemctl is-active systemd-networkd`). Was das Template 13.6 nutzt, ist nicht getestet; die Release Notes zu 9.1
nennen für Debian-13-Container `ifupdown2` und `isc-dhcp-client` [P4].

**Wortlaut `nesting`** [P2]: „Allow nesting. Best used with unprivileged containers with additional id mapping. Note
that this will expose procfs and sysfs contents of the host to the guest.“ Und: „This is also required by systemd to
isolate services.“ Die Weboberfläche setzt `nesting` für neue unprivilegierte Container seit 7.1 selbst [P4]; bei
`pct create` muss es angegeben werden (Standard 0 [P2]).

**Storage – belegt:** Container-Volumes sind Raw-Images mit ext4 („raw images containing a single ext4 formatted file
system“) oder ZFS-Subvolumes [P1]; LVM-thin liefert `raw`, ZFS `subvol` [P7]. Docker nennt für `overlay2` die
Dateisysteme „xfs with ftype=1, ext4, btrfs, (and more)“ und: „Most filesystems should work if they have the required
features.“ [D2] Ab Docker Engine 29.0 ist bei Neuinstallation der containerd-Image-Store mit Snapshotter `overlayfs`
Standard [D2][D3]; eine Dateisystemliste dafür enthalten die gelesenen Seiten nicht. `vfs` ist „not generally
recommended for production use“ [D2].

**Storage – abgeleitet, nicht getestet:** Raw-Image mit ext4 (LVM-thin, Verzeichnis-Storage) passt zur
Docker-Dokumentation. Bei ZFS liegt `/var/lib/docker` auf einem ZFS-Dataset; dafür gibt es in den gelesenen Seiten
keine Zusage. Dockers `zfs`-Treiber ist laut Docker nur mit viel ZFS-Erfahrung für Produktion geeignet [D7] und
bräuchte ZFS-Zugriff, den ein unprivilegierter LXC vermutlich nicht hat. Die OpenZFS-Release-Notes konnten am
Prüfdatum nicht abgerufen werden (HTTP 403). Auf ZFS-Hosts Schritt 5 abwarten; bei `vfs` oder Fehlern die VM wählen.

**Bewusst nicht Standard:** kein privilegierter Container („privileged containers should only be used in trusted
environments“ [P1]) und kein Abschalten von AppArmor – zu `lxc.apparmor.profile = unconfined`: „Please note that this
is not recommended for production use.“ [P1] Startet Docker nicht, stattdessen prüfen: (1) `pct config <CTID>` zeigt
`unprivileged: 1` und beide Features; (2) Paketstand des Hosts und „Known Issues“ der Release Notes [P4]; (3) auf dem
Host `dmesg | grep apparmor` [P1] – gibt es `DENIED`-Zeilen zum Container? (4) im LXC
`journalctl -u docker -u containerd`; (5) bleibt es dabei: VM statt abgeschalteter Schutzfunktionen (Abschnitt 7).

## 3. Schritt für Schritt

**Kein Schritt dieses Abschnitts wurde ausgeführt.** Syntax nach [P1], [P3] und [D1]. Platzhalter: `<CTID>`,
`<STORAGE>`, `<BRIDGE>`, `<IP>/<CIDR>`, `<GATEWAY>`.

**Schritt 1 – Template laden (Proxmox-Host; nicht getestet).** Maßgeblich ist der Name aus `pveam available`.

```bash
pveam update
pveam available --section system | grep debian-13
pveam download local debian-13-standard_13.6-1_amd64.tar.zst
```

**Schritt 2 – Container anlegen (nicht getestet).** Weboberfläche: „Create CT“ → Hostname, SSH-Schlüssel;
„Unprivileged container“ und „Nesting“ aktiviert lassen [P1] → Template → Root-Disk 40 GiB → 2 Kerne → 4096 MiB
RAM, 1024 MiB Swap → Bridge, feste IPv4-Adresse. Danach unter „Options“ „Start at boot“ setzen [P1] und `keyctl`
ergänzen (notfalls `pct set <CTID> --features nesting=1,keyctl=1`). Die Beschriftungen der Oberfläche wurden nicht
am System geprüft. Gleichwertig auf der Kommandozeile:

```bash
pct create <CTID> local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst \
  --hostname workforce \
  --unprivileged 1 \
  --features nesting=1,keyctl=1 \
  --cores 2 --memory 4096 --swap 1024 \
  --rootfs <STORAGE>:40 \
  --net0 name=eth0,bridge=<BRIDGE>,ip=<IP>/<CIDR>,gw=<GATEWAY>,firewall=1 \
  --ssh-public-keys /root/workforce-admin.pub \
  --onboot 1
```

**Schritt 3 – Starten, Konfiguration ansehen, anmelden (nicht getestet).**

```bash
pct start <CTID>
pct config <CTID>
pct enter <CTID>
```

**Schritt 4 – Docker Engine und Compose-Plugin aus Dockers apt-Quelle (im LXC als root; nicht getestet).** Befehle
der offiziellen Seite für Debian [D1], ohne `sudo`, weil als root ausgeführt.

```bash
apt update
apt install ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: $(. /etc/os-release && echo "$VERSION_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt update
apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

**Schritt 5 – Prüfen (nicht getestet).** Erwartet (abgeleitet aus [D2][D3][P1]): `Storage Driver: overlayfs` mit
`driver-type: io.containerd.snapshotter.v1` oder `overlay2`, dazu `Cgroup Version: 2`. Für den Betrieb nicht
akzeptabel: `vfs`. Was Docker in einem LXC tatsächlich ausgibt, ist offen.

```bash
systemctl status docker --no-pager
docker info | grep -iE 'server version|storage driver|driver-type|backing filesystem|cgroup'
docker run --rm hello-world
```

**Schritt 6 – WorkForce holen und starten (im LXC nicht getestet).**

```bash
apt install git
git clone https://github.com/thomasriehn/WorkForce.git /opt/workforce
cd /opt/workforce
cp .env.example .env
chmod 600 .env
```

In `.env` mindestens `POSTGRES_PASSWORD` und `WF_CRAWLER_CONTACT` setzen (Hinweise in `.env.example`), dann starten.
Weiter mit [betrieb.md](betrieb.md) (Administrator anlegen, Erstimport, Sicherung).

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8080/healthz
```

## 4. Dateirechte und Storage

**Ablageorte** (belegt [D5], im LXC nicht getestet): Die Volumes liegen im Root-Dateisystem des LXC unter
`/var/lib/docker/volumes/workforce_db-data/_data` und `/var/lib/docker/volumes/workforce_app-data/_data`; mit dem
containerd-Image-Store liegen Images und Container-Schichten unter `/var/lib/containerd`. Beides zählt auf die Root-Disk.

**UID-Verschiebung:** „The root UID 0 inside the container is mapped to an unprivileged user outside the container.“
[P1] Üblicher Versatz laut Proxmox-Wiki (Stand 2021): „root (uid 0) became uid 100000, 1 will be 100001 and so on“
[P9]. Abgeleitet, nicht getestet: Der Anwendungsbenutzer aus dem `Dockerfile` (uid/gid 10001) ist im LXC 10001 und
auf dem Proxmox-Host 110001. Das leere Volume `app-data` wird beim ersten Start aus `/data` des Images befüllt [D8];
der Eigentümer sollte 10001:10001 sein. Kontrolle im LXC:

```bash
docker compose exec web sh -c 'id && ls -ldn /data'
```

**Keine Bind-Mounts vom Host.** Belegt [P1]: „With unprivileged containers you might run into permission problems
caused by the user mapping and cannot use ACLs.“ Und: „The contents of bind mount points are not backed up when using
vzdump.“ Ein Host-Verzeichnis müsste 110001 gehören oder eine eigene Zuordnung bekommen (Option `idmap` je Mount-Point
seit 9.2 [P1][P4], nicht getestet). Empfehlung: benannte Volumes im Root-Dateisystem. Wer Docker-Daten trennen will,
legt **vor** der Docker-Installation einen storage-gestützten Mount-Point an (nicht getestet); ohne `backup=1` wird er
nicht mitgesichert [P6], und die Images liegen bei Docker ab 29 trotzdem unter `/var/lib/containerd` [D5]:

```bash
pct set <CTID> -mp0 <STORAGE>:40,mp=/var/lib/docker,backup=1
```

**Root-Disk vergrößern** (belegt [P3], nicht getestet); Verkleinern geht nicht: „Shrinking disk size is not supported.“

```bash
pct df <CTID>
pct resize <CTID> rootfs +20G
```

**vzdump und Anwendungssicherung.** Eine vzdump-Sicherung des LXC enthält Konfiguration und Root-Disk, also auch
`/var/lib/docker`, `/var/lib/containerd`, `/opt/workforce` samt `.env` und lokale Sicherungen unter `./backups`.
Nicht enthalten: Bind- und Device-Mounts, weitere Mount-Points ohne `backup=1` sowie `/tmp/?*`, `/var/tmp/?*`,
`/var/run/?*pid` [P6]. Die Modi für Container laut [P6]:

- `stop`: „Stop the container for the duration of the backup. This potentially results in a very long downtime.“
- `suspend`: rsync in ein temporäres Verzeichnis, Container anhalten, zweiter rsync; braucht zusätzlichen Platz.
- `snapshot`: „First, the container will be suspended to ensure data consistency. A temporary snapshot of the
  container’s volumes will be made and the snapshot content will be archived in a tar file.“ Bedingung: „snapshot mode
  requires that all backed up volumes are on a storage that supports snapshots.“

`scripts/backup.sh` (pg_dump, Archiv von `app-data`, Konfiguration) bleibt trotzdem nötig:

1. In den Modi `snapshot` und `suspend` werden Prozesse eingefroren und Dateien kopiert; PostgreSQL wird nicht
   beendet. Das gesicherte Datenverzeichnis entspricht dem Zustand nach einem Absturz und hängt am Wiederanlauf von
   PostgreSQL. Eine Zusage zur Datenbankkonsistenz steht in [P6] nicht (eigene Einschätzung, nicht getestet). Nur
   `stop` sichert eine beendete Datenbank – mit Ausfallzeit.
2. `pg_dump` liefert einen logisch konsistenten Stand, der sich in eine frische Datenbank, auf ein anderes System oder
   in eine VM einspielen lässt; `scripts/restore.sh --verify` prüft das.
3. Die Anwendungssicherung stellt nur WorkForce wieder her, ohne den ganzen LXC zurückzusetzen.

Planungsannahme: täglich `scripts/backup.sh` auf ein Ziel außerhalb des LXC, zusätzlich vzdump für die schnelle
Wiederherstellung der Umgebung. Beide Wiederherstellungswege sind auf Proxmox nicht getestet.

## 5. Netz und Zugriff

- **Standard:** `web` ist im LXC nur an `127.0.0.1:8080` gebunden – mit Absicht weder vom Proxmox-Host noch aus dem
  Netz erreichbar.
- **Variante A – Reverse Proxy mit TLS im selben LXC:** Caddy oder nginx als Dienst im LXC (Vorlagen
  `deploy/Caddyfile.example`, `deploy/nginx.conf.example`); `WF_BIND_ADDRESS` bleibt `127.0.0.1`, offen sind nur 80/443.
- **Variante B – Proxy auf einem anderen Host:** in `.env` `WF_BIND_ADDRESS=<IP des LXC>` setzen und Port 8080 nur für
  den Proxy freigeben; die Strecke Proxy → LXC ist unverschlüsseltes HTTP und gehört in ein internes Netz. Eine
  Firewall im LXC (ufw, firewalld) genügt nicht: Von Docker veröffentlichte Ports „bypass your firewall rules“
  [D1][D6]. Geeignet ist die Proxmox-Firewall, weil sie auf dem Host vor dem Container filtert (abgeleitet aus [P8]).
  Belegt [P8]: Sie ist „completely disabled by default“ und muss clusterweit, für den Container und an der
  Netzwerkkarte (`firewall=1`) aktiviert werden – „Each virtual network device has its own firewall enable flag.“
  Vorsicht beim clusterweiten Einschalten: „If you enable the firewall, traffic to all hosts will be blocked by
  default“ (Ausnahmen u. a. für Weboberfläche und SSH aus dem lokalen Netz). Regel in `/etc/pve/firewall/<CTID>.fw`
  nach dem Muster `IN ACCEPT -source <PROXY-IP> -p tcp -dport 8080` bei `policy_in: DROP`; vorher den eigenen
  SSH-Zugang freigeben (Syntax nach [P8], nicht getestet).
- **PostgreSQL** wird nie veröffentlicht: `db` hängt nur am Compose-Netz `backend` (`internal: true`) und hat keinen
  `ports`-Eintrag. Administration nur über `docker compose exec db psql …`.
- **Ausgehend:** Im Betrieb braucht fachlich nur der `worker` ausgehendes HTTPS (freigegebene Quellen, Statistik- und
  Geodaten-Downloads). Für Installation, Image-Bau und Updates braucht der LXC zusätzlich die Paketquellen und
  Registries (Debian, Docker, Docker Hub, ghcr.io, PyPI, npm, Chromium-Download von Playwright).

## 6. Startdimensionierung (Planungsannahme)

**2 vCPU, 4 GB RAM, 1 GB Swap, 40 GB Root-Disk.** Kein Messergebnis auf Proxmox, sondern eine Annahme aus dem
synthetischen Skalierungstest auf einer Entwicklungsmaschine (4 Kerne, 15 GB RAM, PostgreSQL-Standardeinstellungen):

| Messwert (Entwicklungsmaschine) | Folgerung für den Startwert |
|---|---|
| 100.000 Quellanzeigen mit 4,37 Mio. kompakten Beobachtungen belegen rund 1 GB in PostgreSQL (größte Tabellen: `observation` 409 MB, `posting_version` 269 MB) | passt bei 4 GB in den Arbeitsspeicher (`PG_SHARED_BUFFERS=512MB` plus Seitencache); auf der Platte bleibt viel Reserve |
| Suchabfragen 5–180 ms, Kartenabfragen 130–410 ms | 2 Kerne reichen für wenige gleichzeitige Nutzer; Abrufe sind durch Wartezeiten gedrosselt und kaum CPU-gebunden |
| Image enthält Chromium (mehrere hundert MB) | Platz für Images, Bau-Cache und ein zweites Image beim Update; der containerd-Image-Store braucht laut Docker mehr Platz als die klassischen Treiber [D3] |
| VG250-Download 70–120 MB, dazu aufbewahrte Statistik-Quelldateien | `app-data` wächst langsam und bleibt deutlich kleiner als die Datenbank |

Weitere Posten im RAM: drei Python-Prozesse, Docker und containerd, zeitweise Chromium im `worker`; `shm_size` aus
`compose.yaml` (256 MB `db`, 512 MB `worker`) zählt bei Nutzung mit. Swap ist ein Puffer für kurze Spitzen
(Image-Bau, Chromium); er stammt aus dem Swap des Hosts [P1] und wirkt nur, wenn der Host Swap hat. Aufstocken, wenn:

- viele Quellen aktiv sind oder `WF_WORKER_CONCURRENCY` erhöht wird → 4 vCPU;
- deutlich mehr als 1 Mio. Beobachtungen pro Monat anfallen → Plattenbedarf beobachten (hochgerechnet aus 409 MB für
  4,37 Mio. Zeilen: rund 0,1 GB je Million allein in `observation`); wird die Datenbank größer als der
  Arbeitsspeicher, 8 GB RAM und höhere `PG_SHARED_BUFFERS` / `PG_EFFECTIVE_CACHE_SIZE`;
- Kartenabfragen dauerhaft über einer Sekunde liegen oder der Kernel Prozesse beendet (OOM) → mehr RAM;
- die Root-Disk über 70 % belegt ist (`pct df <CTID>`) → `pct resize`.

## 7. Fehlersuche speziell für Docker im LXC

| Symptom | Dokumentierte Ursache / Prüfung | Maßnahme |
|---|---|---|
| systemd-Dienste im LXC schlagen fehl, Docker startet nicht, Proxmox warnt beim Containerstart | `nesting` fehlt: „required by systemd to isolate services“ [P2]; seit 9.2 mit Warnung [P4]. `pct config <CTID>` | `pct set <CTID> --features nesting=1,keyctl=1`, dann `pct reboot <CTID>` |
| Docker-Container starten im unprivilegierten LXC nicht | `keyctl` fehlt: unprivilegierte Container sehen den Systemaufruf sonst als „non-existent“ [P2]. Der genaue Fehlertext ist nicht belegt. | `keyctl=1` setzen; kein systemd-networkd im LXC [P2] |
| `docker info` zeigt `Storage Driver: vfs`, oder Overlay-Fehler im Journal | `vfs` ist nur für Tests gedacht [D2]; dokumentierte Dateisysteme für Overlay in [D2][D4]. `df -T /var/lib/docker /var/lib/containerd` | Root-Disk auf ein Storage mit ext4-Raw-Image verschieben (`pct move-volume <CTID> rootfs <STORAGE>` [P3]) oder VM; kein Betrieb mit `vfs` |
| `permission denied` beim Start von Docker-Containern, oft nach Host- oder Docker-Update | AppArmor-Profil des LXC blockiert: auf dem Host `dmesg \| grep apparmor` [P1]. Belegte Fälle: Release Notes 9.0 („known issue with nested containerization“) mit Bugzilla-Eintrag 6538 (Status FIX PACKAGED) und Eintrag 7006 (RESOLVED FIXED, Korrektur in 9.1) [P4][P12] | Host aktualisieren, `nesting=1` prüfen, Release Notes lesen; `unconfined` ist keine Dauerlösung [P1]; sonst VM |
| Software erwartet cgroup v1 | Proxmox VE 9 kennt nur cgroup v2, Zurückschalten geht nicht mehr [P1][P4]; `docker info` muss `Cgroup Version: 2` zeigen | keine Umstellung möglich; WorkForce braucht kein cgroup v1 (Annahme) |
| vzdump im Modus `snapshot` oder `suspend` hängt | FUSE-Mounts im Container sind „strongly advised against“, weil der Container eingefroren werden muss [P1] | kein `fuse=1`, kein fuse-overlayfs |
| `pct start` schlägt fehl | Debug-Ausgabe laut [P1] | `pct start <CTID> --debug` |
| Dateien auf einem Bind-Mount gehören `nobody`, Schreiben scheitert | UID-Verschiebung unprivilegierter Container [P1][P9] | benannte Volumes oder storage-gestützter Mount-Point (Abschnitt 4) |
| Prozesse enden mit Exit-Code 137 | Erfahrungswert, nicht aus der offiziellen Dokumentation: Speichergrenze des LXC erreicht (die Grenze selbst ist belegt [P1]) | RAM erhöhen oder `PG_SHARED_BUFFERS` / `WF_WORKER_CONCURRENCY` senken |

## 8. Nicht getestete Punkte

- Der gesamte Ablauf aus Abschnitt 3 auf einem Proxmox-Host, einschließlich der Beschriftungen der Weboberfläche.
- Docker Engine 29.x (containerd-Image-Store, Snapshotter `overlayfs`) im unprivilegierten LXC unter Proxmox VE 9.2
  mit Kernel 7.0, LXC 7.0 und AppArmor 4.1; ob `nesting=1,keyctl=1` ohne weitere Einstellungen genügt.
- Overlay auf ext4-Raw-Image (LVM-thin, Verzeichnis) und auf ZFS-Subvolume.
- `security_opt: no-new-privileges`, `cap_drop: ALL`, `shm_size`, die Healthchecks und das interne Netz `backend` aus
  `compose.yaml` innerhalb eines LXC; Headless-Chromium (Playwright) im `worker`.
- Image-Bau im LXC mit 2 vCPU / 4 GB (Dauer, Speicherbedarf) und die gesamte Dimensionierung.
- UID-Versatz 100000, Eigentümer der Volumes, Option `idmap`, getrennter Mount-Point für Docker-Daten.
- Netzverwaltung des Templates Debian 13.6 im Hinblick auf den `keyctl`-Vorbehalt zu systemd-networkd.
- vzdump-Sicherung und Wiederherstellung des LXC mit laufendem Docker und PostgreSQL in allen drei Modi; Snapshots.
- Die Beispielregeln für die Proxmox-Firewall; das Verhalten nach Upgrades von Host oder Docker; die VM-Alternative.
- Am Prüfdatum nicht abrufbar: OpenZFS-Release-Notes auf GitHub (HTTP 403). Nicht betrachtet: arm64.

## 9. Quellen

Alle Seiten wurden am 2026-11-10 abgerufen und gelesen. [P9] ist eine Seite des offiziellen Proxmox-Wikis, [P12] der
offizielle Fehlerverfolger; dessen Kommentare stammen teils von Nutzern.

| Kürzel | Quelle | Verwendet für |
|---|---|---|
| [P1] | Proxmox VE Administration Guide, „Proxmox Container Toolkit“, Version 9.2.13 – https://pve.proxmox.com/pve-docs/chapter-pct.html | VM-Empfehlung, OCI-Vorschau, privilegiert/unprivilegiert, AppArmor, cgroup v2, Mount-Points, Bind-Mounts, FUSE, CPU/RAM/Swap, Migration, Debug |
| [P2] | pct.conf(5), Version 9.2.13 – https://pve.proxmox.com/pve-docs/pct.conf.5.html | Wortlaut `features` (`nesting`, `keyctl`, `fuse`, `mknod`, `mount`) |
| [P3] | pct(1) – https://pve.proxmox.com/pve-docs/pct.1.html | Syntax `pct create`, `pct resize`, `pct move-volume`, `pct df` |
| [P4] | Roadmap und Release History – https://pve.proxmox.com/wiki/Roadmap | Versionen 9.0–9.2, AppArmor 4.1, bekanntes Problem mit verschachtelten Containern, Ende von cgroup v1, OCI, Compose als Roadmap-Ziel |
| [P5] | FAQ, Version 9.2.13 – https://pve.proxmox.com/pve-docs/chapter-pve-faq.html | Docker-Aussagen, Unterstützungszeiträume, Update-Befehle |
| [P6] | „Backup and Restore“ – https://pve.proxmox.com/pve-docs/chapter-vzdump.html | Sicherungsmodi für Container, Ausschlüsse, Mount-Points |
| [P7] | „Proxmox VE Storage“ – https://pve.proxmox.com/pve-docs/chapter-pvesm.html | Formate `raw` / `subvol` |
| [P8] | „Proxmox VE Firewall“ – https://pve.proxmox.com/pve-docs/chapter-pve-firewall.html | Aktivierung, Regelsyntax, Warnhinweis |
| [P9] | „Unprivileged LXC containers“ (zuletzt bearbeitet 16.03.2021) – https://pve.proxmox.com/wiki/Unprivileged_LXC_containers | UID-Versatz 100000, Bind-Mounts |
| [P10] | Downloads – https://www.proxmox.com/en/downloads/proxmox-virtual-environment | aktuelles ISO 9.2-1 |
| [P11] | Template-Verzeichnis – http://download.proxmox.com/images/system/ | Debian-13-Template |
| [P12] | Proxmox Bugzilla – https://bugzilla.proxmox.com/show_bug.cgi?id=6538 und https://bugzilla.proxmox.com/show_bug.cgi?id=7006 | belegte AppArmor-Störungen mit Docker im LXC, Status |
| [P13] | Administration Guide 8.4 – https://pve.proxmox.com/pve-docs-8/chapter-pct.html | früherer Wortlaut der VM-Empfehlung |
| [D1] | Docker: Install Docker Engine on Debian – https://docs.docker.com/engine/install/debian/ | unterstützte Debian-Versionen, Installationsbefehle, Firewall-Hinweis |
| [D2] | Docker: Select a storage driver – https://docs.docker.com/engine/storage/drivers/select-storage-driver/ | Treiber, Dateisysteme, `vfs` |
| [D3] | Docker: containerd image store – https://docs.docker.com/engine/storage/containerd/ | Standard ab 29.0, Platzbedarf |
| [D4] | Docker: OverlayFS storage driver – https://docs.docker.com/engine/storage/drivers/overlayfs-driver/ | Voraussetzungen `overlay2` |
| [D5] | Docker: Daemon data directory – https://docs.docker.com/engine/daemon/ | `/var/lib/docker`, `/var/lib/containerd` |
| [D6] | Docker: Packet filtering and firewalls – https://docs.docker.com/engine/network/packet-filtering-firewalls/ | veröffentlichte Ports und ufw |
| [D7] | Docker: ZFS storage driver – https://docs.docker.com/engine/storage/drivers/zfs-driver/ | Einschränkung des `zfs`-Treibers |
| [D8] | Docker: Volumes – https://docs.docker.com/engine/storage/volumes/ | Befüllen leerer Volumes |
