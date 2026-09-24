# Inventaire des fichiers de Linux Manager

Ce document décrit le rôle des fichiers présents dans le projet. L’application est une interface web Flask qui permet d’administrer un serveur Linux : utilisateurs, groupes, fichiers, ACL, tâches cron, journaux et pare-feu.

## Vue d’ensemble

Le fonctionnement général est le suivant :

1. `app.py` reçoit les requêtes HTTP, vérifie la session et le jeton CSRF, valide les données puis exécute les commandes Linux autorisées.
2. Les pages HTML de `templates/` affichent les formulaires et les résultats.
3. `utils/i18n.py` fournit les textes français et anglais.
4. `utils/logging_utils.py` écrit les actions dans `var/log/audit.jsonl`.
5. Les variables de configuration et les secrets viennent de `.env` en développement ou d’un fichier `EnvironmentFile` systemd en production.

## Fichiers à la racine

| Fichier | Utilité |
|---|---|
| `app.py` | Point d’entrée principal de l’application Flask. Il configure Flask, charge l’environnement, gère l’authentification, les sessions, le CSRF, les en-têtes de sécurité, les validations, l’exécution des commandes Linux et toutes les routes web/API. Il couvre les utilisateurs, groupes, fichiers, ACL, cron, journaux et pare-feu UFW/iptables. En production, Gunicorn charge l’objet `app` depuis ce fichier (`app:app`). |
| `user.py` | Ancien prototype en ligne de commande pour créer et gérer des utilisateurs/groupes. La plupart des fonctions sont seulement des affichages et le menu principal n’appelle pas encore réellement ces fonctions. L’application actuelle utilise `app.py`; ce fichier est donc historique ou expérimental. |
| `requirements.txt` | Liste des dépendances Python nécessaires : Flask, Gunicorn et python-dotenv, avec des contraintes de versions majeures/mineures. |
| `.env.example` | Modèle de configuration à copier en `.env`. Il indique la clé secrète Flask, le compte administrateur, le hash du mot de passe, l’expiration du mot de passe et les paramètres SMTP. Il ne doit pas contenir de vraies valeurs secrètes. |
| `.env` | Configuration locale réelle de l’application, notamment les secrets et identifiants. Ce fichier doit rester privé et n’est pas destiné à être versionné. |
| `.gitignore` | Liste les secrets, environnements virtuels, caches Python, journaux, fichiers temporaires d’éditeur, bases locales et historique d’éditeur à exclure de Git. |
| `README.md` | Documentation générale : fonctionnalités, prérequis Linux, installation locale, démarrage, sécurité, avertissements et structure du projet. |
| `DEPLOYMENT_UBUNTU.md` | Procédure de déploiement Ubuntu avec Gunicorn, systemd, Nginx, HTTPS/Certbot et une règle sudo limitée aux commandes utilisées. |
| `design-previews.svg` | Fichier SVG de prévisualisations/conception de l’interface. Il sert de support visuel ou de référence graphique et n’est pas chargé par les routes Flask principales. |

## Dossier `utils/`

| Fichier | Utilité |
|---|---|
| `utils/__init__.py` | Marque `utils` comme paquet Python. Il permet d’importer les modules utilitaires avec `from utils ...`. |
| `utils/i18n.py` | Système d’internationalisation léger sans dépendance externe. Il mémorise la langue dans la session, propose français/anglais, traduit les messages, libellés, titres et boutons, et utilise le français puis la clé comme solution de repli. |
| `utils/logging_utils.py` | Écrit les événements d’audit au format JSON Lines dans `var/log/audit.jsonl`. Les entrées contiennent la date, l’action, la cible, l’acteur et le résultat, sans enregistrer de mot de passe ni de secret. |

## Dossier `static/`

| Fichier | Utilité |
|---|---|
| `static/favicon.svg` | Icône affichée par le navigateur pour identifier Linux Manager dans l’onglet ou les favoris. |

## Dossier `templates/`

