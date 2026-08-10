# Linux Manager

Application web Flask destinée à l’administration d’utilisateurs et de groupes sur un serveur Linux. Elle propose une interface unique pour exécuter les opérations système courantes, avec authentification, protection CSRF et journal d’audit.

> Cette application modifie des comptes Linux réels. Déployez-la uniquement sur un serveur administré, derrière HTTPS, et avec des permissions `sudo` strictement limitées.

## Fonctionnalités

- Création et suppression d’utilisateurs et de groupes
- Ajout ou retrait d’un utilisateur d’un groupe, y compris du groupe `sudo`
- Modification ou réinitialisation de mots de passe
- Consultation des groupes d’un utilisateur et des membres d’un groupe
- Recherche des utilisateurs, groupes et sessions actives
- Accès aux journaux d’audit après validation d’un code envoyé par e-mail
- Authentification administrateur, sessions signées et protection CSRF

## Prérequis

- Un serveur Linux compatible avec `adduser`, `addgroup`, `usermod`, `gpasswd`, `groupdel`, `userdel`, `chpasswd`, `getent`, `groups` et `who`
- Python 3.10 ou plus récent
- Des règles `sudo` autorisant uniquement les commandes nécessaires au compte qui exécute l’application

L’application ne doit pas être utilisée telle quelle sous Windows : ses fonctionnalités d’administration exécutent des commandes Linux.

## Installation locale

Clonez le projet, puis créez un environnement virtuel :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Préparez ensuite les variables d’environnement :

```bash
cp .env.example .env
```

Chargez les variables depuis votre méthode habituelle (service systemd, outil de gestion des secrets ou export du shell). L’application ne lit pas automatiquement le fichier `.env`.

Générez une clé de session :

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Générez le hash du mot de passe administrateur :

```bash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('votre-mot-de-passe'))"
```

Définissez au minimum :

```ini
FLASK_SECRET_KEY=cle-longue-et-aleatoire
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=hash-genere-ci-dessus
```

Pour activer la consultation protégée des journaux par e-mail, ajoutez :

```ini
ALLOWED_LOG_EMAILS=admin@example.com,responsable@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=admin@example.com
SMTP_PASSWORD=mot-de-passe-application
```

## Démarrer l’application

Après avoir exporté les variables requises :

```bash
python3 app.py
```

Ouvrez ensuite [http://127.0.0.1:5000](http://127.0.0.1:5000), puis connectez-vous avec les identifiants définis dans `ADMIN_USERNAME` et `ADMIN_PASSWORD_HASH`.

Le serveur de développement écoute uniquement sur `127.0.0.1`. Pour un environnement de production, utilisez Gunicorn derrière un proxy inverse.

## Déploiement Ubuntu

Le guide complet décrit la configuration de l’environnement virtuel, des secrets, des permissions `sudo`, de systemd, de Nginx et de HTTPS :

- [Guide de déploiement Ubuntu](DEPLOYMENT_UBUNTU.md)

Ne donnez jamais `NOPASSWD: ALL` au compte de service. Limitez les droits `sudo` aux exécutables précis employés par l’application.

## Journal d’audit

Les opérations de gestion sont enregistrées dans `var/log/audit.jsonl`. Le journal contient l’horodatage, l’action, la cible, l’administrateur connecté et le statut de l’opération ; aucun mot de passe ni secret n’y est enregistré.

## Structure du projet

```text
app.py                    Application Flask et routes
manager/templates/        Pages HTML de l’interface
utils/logging_utils.py    Écriture du journal d’audit
.env.example              Modèle des variables de configuration
DEPLOYMENT_UBUNTU.md      Procédure de déploiement en production
requirements.txt          Dépendances Python
```

## Sécurité

- Conservez les secrets hors du dépôt et ne versionnez jamais votre fichier `.env`.
- Utilisez un mot de passe administrateur robuste et stockez uniquement son hash.
- Placez l’application derrière HTTPS et limitez son accès au réseau d’administration.
- Testez les règles `sudo` avant la mise en service et sauvegardez les données système importantes.
