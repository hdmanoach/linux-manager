# Linux Manager

Application web Flask d'administration d'utilisateurs, groupes, fichiers, tâches cron, ACL et pare-feu sur un serveur Linux. Interface unique en français pour exécuter les opérations système courantes, avec authentification, protection CSRF et journal d'audit.

> Cette application modifie le système réel (comptes, permissions, pare-feu). Déployez-la uniquement sur un serveur administré, derrière HTTPS, avec des règles `sudo` strictement limitées. **Tout accès admin équivaut à un accès root.**

## Fonctionnalités

- **Utilisateurs** : création, suppression, verrouillage/déverrouillage, expiration, shell, home, nom complet (GECOS), mots de passe, politique `chage`
- **Groupes** : création, suppression, renommage, GID, ajout/retrait de membres, accès `sudo`
- **Consultations** : liste paginée des utilisateurs/groupes, groupes d'un user, membres d'un groupe, sessions actives, dernières connexions
- **Fichiers** : `chmod`, `chown`, consultation `stat`, audit `ausearch`
- **ACL** : consultation (`getfacl`), ajout (`setfacl -m`, options défaut/récursif), suppression (`-x`/`-b`)
- **Pare-feu** : statut et règles UFW (`allow`/`deny`/`delete`), règles iptables (INPUT, ACCEPT/DROP/REJECT)
- **Cron** : tâches par utilisateur, fichiers système, ajout (sans écraser l'existant), suppression
- **Journaux d'audit** : accès protégé par code e-mail à usage unique (5 min)
- **Autocomplete** : users, groupes, chemins fichiers et format `user:group` sur tous les champs concernés
- **Bilingue FR/EN** : sélecteur dans l'en-tête et sur la page de login, langue mémorisée en session (`utils/i18n.py`, sans dépendance externe)
- **Responsive** : sidebar repliable (hamburger) sur mobile, tableaux à défilement horizontal, grilles adaptatives
- Expiration du mot de passe admin configurable, pagination (50/page), overlay de chargement

## Prérequis

- Linux avec : `adduser`, `addgroup`, `usermod`, `gpasswd`, `groupdel`, `groupmod`, `userdel`, `chpasswd`, `chage`, `getent`, `groups`, `who`, `crontab`, `chmod`, `chown`, `stat`, `getfacl`/`setfacl` (paquet `acl`), `ufw`, `iptables`, `ausearch` (paquet `auditd`, optionnel), `lastlog`
- Python 3.10+
- Règles `sudo` **NOPASSWD** limitées aux commandes utilisées (liste exacte : page « À propos » de l'app, section 3 du guide Ubuntu)

> Les actions `sudo` sont **bloquantes** : sans règles NOPASSWD, le serveur demande le mot de passe dans son terminal à chaque action (avec un **timeout de 30 s** par commande).

## Installation locale

Installez les prérequis système (git, venv, ACL) :

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip acl
```

Clonez le dépôt puis entrez dedans :

```bash
git clone https://github.com/hdmanoach/linux-manager.git
cd linux-manager
```

Créez l'environnement virtuel et installez les dépendances :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Générez une clé de session (l'app **refuse de démarrer** sans `FLASK_SECRET_KEY` valide) :

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Générez le hash du mot de passe administrateur :

```bash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('votre-mot-de-passe'))"
```

`.env` minimal :

```ini
FLASK_SECRET_KEY=cle-longue-et-aleatoire
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=hash-genere-ci-dessus
```

Journaux par e-mail (optionnel) :

```ini
ALLOWED_LOG_EMAILS=admin@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=admin@example.com
SMTP_PASSWORD=mot-de-passe-application
```

Expiration du mot de passe admin (optionnel, `0` = jamais) :

```ini
ADMIN_PASSWORD_EXPIRY_DAYS=90
ADMIN_PASSWORD_LAST_CHANGED=2026-01-01T00:00:00
```

## Démarrer

```bash
python3 app.py
```

Ouvrez [http://127.0.0.1:5000](http://127.0.0.1:5000). Le mode debug est désactivé par défaut (`FLASK_DEBUG=1` pour l'activer en développement uniquement). En production, utilisez Gunicorn derrière Nginx : voir [Guide de déploiement Ubuntu](DEPLOYMENT_UBUNTU.md).

## Sécurité

- **Secrets** : jamais versionnés (`.env` ignoré). Démarrage impossible sans vraie clé Flask.
- **Sessions** : cookie `Secure` + `HttpOnly` + `SameSite=Lax`, expiration après 30 min. Note : le flag `Secure` exige HTTPS hors `localhost` — en HTTP simple sur le réseau local, prévoyez HTTPS (voir guide Ubuntu).
- **CSRF** : jeton obligatoire sur tous les POST (sauf login).
- **Brute-force** : 5 tentatives max + cooldown progressif, hash `pbkdf2`, expiration MDP configurable.
- **Injection** : aucune commande shell (listes d'arguments uniquement), noms validés par regex, modes `chmod`/`chown` validés, séparateur `--` anti-injection d'options, redirection `next` limitée aux chemins internes.
- **En-têtes** : `nosniff`, `DENY`, `XSS-Protection`, `Referrer-Policy`.
- **Audit** : chaque opération loguée dans `var/log/audit.jsonl` (sans secrets).

## Avertissements

- **UFW à distance** : une règle `deny` mal placée peut couper votre accès SSH — gardez une session de secours.
- **iptables** : les règles sont **perdues au reboot** sans `iptables-persistent` — l'app ne gère pas la persistance.
- **`userdel` sans `-r`** : le home est conservé (sécurité) — nettoyez avec `rm -rf /home/<user>` si besoin.
- **Cron** : l'ajout préserve les tâches existantes de l'utilisateur.

## Structure du projet

```text
app.py                    Application Flask et routes (~1000 lignes)
templates/                ~45 pages HTML (base, menu, formulaires, affichages)
templates/partials/       Carte de formulaire réutilisable
static/favicon.svg        Favicon
utils/logging_utils.py    Écriture du journal d'audit
.env.example              Modèle de configuration
DEPLOYMENT_UBUNTU.md      Procédure de déploiement en production
requirements.txt          Dépendances Python
var/log/audit.jsonl       Journal d'audit (non versionné)
```
