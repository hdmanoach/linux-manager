# Déployer Linux Manager sur Ubuntu

Ce guide publie l'application Flask derrière **Gunicorn** et **Nginx**. Les commandes sont à exécuter sur le serveur Ubuntu, depuis le dossier du projet.

> L'application gère des comptes Linux. N'exposez pas ce site directement sur Internet sans authentification, HTTPS et règles `sudo` restrictives.

## 1. Préparer le serveur

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git acl
sudo adduser --system --group --home /opt/linux-manager linuxmanager
```

Clonez le dépôt directement à sa place finale :

```bash
sudo git clone -b main https://github.com/hdmanoach/linux-manager.git /opt/linux-manager
sudo chown -R linuxmanager:linuxmanager /opt/linux-manager
```

Créez l'environnement virtuel avec le compte de service :

```bash
sudo -u linuxmanager -H bash
cd /opt/linux-manager
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
exit
```

## 2. Variables secrètes

Créez le fichier `/etc/linux-manager.env` :

```bash
sudo nano /etc/linux-manager.env
```

Son contenu doit ressembler à ceci :

```ini
FLASK_SECRET_KEY=remplacez-par-une-cle-longue-et-aleatoire
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=pbkdf2:sha256:600000$remplacez$par-un-vrai-hash
ADMIN_PASSWORD_EXPIRY_DAYS=90
ADMIN_PASSWORD_LAST_CHANGED=
ALLOWED_LOG_EMAILS=admin@example.com,responsable@example.com
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=admin@example.com
SMTP_PASSWORD=mot-de-passe-application
```

> `ADMIN_PASSWORD_EXPIRY_DAYS=0` désactive l'expiration. `ADMIN_PASSWORD_LAST_CHANGED` se met à jour depuis la page « Expiration MDP » de l'app.

Générez une clé sûre avec :

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Générez le hash du mot de passe administrateur :

```bash
/opt/linux-manager/.venv/bin/python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('votre-mot-de-passe'))"
```

Protégez le fichier :

```bash
sudo chown root:linuxmanager /etc/linux-manager.env
sudo chmod 640 /etc/linux-manager.env
```

## 3. Autoriser uniquement les commandes nécessaires avec sudo

Ne donnez jamais un accès `NOPASSWD: ALL` à l'utilisateur du service.

Obtenez les chemins des commandes (toutes celles utilisées par l'app) :

```bash
command -v adduser addgroup usermod gpasswd groupdel groupmod userdel chpasswd chage chmod chown stat crontab lastlog ausearch getfacl setfacl ufw iptables
```

Créez une règle sudo :

```bash
sudo visudo -f /etc/sudoers.d/linux-manager
```

Adaptez les chemins au résultat de `command -v`, puis ajoutez par exemple :

```sudoers
Cmnd_Alias LINUX_MANAGER = /usr/sbin/adduser, /usr/sbin/addgroup, /usr/sbin/usermod, /usr/bin/gpasswd, /usr/sbin/groupdel, /usr/sbin/groupmod, /usr/sbin/userdel, /usr/sbin/chpasswd, /usr/bin/chage, /usr/bin/chmod, /usr/bin/chown, /usr/bin/stat, /usr/bin/crontab, /usr/bin/lastlog, /usr/sbin/ausearch, /usr/bin/getfacl, /usr/bin/setfacl, /usr/sbin/ufw, /usr/sbin/iptables
linuxmanager ALL=(root) NOPASSWD: LINUX_MANAGER
```

Validez la syntaxe :

```bash
sudo visudo -cf /etc/sudoers.d/linux-manager
```

## 4. Créer le service systemd

Créez `/etc/systemd/system/linux-manager.service` :

```bash
sudo nano /etc/systemd/system/linux-manager.service
```

Collez :

```ini
[Unit]
Description=Linux Manager Flask
After=network.target

[Service]
User=linuxmanager
Group=linuxmanager
WorkingDirectory=/opt/linux-manager
EnvironmentFile=/etc/linux-manager.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/linux-manager/.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:5000 app:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Activez et vérifiez le service :

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now linux-manager
sudo systemctl status linux-manager
```

Pour suivre les erreurs :

```bash
sudo journalctl -u linux-manager -f
```

Vérifiez que l'app répond en local avant de continuer :

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5000/login/
```

Vous devez obtenir `200`. Sinon, consultez les logs ci-dessus (souvent : `.env` manquant ou règle sudo absente).

## 5. Configurer Nginx

Créez `/etc/nginx/sites-available/linux-manager` :

```bash
sudo nano /etc/nginx/sites-available/linux-manager
```

Remplacez `manager.example.com` par votre nom de domaine :

```nginx
server {
    listen 80;
    server_name manager.example.com;

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Activez la configuration :

```bash
sudo ln -s /etc/nginx/sites-available/linux-manager /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

> ⚠️ N'activez UFW que **après** avoir autorisé SSH, sinon vous perdez l'accès distant :
>
> ```bash
> sudo ufw allow OpenSSH
> sudo ufw allow 'Nginx Full'
> sudo ufw enable
> ```

## 6. Activer HTTPS

Après avoir dirigé le DNS de votre domaine vers le serveur :

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d manager.example.com
```

## Mettre à jour l’application

```bash
cd /opt/linux-manager
sudo git pull origin main
sudo chown -R linuxmanager:linuxmanager /opt/linux-manager
sudo -u linuxmanager -H .venv/bin/pip install -r requirements.txt
sudo systemctl restart linux-manager
sudo journalctl -u linux-manager -n 50 --no-pager
```