Tous les fichiers HTML sont des templates Jinja. La majorité hérite de `base.html`; les pages de formulaire réutilisent `partials/form_card.html`. Les balises de traduction `t(...)`, les formulaires CSRF et les URLs nommées sont injectés depuis `app.py`.

### Templates communs et navigation

| Fichier | Utilité |
|---|---|
| `templates/base.html` | Gabarit commun des pages authentifiées : structure HTML, en-tête, navigation, langue, messages, styles Tailwind chargés par CDN et scripts communs. |
| `templates/menu.html` | Tableau de bord/menu principal donnant accès aux fonctionnalités d’administration. |
| `templates/login.html` | Page de connexion de l’administrateur, avec sélection de langue, validation des identifiants et affichage des erreurs. Elle possède une structure HTML indépendante du gabarit authentifié. |
| `templates/404.html` | Page affichée lorsqu’une route n’existe pas. Elle propose un retour au tableau de bord. |
| `templates/about.html` | Page « À propos » qui présente l’application, les précautions de sécurité et les commandes sudo nécessaires. |
| `templates/partials/form_card.html` | Composant réutilisable pour afficher une carte de formulaire : titre, description, champs, erreurs, bouton, messages et option d’action dangereuse. |

### Utilisateurs et groupes

| Fichier | Utilité |
|---|---|
| `templates/create_user.html` | Formulaire de création d’un utilisateur Linux. |
| `templates/delete_user.html` | Formulaire de suppression d’un utilisateur. |
| `templates/lock_user.html` | Formulaire de verrouillage d’un compte utilisateur. |
| `templates/unlock_user.html` | Formulaire de déverrouillage d’un compte utilisateur. |
| `templates/expire_user.html` | Formulaire de définition de la date d’expiration d’un compte. |
| `templates/change_shell.html` | Formulaire de modification du shell de connexion d’un utilisateur. |
| `templates/change_home.html` | Formulaire de modification/déplacement du répertoire home d’un utilisateur. |
| `templates/change_gecos.html` | Formulaire de modification du nom complet ou champ GECOS d’un utilisateur. |
| `templates/create_group.html` | Formulaire de création d’un groupe Linux. |
| `templates/delete_group.html` | Formulaire de suppression d’un groupe. |
| `templates/rename_group.html` | Formulaire de renommage d’un groupe. |
| `templates/change_group_gid.html` | Formulaire de modification du GID d’un groupe. |
| `templates/add_user_to_group.html` | Formulaire d’ajout d’un utilisateur à un groupe. |
| `templates/add_user_to_group_sudo.html` | Formulaire d’ajout d’un utilisateur au groupe donnant l’accès sudo, avec avertissement de sécurité. |
| `templates/remove_user_from_group.html` | Formulaire de retrait d’un utilisateur d’un groupe. |
| `templates/list_users.html` | Liste paginée et filtrable des utilisateurs système, avec UID, GID, home et shell. |
| `templates/list_groups.html` | Liste paginée et filtrable des groupes système, avec GID et membres. |
| `templates/show_user_groups.html` | Recherche d’un utilisateur et affichage des groupes auxquels il appartient. |
| `templates/show_group_users.html` | Recherche d’un groupe et affichage de ses membres. |

### Sessions, mots de passe et sécurité

| Fichier | Utilité |
|---|---|
| `templates/logged_in_users.html` | Recherche et affichage des utilisateurs actuellement connectés, avec terminal, heure, adresse et PID. |
| `templates/last_logins.html` | Consultation des dernières connexions issues des commandes Linux de journalisation. |
| `templates/change_passwd.html` | Formulaire de changement du mot de passe d’un compte utilisateur. |
| `templates/passwd_forget.html` | Formulaire de réinitialisation d’un mot de passe utilisateur. |
| `templates/password_policy.html` | Formulaire de configuration de la politique de mot de passe avec `chage` : durée minimale, maximale et avertissement. |
| `templates/update_password_last_changed.html` | Formulaire de mise à jour de la date de dernière modification du mot de passe administrateur. |

### Tâches cron

| Fichier | Utilité |
|---|---|
| `templates/list_cron_jobs.html` | Recherche et affichage des tâches cron d’un utilisateur. |
| `templates/add_cron_job.html` | Formulaire d’ajout d’une tâche cron sans écraser les tâches existantes. |
| `templates/delete_cron_job.html` | Formulaire de suppression d’une tâche cron précise. |
| `templates/system_cron.html` | Affichage des fichiers cron système présents sur le serveur. |

### Fichiers, permissions et ACL

| Fichier | Utilité |
|---|---|
| `templates/change_permissions.html` | Formulaire d’application de permissions `chmod` sur un fichier ou dossier. |
| `templates/change_owner.html` | Formulaire de changement de propriétaire ou de groupe avec `chown`. |
| `templates/view_file_permissions.html` | Affichage des informations `stat` d’un fichier ou dossier : type, propriétaire, groupe et permissions. |
| `templates/file_audit.html` | Consultation des événements d’audit système associés à un fichier via `ausearch`. |
| `templates/view_acl.html` | Affichage des ACL d’un fichier ou dossier via `getfacl`. |
| `templates/set_acl.html` | Formulaire d’ajout ou de modification d’une ACL via `setfacl`, éventuellement par défaut et/ou récursif. |
| `templates/remove_acl.html` | Formulaire de suppression d’une ACL précise ou de toutes les ACL. |

### Pare-feu

| Fichier | Utilité |
|---|---|
| `templates/ufw_status.html` | Affichage du statut et des règles actuelles du pare-feu UFW. |
| `templates/ufw_rule.html` | Formulaire d’ajout d’une règle UFW en `allow` ou `deny`. |
| `templates/ufw_delete.html` | Formulaire de suppression d’une règle UFW par numéro ou libellé. |
| `templates/iptables_list.html` | Affichage des règles iptables de la chaîne INPUT. |
| `templates/iptables_rule.html` | Formulaire d’ajout ou de suppression d’une règle iptables avec protocole, port et cible. |

### Journaux d’audit protégés

| Fichier | Utilité |
|---|---|
| `templates/request_log_access.html` | Formulaire de demande d’accès aux journaux. Il déclenche l’envoi d’un code à usage unique à une adresse autorisée. |
| `templates/verify_log_code.html` | Formulaire de vérification du code reçu par e-mail, avec possibilité de renvoyer un code. |
| `templates/log_wrapper.html` | Page d’affichage du journal d’audit après authentification secondaire. |
| `templates/log_info.html` | Fichier actuellement vide ou réservé à un usage futur lié à l’information détaillée d’un journal. La page effective des journaux est `log_wrapper.html`. |

## Données et fichiers générés

| Fichier/dossier | Utilité et précaution |
|---|---|
| `var/log/audit.jsonl` | Journal d’audit produit par `utils/logging_utils.py`. Un événement JSON est écrit par ligne. Le contenu peut révéler les opérations d’administration et doit être protégé. Le dossier `var/log/` est ignoré par Git. |
| `__pycache__/` et `utils/__pycache__/` | Caches générés automatiquement par Python (`.pyc`). Ils ne sont pas des sources et peuvent être recréés. |
| `venv/` | Environnement virtuel Python local contenant Flask, Gunicorn et leurs dépendances. Il est généré par l’installation et ne doit pas être versionné; en production, il est généralement recréé sur le serveur. |
| `.history/` | Historique local de l’éditeur contenant d’anciennes versions de fichiers. Il peut contenir des informations sensibles ou obsolètes et est ignoré par Git. |

## Points importants

- `.env` et les secrets SMTP ne doivent jamais être publiés.
- `app.py` exécute des commandes qui modifient le système réel : le compte de service doit disposer uniquement des commandes sudo nécessaires.
- `user.py` n’est pas le moteur utilisé par l’interface Flask; il s’agit d’un ancien prototype CLI.
- `var/log/audit.jsonl`, les caches Python, `venv/` et `.history/` sont des artefacts locaux ou générés, pas des fichiers fonctionnels à modifier pour ajouter une fonctionnalité.
