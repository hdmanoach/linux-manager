"""Application Flask de gestion des utilisateurs et groupes Linux."""
import os
import secrets
import smtplib
import string
import subprocess
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from jinja2 import FileSystemLoader
from markupsafe import Markup, escape
import re
import json

from utils import logging_utils
from utils.i18n import LANGS, get_lang, t
from werkzeug.security import check_password_hash

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

class DjangoTemplateLoader(FileSystemLoader):
    """Compatibilité temporaire pour les tags Django conservés dans les templates."""
    def get_source(self, environment, template):
        source, filename, uptodate = super().get_source(environment, template)
        source = re.sub(r"\{%\s*url\s+'([^']+)'\s*%\}", r"{{ url_for('\1') }}", source)
        source = re.sub(r"\{%\s*csrf_token\s*%\}", "{{ csrf_token_input() }}", source)
        source = re.sub(r"\{%\s*empty\s*%\}", "{% else %}", source)
        source = re.sub(r"\|default:'([^']*)'", r"|default('\1')", source)
        def include(match):
            assignments = re.findall(r"(\w+)=((?:\"[^\"]*\")|(?:'[^']*')|True|False|t\('[^']*'\))", match.group(1))
            return "".join("{% set " + name + " = " + value + " %}" for name, value in assignments) + '{% include "partials/form_card.html" %}'
        source = re.sub(r'\{%\s*include\s+"partials/form_card.html"\s+with\s+(.+?)\s*%\}', include, source)
        return source, filename, uptodate


class Field:
    def __init__(self, name, label, value, type_, autocomplete=None):
        self.name, self.label, self.value, self.type, self.id_for_label = name, label, value, type_, f"id_{name}"
        self.autocomplete = autocomplete
    def __html__(self):
        ac_attr = f' data-autocomplete="{escape(self.autocomplete)}"' if self.autocomplete else ''
        return Markup('<input class="field" id="%s" name="%s" type="%s" value="%s" autocomplete="off"%s required>' % (escape(self.id_for_label), escape(self.name), escape(self.type), escape(self.value), ac_attr))
    __str__ = lambda self: str(self.__html__())


class FormData(dict):
    def __iter__(self): return iter(self.values())
    __getattr__ = dict.__getitem__


app = Flask(__name__, template_folder="templates")
app.jinja_loader = DjangoTemplateLoader(str(BASE_DIR / "templates"))
_secret_key = os.environ.get("FLASK_SECRET_KEY", "")
if not _secret_key or _secret_key == "change-me-in-production":
    raise RuntimeError("FLASK_SECRET_KEY manquante ou invalide : définissez une clé secrète forte dans .env.")
app.config["SECRET_KEY"] = _secret_key
app.config["LOG_EMAILS"] = set(filter(None, os.environ.get("ALLOWED_LOG_EMAILS", "").split(",")))
app.config["ADMIN_USERNAME"] = os.environ.get("ADMIN_USERNAME", "")
app.config["ADMIN_PASSWORD_HASH"] = os.environ.get("ADMIN_PASSWORD_HASH", "")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)
app.config["MAX_LOGIN_ATTEMPTS"] = 5
app.config["ADMIN_PASSWORD_EXPIRY_DAYS"] = int(os.environ.get("ADMIN_PASSWORD_EXPIRY_DAYS", "90"))
app.config["ADMIN_PASSWORD_LAST_CHANGED"] = os.environ.get("ADMIN_PASSWORD_LAST_CHANGED", "")
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "True") == "True"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def is_admin_password_expired():
    """Vérifie si le mot de passe administrateur a expiré."""
    last_changed = app.config["ADMIN_PASSWORD_LAST_CHANGED"]
    if not last_changed:
        return False
    try:
        last_changed_date = datetime.fromisoformat(last_changed)
        expiry_days = app.config["ADMIN_PASSWORD_EXPIRY_DAYS"]
        if expiry_days <= 0:
            return False
        return datetime.now() > last_changed_date + timedelta(days=expiry_days)
    except (ValueError, TypeError):
        return False


def current_admin():
    return session.get("admin_username")


@app.context_processor
def inject_security_context():
    def csrf_token_input():
        token = session.get("csrf_token")
        if not token:
            token = os.urandom(32).hex(); session["csrf_token"] = token
        return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')
    return {"current_admin": current_admin(), "csrf_token_input": csrf_token_input, "t": t, "current_lang": get_lang()}


@app.route("/lang/<code>/")
def set_language(code):
    if code in LANGS:
        session["lang"] = code
    destination = request.args.get("next") or request.referrer or url_for("menu")
    parsed = urlparse(destination)
    if parsed.netloc or parsed.scheme or not parsed.path.startswith("/"):
        destination = url_for("menu")
    return redirect(destination)


@app.before_request
def protect_application():
    public_endpoints = {"login", "static", "not_found", "set_language"}
    if request.method == "POST" and request.endpoint not in public_endpoints:
        if not session.get("csrf_token") or request.form.get("csrf_token") != session.get("csrf_token"):
            abort(400, t("err_csrf"))
    if request.endpoint not in public_endpoints and not current_admin():
        return redirect(url_for("login", next=request.path))
    login_attempts = session.get("login_attempts", 0)
    last_attempt = session.get("last_login_attempt")
    if login_attempts >= 3 and last_attempt:
        try:
            last_time = datetime.fromisoformat(last_attempt)
            cooldown = timedelta(seconds=30 * (login_attempts - 2))
            if datetime.now() < last_time + cooldown:
                remaining = int(((last_time + cooldown) - datetime.now()).total_seconds())
                if request.endpoint == "login" and request.method == "POST":
                    abort(429, t("err_rate_limit").format(seconds=remaining))
        except (ValueError, TypeError):
            pass


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def form_data(*fields):
    """Construit des champs simples, compatibles avec les templates existants."""
    values = request.form if request.method == "POST" else {}
    result = FormData()
    for field_def in fields:
        if len(field_def) == 4:
            name, label, type_, autocomplete = field_def
        else:
            name, label, type_ = field_def
            autocomplete = None
        result[name] = Field(name, label, values.get(name, ""), type_, autocomplete)
    return result


class CommandTimeout(OSError):
    """Une commande système a dépassé le délai imparti."""


def run(command, **kwargs):
    # Bloquant : sudo peut demander le mot de passe dans le terminal du serveur.
    # Timeout de sécurité : aucune commande ne doit figer un worker indéfiniment.
    kwargs.setdefault("timeout", 30)
    try:
        return subprocess.run(list(command), check=True, capture_output=True, text=True, **kwargs)
    except subprocess.TimeoutExpired:
        raise CommandTimeout(f"Commande trop longue (>{kwargs['timeout']}s), abandonnée.")


def send_code(email, code):
    host, port = os.environ.get("SMTP_HOST"), os.environ.get("SMTP_PORT", "587")
    username, password = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    if not all((host, username, password)):
        raise RuntimeError("Configurez SMTP_HOST, SMTP_USER et SMTP_PASSWORD pour envoyer les codes.")
    message = EmailMessage()
    message["Subject"] = t("email_subject")
    message["From"] = username
    message["To"] = email
    message.set_content(t("email_body").format(code=code))
    with smtplib.SMTP(host, int(port)) as smtp:
        smtp.starttls(); smtp.login(username, password); smtp.send_message(message)


def valid_linux_name(value):
    return bool(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}\$?", value))


def valid_mode(value):
    """Mode chmod : octal (755, 644) ou symbolique (u+rwx, g-w, a=rX)."""
    return bool(re.fullmatch(r"[0-7]{3,4}", value) or re.fullmatch(r"([ugoa]*[+-=][rwxXst]*)(,([ugoa]*[+-=][rwxXst]*))*", value))


def valid_owner(value):
    """Propriétaire chown : user ou user:group."""
    return bool(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}(:[a-z_][a-z0-9_-]{0,31})?", value))


def valid_password(password):
    """Vérifie la complexité du mot de passe : min 8 car., majuscule, minuscule, chiffre."""
    if len(password) < 8:
        return False, t("err_pwd_short")
    if not re.search(r"[A-Z]", password):
        return False, t("err_pwd_upper")
    if not re.search(r"[a-z]", password):
        return False, t("err_pwd_lower")
    if not re.search(r"[0-9]", password):
        return False, t("err_pwd_digit")
    return True, ""


def audit(target, event, success=True):
    try:
        logging_utils.log_user_event(target, event, actor=current_admin() or "unknown", success=success)
    except OSError:
        app.logger.error("Écriture du journal d'audit impossible.")


@app.route("/login/", methods=["GET", "POST"])
def login():
    error = None
    if is_admin_password_expired():
        error = t("err_pwd_expired")
        return render_template("login.html", error=error)
    if request.method == "POST":
        login_attempts = session.get("login_attempts", 0)
        if login_attempts >= app.config["MAX_LOGIN_ATTEMPTS"]:
            error = t("err_too_many")
        else:
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            if not app.config["ADMIN_USERNAME"] or not app.config["ADMIN_PASSWORD_HASH"]:
                error = t("err_not_configured")
            elif username == app.config["ADMIN_USERNAME"] and check_password_hash(app.config["ADMIN_PASSWORD_HASH"], password):
                session.clear(); session["admin_username"] = username; session.permanent = True
                audit(username, t("audit_login_ok"))
                destination = request.args.get("next") or url_for("menu")
                parsed = urlparse(destination)
                if parsed.netloc or parsed.scheme or not parsed.path.startswith("/"):
                    destination = url_for("menu")
                return redirect(destination)
            else:
                session["login_attempts"] = login_attempts + 1
                session["last_login_attempt"] = datetime.now().isoformat()
                audit(username or "-", t("audit_login_fail"), success=False)
                error = t("err_bad_credentials")
    return render_template("login.html", error=error)


@app.post("/logout/")
def logout():
    audit(current_admin() or "-", t("audit_logout"))
    session.clear()
    return redirect(url_for("login"))


@app.route("/about/")
def about():
    return render_template("about.html")


@app.route("/")
@app.route("/menu/")
def menu():
    return render_template("menu.html")


def action_page(template, fields, command_builder, success, danger=False):
    form = form_data(*fields); message = error = None
    if request.method == "POST":
        values = {name: request.form.get(name, "").strip() for name, *_ in fields}
        names = [value for key, value in values.items() if key in {"username", "group_name", "new_name"}]
        if not all(values.values()):
            error = t("err_required")
        elif not all(valid_linux_name(value) for value in names):
            error = t("err_linux_name")
        else:
            try:
                command, input_text = command_builder(values)
                run(command, input=input_text) if input_text is not None else run(command)
                audit(values.get("username") or values.get("group_name"), template.removesuffix(".html"), success=True)
                message = success(values)
                form = form_data(*fields)
            except (subprocess.CalledProcessError, OSError) as exc:
                app.logger.error("Commande système échouée: %s", exc)
                audit(values.get("username") or values.get("group_name"), template.removesuffix(".html"), success=False)
                error = t("err_op_failed")
    return render_template(template, form=form, message=message, error=error, danger=danger)


@app.route("/create_user/", methods=["GET", "POST"])
def create_user():
    fields = (("username", t("field_username"), "text", "users"), ("password", t("field_password"), "password"))
    form = form_data(*fields); message = error = None
    if request.method == "POST":
        username, password = request.form.get("username", "").strip(), request.form.get("password", "")
        if not username or not password:
            error = t("err_required")
        elif not valid_linux_name(username):
            error = t("err_bad_username")
        else:
            password_valid, password_error = valid_password(password)
            if not password_valid:
                error = password_error
            else:
                try:
                    run(["sudo", "adduser", "--disabled-password", "--gecos", "", username])
                    run(["sudo", "chpasswd"], input=f"{username}:{password}\n")
                    audit(username, t("audit_user_created"))
                    message = t("msg_user_created").format(name=username); form = form_data(*fields)
                except (subprocess.CalledProcessError, OSError) as exc:
                    app.logger.error("Création utilisateur échouée: %s", exc); error = t("err_user_create")
    return render_template("create_user.html", form=form, message=message, error=error)


@app.route("/create_group/", methods=["GET", "POST"])
def create_group():
    return action_page("create_group.html", (("group_name", t("field_group"), "text", "groups"),), lambda v: (["sudo", "addgroup", v["group_name"]], None), lambda v: t("msg_group_created").format(name=v["group_name"]))


@app.route("/add_user_to_group/", methods=["GET", "POST"])
def add_user_to_group():
    return action_page("add_user_to_group.html", (("username", t("field_username"), "text", "users"), ("group_name", t("field_group"), "text", "groups")), lambda v: (["sudo", "usermod", "-aG", v["group_name"], v["username"]], None), lambda v: t("msg_added_to_group").format(name=v["group_name"]))


@app.route("/add_user_to_group_sudo/", methods=["GET", "POST"])
def add_user_to_group_sudo():
    return action_page("add_user_to_group_sudo.html", (("username", t("field_username"), "text", "users"),), lambda v: (["sudo", "usermod", "-aG", "sudo", v["username"]], None), lambda v: t("msg_sudo_granted").format(name=v["username"]))


@app.route("/remove_user_from_group/", methods=["GET", "POST"])
def remove_user_from_group():
    return action_page("remove_user_from_group.html", (("username", t("field_username"), "text", "users"), ("group_name", t("field_group"), "text", "groups")), lambda v: (["sudo", "gpasswd", "-d", v["username"], v["group_name"]], None), lambda v: t("msg_removed_from_group"))


@app.route("/delete_group/", methods=["GET", "POST"])
def delete_group():
    return action_page("delete_group.html", (("group_name", t("field_group"), "text", "groups"),), lambda v: (["sudo", "groupdel", v["group_name"]], None), lambda v: t("msg_group_deleted"), True)


@app.route("/rename_group/", methods=["GET", "POST"])
def rename_group():
    return action_page("rename_group.html", (("group_name", t("field_group_current"), "text", "groups"), ("new_name", t("field_group_new"), "text")), lambda v: (["sudo", "groupmod", "--new-name", v["new_name"], v["group_name"]], None), lambda v: t("msg_group_renamed").format(name=v["new_name"]))


@app.route("/change_group_gid/", methods=["GET", "POST"])
def change_group_gid():
    return action_page("change_group_gid.html", (("group_name", t("field_group"), "text", "groups"), ("gid", t("field_gid"), "number")), lambda v: (["sudo", "groupmod", "--gid", v["gid"], v["group_name"]], None), lambda v: t("msg_gid_updated").format(name=v["group_name"]))


@app.route("/delete_user/", methods=["GET", "POST"])
def delete_user():
    return action_page("delete_user.html", (("username", t("field_username"), "text", "users"),), lambda v: (["sudo", "userdel", v["username"]], None), lambda v: t("msg_user_deleted"), True)


@app.route("/lock_user/", methods=["GET", "POST"])
def lock_user():
    return action_page("lock_user.html", (("username", t("field_username"), "text", "users"),), lambda v: (["sudo", "usermod", "-L", v["username"]], None), lambda v: t("msg_locked").format(name=v["username"]))


@app.route("/unlock_user/", methods=["GET", "POST"])
def unlock_user():
    return action_page("unlock_user.html", (("username", t("field_username"), "text", "users"),), lambda v: (["sudo", "usermod", "-U", v["username"]], None), lambda v: t("msg_unlocked").format(name=v["username"]))


@app.route("/expire_user/", methods=["GET", "POST"])
def expire_user():
    return action_page("expire_user.html", (("username", t("field_username"), "text", "users"), ("expire_date", t("field_expire"), "date")), lambda v: (["sudo", "chage", "-E", v["expire_date"], v["username"]], None), lambda v: t("msg_expire_set").format(name=v["username"]))


@app.route("/password_policy/", methods=["GET", "POST"])
def password_policy():
    form = form_data(("username", t("field_username"), "text", "users"), ("max_days", t("field_max_days"), "number"), ("min_days", t("field_min_days"), "number"), ("warn_days", t("field_warn_days"), "number"))
    message = error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        max_days = request.form.get("max_days", "").strip()
        min_days = request.form.get("min_days", "").strip()
        warn_days = request.form.get("warn_days", "").strip()
        if not valid_linux_name(username):
            error = t("err_bad_username")
        else:
            try:
                if max_days: run(["sudo", "chage", "-M", max_days, username])
                if min_days: run(["sudo", "chage", "-m", min_days, username])
                if warn_days: run(["sudo", "chage", "-W", warn_days, username])
                audit(username, t("audit_policy"))
                message = t("msg_policy_updated")
                form = form_data(("username", t("field_username"), "text", "users"), ("max_days", t("field_max_days"), "number"), ("min_days", t("field_min_days"), "number"), ("warn_days", t("field_warn_days"), "number"))
            except (subprocess.CalledProcessError, OSError):
                error = t("err_policy")
    return render_template("password_policy.html", form=form, message=message, error=error)


@app.route("/change_shell/", methods=["GET", "POST"])
def change_shell():
    return action_page("change_shell.html", (("username", t("field_username"), "text", "users"), ("shell", t("field_shell"), "text")), lambda v: (["sudo", "usermod", "--shell", v["shell"], v["username"]], None), lambda v: t("msg_shell_updated").format(name=v["username"]))


@app.route("/change_home/", methods=["GET", "POST"])
def change_home():
    return action_page("change_home.html", (("username", t("field_username"), "text", "users"), ("home_dir", t("field_home"), "text", "files")), lambda v: (["sudo", "usermod", "--home-dir", v["home_dir"], "--move-home", v["username"]], None), lambda v: t("msg_home_updated").format(name=v["username"]))


@app.route("/change_gecos/", methods=["GET", "POST"])
def change_gecos():
    return action_page("change_gecos.html", (("username", t("field_username"), "text", "users"), ("full_name", t("field_fullname"), "text")), lambda v: (["sudo", "usermod", "--comment", v["full_name"], v["username"]], None), lambda v: t("msg_gecos_updated").format(name=v["username"]))


@app.route("/last_logins/", methods=["GET", "POST"])
def last_logins():
    form = form_data(("username", t("field_username_optional"), "text", "users"))
    last_entries = []; lastlog_entries = []; error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if username and not valid_linux_name(username):
            error = t("err_bad_username")
            return render_template("last_logins.html", form=form, last_entries=last_entries, lastlog_entries=lastlog_entries, error=error)
        try:
            last_cmd = ["last", username] if username else ["last"]
            last_output = run(last_cmd).stdout
            for line in last_output.splitlines()[:-2]:
                parts = line.split()
                if len(parts) >= 4:
                    last_entries.append({"user": parts[0], "terminal": parts[1], "host": parts[2], "login": " ".join(parts[3:5]), "duration": parts[5] if len(parts) > 5 else ""})
            lastlog_output = run(["sudo", "lastlog"]).stdout
            for line in lastlog_output.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 3:
                    lastlog_entries.append({"user": parts[0], "last_login": " ".join(parts[1:5]) if parts[1] != "Never" else t("never_connected")})
        except (subprocess.CalledProcessError, OSError):
            error = t("err_lastlog")
    return render_template("last_logins.html", form=form, last_entries=last_entries, lastlog_entries=lastlog_entries, error=error)


@app.route("/show_user_groups/", methods=["GET", "POST"])
def show_user_groups():
    form = form_data(("username", t("field_username"), "text", "users")); username = None; groups = []; error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if not valid_linux_name(username): error = t("err_bad_username")
        elif username:
            try: groups = run(["groups", username]).stdout.partition(":")[2].split()
            except (subprocess.CalledProcessError, OSError): error = t("err_user_groups")
    return render_template("show_user_groups.html", form=form, username=username, user_groups=groups, error=error)


@app.route("/show_group_users/", methods=["GET", "POST"])
def show_group_users():
    form = form_data(("group_name", t("field_group"), "text", "groups")); group_name = None; users = []; error = None
    if request.method == "POST":
        group_name = request.form.get("group_name", "").strip()
        if not valid_linux_name(group_name): error = t("err_bad_group")
        elif group_name:
            try: users = [u for u in run(["getent", "group", group_name]).stdout.strip().split(":")[3].split(",") if u]
            except (subprocess.CalledProcessError, OSError, IndexError): error = t("err_group_users")
    return render_template("show_group_users.html", form=form, group_name=group_name, group_users=users, error=error)


def passwd_rows():
    return [{"username": p[0], "uid": p[2], "gid": p[3], "home_directory": p[5], "shell": p[6]} for p in (line.split(":") for line in run(["getent", "passwd"]).stdout.splitlines()) if len(p) >= 7]

@app.route("/list_users/", methods=["GET", "POST"])
def list_users():
    query = request.form.get("username", "").strip(); error = None
    page = request.args.get("page", 1, type=int)
    per_page = 50
    try:
        all_users = [u for u in passwd_rows() if not query or u["username"].startswith(query)]
        total = len(all_users)
        total_pages = (total + per_page - 1) // per_page
        users = all_users[(page - 1) * per_page : page * per_page]
    except (subprocess.CalledProcessError, OSError): users=[]; error=t("err_list_users"); total=0; total_pages=0
    return render_template("list_users.html", form=form_data(("username", t("field_username"), "text", "users")), user_list=users, error=error, page=page, total_pages=total_pages, total=total, query=query)


@app.route("/list_groups/", methods=["GET", "POST"])
def list_groups():
    query = request.form.get("group_name", "").strip(); error = None
    page = request.args.get("page", 1, type=int)
    per_page = 50
    try:
        all_groups=[{"group_name":p[0],"gid":p[2],"member":p[3]} for p in (line.split(":") for line in run(["getent","group"]).stdout.splitlines()) if len(p)>=4 and (not query or p[0]==query)]
        total = len(all_groups)
        total_pages = (total + per_page - 1) // per_page
        groups = all_groups[(page - 1) * per_page : page * per_page]
    except (subprocess.CalledProcessError, OSError): groups=[]; error=t("err_list_groups"); total=0; total_pages=0
    return render_template("list_groups.html", form=form_data(("group_name", t("field_group"), "text", "groups")), group_list=groups, error=error, page=page, total_pages=total_pages, total=total, query=query)


@app.route("/logged_in_users/", methods=["GET", "POST"])
def logged_in_users():
    query=request.form.get("username", "").strip(); users=[]; error=None
    try:
        for p in (line.split() for line in run(["who", "-u"]).stdout.splitlines()):
            if len(p)>=5 and (not query or query in p[0]): users.append({"username":p[0],"terminal":p[1],"login_time":" ".join(p[2:4]),"host":p[-2],"pid":p[-1]})
    except (subprocess.CalledProcessError, OSError): error=t("err_sessions")
    return render_template("logged_in_users.html", form=form_data(("username", t("field_username"), "text", "users")), users=users, error=error)


@app.route("/list_cron_jobs/", methods=["GET", "POST"])
def list_cron_jobs():
    form = form_data(("username", t("field_username"), "text", "users"))
    cron_entries = []; error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if not valid_linux_name(username):
            error = t("err_bad_username")
        else:
            try:
                output = run(["sudo", "crontab", "-l", "-u", username]).stdout
                for line in output.splitlines():
                    if line and not line.startswith("#"):
                        parts = line.split(None, 5)
                        if len(parts) >= 6:
                            cron_entries.append({"schedule": " ".join(parts[:5]), "command": parts[5]})
            except subprocess.CalledProcessError:
                error = t("err_cron_none").format(name=username)
            except OSError:
                error = t("err_cron_read")
    return render_template("list_cron_jobs.html", form=form, cron_entries=cron_entries, error=error)


@app.route("/system_cron/", methods=["GET"])
def system_cron():
    cron_files = []; error = None
    try:
        output = run(["ls", "/etc/cron.d/"]).stdout
        for filename in output.splitlines():
            if filename:
                try:
                    content = run(["cat", f"/etc/cron.d/{filename}"]).stdout
                    cron_files.append({"filename": filename, "content": content})
                except (subprocess.CalledProcessError, OSError):
                    cron_files.append({"filename": filename, "content": t("err_file_unreadable")})
    except (subprocess.CalledProcessError, OSError):
        error = t("err_system_cron")
    return render_template("system_cron.html", cron_files=cron_files, error=error)


@app.route("/add_cron_job/", methods=["GET", "POST"])
def add_cron_job():
    form = form_data(("username", t("field_username"), "text", "users"), ("schedule", t("field_schedule"), "text"), ("command", t("field_command"), "text"))
    message = error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        schedule = request.form.get("schedule", "").strip()
        command = request.form.get("command", "").strip()
        if not valid_linux_name(username):
            error = t("err_bad_username")
        elif not schedule or not command:
            error = t("err_required")
        else:
            try:
                try:
                    existing = run(["sudo", "crontab", "-l", "-u", username]).stdout
                except subprocess.CalledProcessError:
                    existing = ""
                if existing and not existing.endswith("\n"):
                    existing += "\n"
                run(["sudo", "crontab", "-u", username, "-"], input=existing + f"{schedule} {command}\n")
                audit(username, t("audit_cron_added"))
                message = t("msg_cron_added").format(name=username)
                form = form_data(("username", t("field_username"), "text", "users"), ("schedule", t("field_schedule"), "text"), ("command", t("field_command"), "text"))
            except (subprocess.CalledProcessError, OSError):
                error = t("err_cron_add")
    return render_template("add_cron_job.html", form=form, message=message, error=error)


@app.route("/delete_cron_job/", methods=["GET", "POST"])
def delete_cron_job():
    form = form_data(("username", t("field_username"), "text", "users"), ("command", t("field_command_del"), "text"))
    message = error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        command = request.form.get("command", "").strip()
        if not valid_linux_name(username):
            error = t("err_bad_username")
        elif not command:
            error = t("err_command_required")
        else:
            try:
                current_crontab = run(["sudo", "crontab", "-l", "-u", username]).stdout
                new_lines = [line for line in current_crontab.splitlines() if command not in line]
                new_crontab = "\n".join(new_lines) + "\n"
                run(["sudo", "crontab", "-u", username, "-"], input=new_crontab)
                audit(username, t("audit_cron_deleted"))
                message = t("msg_cron_deleted").format(name=username)
                form = form_data(("username", t("field_username"), "text", "users"), ("command", t("field_command_del"), "text"))
            except subprocess.CalledProcessError:
                error = t("err_cron_read_user").format(name=username)
            except OSError:
                error = t("err_system")
    return render_template("delete_cron_job.html", form=form, message=message, error=error)


@app.route("/change_permissions/", methods=["GET", "POST"])
def change_permissions():
    form = form_data(("file_path", t("field_path"), "text", "files"), ("permissions", t("field_perms"), "text"))
    message = error = None
    if request.method == "POST":
        file_path = request.form.get("file_path", "").strip()
        permissions = request.form.get("permissions", "").strip()
        if not file_path:
            error = t("err_path_required")
        elif not permissions:
            error = t("err_perms_required")
        elif not valid_mode(permissions):
            error = t("err_bad_mode")
        else:
            try:
                run(["sudo", "chmod", "--", permissions, file_path])
                audit(file_path, t("audit_perms"))
                message = t("msg_perms_updated").format(path=file_path, mode=permissions)
                form = form_data(("file_path", t("field_path"), "text", "files"), ("permissions", t("field_perms"), "text"))
            except (subprocess.CalledProcessError, OSError):
                error = t("err_chmod")
    return render_template("change_permissions.html", form=form, message=message, error=error)


@app.route("/change_owner/", methods=["GET", "POST"])
def change_owner():
    form = form_data(("file_path", t("field_path"), "text", "files"), ("owner", t("field_owner"), "text", "usergroup"))
    message = error = None
    if request.method == "POST":
        file_path = request.form.get("file_path", "").strip()
        owner = request.form.get("owner", "").strip()
        if not file_path:
            error = t("err_path_required")
        elif not owner:
            error = t("err_owner_required")
        elif not valid_owner(owner):
            error = t("err_bad_owner")
        else:
            try:
                run(["sudo", "chown", "--", owner, file_path])
                audit(file_path, t("audit_owner"))
                message = t("msg_owner_changed").format(path=file_path, owner=owner)
                form = form_data(("file_path", t("field_path"), "text", "files"), ("owner", t("field_owner"), "text", "usergroup"))
            except (subprocess.CalledProcessError, OSError):
                error = t("err_chown")
    return render_template("change_owner.html", form=form, message=message, error=error)


@app.route("/view_file_permissions/", methods=["GET", "POST"])
def view_file_permissions():
    form = form_data(("file_path", t("field_path"), "text", "files"))
    permissions_info = None; error = None
    if request.method == "POST":
        file_path = request.form.get("file_path", "").strip()
        if not file_path:
            error = t("err_path_required")
        else:
            try:
                stat_output = run(["sudo", "stat", "-c", "%a %U %G %n", "--", file_path]).stdout.strip()
                parts = stat_output.split(None, 3)
                if len(parts) >= 4:
                    permissions_info = {"mode": parts[0], "owner": parts[1], "group": parts[2], "path": parts[3]}
                else:
                    error = t("err_stat_read")
            except (subprocess.CalledProcessError, OSError):
                error = t("err_not_found")
    return render_template("view_file_permissions.html", form=form, permissions_info=permissions_info, error=error)


@app.route("/file_audit/", methods=["GET", "POST"])
def file_audit():
    form = form_data(("file_path", t("field_path"), "text", "files"))
    audit_entries = []; error = None
    if request.method == "POST":
        file_path = request.form.get("file_path", "").strip()
        if not file_path:
            error = t("err_path_required")
        else:
            try:
                output = run(["sudo", "ausearch", "-f", file_path, "--raw"]).stdout
                if output.strip():
                    for entry in output.split("\n\n"):
                        if entry.strip():
                            lines = entry.strip().splitlines()
                            audit_data = {}
                            for line in lines:
                                if line.startswith("type="):
                                    audit_data["type"] = line.split(" ")[0]
                                elif "SYSCALL" in line:
                                    audit_data["syscall"] = line
                                elif "EXECVE" in line:
                                    audit_data["command"] = line
                                elif "cwd=" in line:
                                    audit_data["cwd"] = line
                            if audit_data:
                                audit_entries.append(audit_data)
                else:
                    error = t("err_audit_empty")
            except (subprocess.CalledProcessError, OSError):
                error = t("err_audit")
    return render_template("file_audit.html", form=form, audit_entries=audit_entries, error=error)


@app.route("/view_acl/", methods=["GET", "POST"])
def view_acl():
    form = form_data(("file_path", t("field_path"), "text", "files"))
    acl_output = None; error = None
    if request.method == "POST":
        file_path = request.form.get("file_path", "").strip()
        if not file_path:
            error = t("err_path_required")
        else:
            try:
                acl_output = run(["sudo", "getfacl", "-p", "--", file_path]).stdout
            except (subprocess.CalledProcessError, OSError):
                error = t("err_getfacl")
    return render_template("view_acl.html", form=form, acl_output=acl_output, error=error)


@app.route("/set_acl/", methods=["GET", "POST"])
def set_acl():
    FIELDS = (("file_path", t("field_path"), "text", "files"), ("acl_entry", t("field_acl_entry"), "text"), ("acl_options", t("field_acl_options"), "text"))
    form = form_data(*FIELDS)
    message = error = None
    if request.method == "POST":
        file_path = request.form.get("file_path", "").strip()
        acl_entry = request.form.get("acl_entry", "").strip()
        acl_options = request.form.get("acl_options", "").strip()
        if not file_path or not acl_entry:
            error = t("err_acl_required")
        elif not re.fullmatch(r"[ug]:[a-z_][a-z0-9_-]{0,31}:[rwx-]{3}", acl_entry):
            error = t("err_acl_format")
        elif acl_options not in {"", "d", "R", "dR", "Rd"}:
            error = t("err_acl_options")
        else:
            try:
                command = ["sudo", "setfacl"]
                if "d" in acl_options:
                    command.append("-d")
                if "R" in acl_options:
                    command.append("-R")
                command += ["-m", acl_entry, "--", file_path]
                run(command)
                audit(file_path, t("audit_acl_added").format(entry=acl_entry))
                message = t("msg_acl_added").format(entry=acl_entry, path=file_path)
                form = form_data(*FIELDS)
            except (subprocess.CalledProcessError, OSError):
                error = t("err_setfacl")
    return render_template("set_acl.html", form=form, message=message, error=error)


@app.route("/remove_acl/", methods=["GET", "POST"])
def remove_acl():
    FIELDS = (("file_path", t("field_path"), "text", "files"), ("acl_entry", t("field_acl_entry_del"), "text"))
    form = form_data(*FIELDS)
    message = error = None
    if request.method == "POST":
        file_path = request.form.get("file_path", "").strip()
        acl_entry = request.form.get("acl_entry", "").strip()
        if not file_path:
            error = t("err_path_required")
        elif acl_entry and not re.fullmatch(r"[ug]:[a-z_][a-z0-9_-]{0,31}", acl_entry):
            error = t("err_acl_del_format")
        else:
            try:
                command = ["sudo", "setfacl", "-b", "--", file_path] if not acl_entry else ["sudo", "setfacl", "-x", acl_entry, "--", file_path]
                run(command)
                audit(file_path, t("audit_acl_deleted").format(entry=acl_entry or "-"))
                message = t("msg_acl_deleted").format(path=file_path)
                form = form_data(*FIELDS)
            except (subprocess.CalledProcessError, OSError):
                error = t("err_acl_del")
    return render_template("remove_acl.html", form=form, message=message, error=error, danger=True)


@app.route("/ufw_status/", methods=["GET"])
def ufw_status():
    ufw_output = None; error = None
    try:
        ufw_output = run(["sudo", "ufw", "status", "numbered"]).stdout
    except (subprocess.CalledProcessError, OSError):
        error = t("err_ufw_status")
    return render_template("ufw_status.html", ufw_output=ufw_output, error=error)


@app.route("/ufw_rule/", methods=["GET", "POST"])
def ufw_rule():
    FIELDS = (("rule", t("field_ufw_rule"), "text"), ("action", t("field_ufw_action"), "text"))
    form = form_data(*FIELDS)
    message = error = None
    if request.method == "POST":
        rule = request.form.get("rule", "").strip()
        action = request.form.get("action", "").strip().lower()
        if not rule or not action:
            error = t("err_required")
        elif action not in {"allow", "deny"}:
            error = t("err_ufw_action")
        elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-./:]{0,39}", rule):
            error = t("err_ufw_rule")
        else:
            try:
                run(["sudo", "ufw", action, rule])
                audit(rule, t("audit_ufw").format(action=action))
                message = t("msg_ufw_added").format(action=action, rule=rule)
                form = form_data(*FIELDS)
            except (subprocess.CalledProcessError, OSError):
                error = t("err_ufw_add")
    return render_template("ufw_rule.html", form=form, message=message, error=error)


@app.route("/ufw_delete/", methods=["GET", "POST"])
def ufw_delete():
    form = form_data(("rule", t("field_ufw_del"), "text"))
    message = error = None
    if request.method == "POST":
        rule = request.form.get("rule", "").strip()
        if not rule:
            error = t("err_rule_required")
        elif not re.fullmatch(r"\d+", rule) and not re.fullmatch(r"(allow|deny) [A-Za-z0-9][A-Za-z0-9\-./:]{0,39}", rule):
            error = t("err_ufw_del_format")
        else:
            try:
                run(["sudo", "ufw", "--force", "delete"] + rule.split())
                audit(rule, t("audit_ufw_del"))
                message = t("msg_ufw_deleted").format(rule=rule)
                form = form_data(("rule", t("field_ufw_del"), "text"))
            except (subprocess.CalledProcessError, OSError):
                error = t("err_ufw_del")
    return render_template("ufw_delete.html", form=form, message=message, error=error, danger=True)


@app.route("/iptables_list/", methods=["GET"])
def iptables_list():
    iptables_output = None; error = None
    try:
        iptables_output = run(["sudo", "iptables", "-L", "-n", "-v", "--line-numbers"]).stdout
    except (subprocess.CalledProcessError, OSError):
        error = t("err_iptables_list")
    return render_template("iptables_list.html", iptables_output=iptables_output, error=error)


@app.route("/iptables_rule/", methods=["GET", "POST"])
def iptables_rule():
    FIELDS = (("operation", t("field_ipt_op"), "text"), ("protocol", t("field_ipt_proto"), "text"), ("port", t("field_ipt_port"), "text"), ("target", t("field_ipt_target"), "text"))
    form = form_data(*FIELDS)
    message = error = None
    if request.method == "POST":
        operation = request.form.get("operation", "").strip().upper()
        protocol = request.form.get("protocol", "").strip().lower()
        port = request.form.get("port", "").strip()
        target = request.form.get("target", "").strip().upper()
        if operation not in {"A", "D"}:
            error = t("err_ipt_op")
        elif protocol and protocol not in {"tcp", "udp", "icmp"}:
            error = t("err_ipt_proto")
        elif port and (not port.isdigit() or not 1 <= int(port) <= 65535):
            error = t("err_ipt_port")
        elif target not in {"ACCEPT", "DROP", "REJECT"}:
            error = t("err_ipt_target")
        else:
            try:
                command = ["sudo", "iptables", f"-{operation}", "INPUT"]
                if protocol:
                    command += ["-p", protocol]
                if port:
                    command += ["--dport", port]
                command += ["-j", target]
                run(command)
                audit(f"{protocol or 'all'}:{port or 'all'}", t("audit_iptables").format(op=operation, target=target))
                message = t("msg_iptables").format(op=operation, proto=protocol, port=port, target=target)
                form = form_data(*FIELDS)
            except (subprocess.CalledProcessError, OSError):
                error = t("err_iptables")
    return render_template("iptables_rule.html", form=form, message=message, error=error)


def password_page(template):
    form=form_data(("username",t("field_username"),"text", "users"),("new_password",t("field_new_password"),"password")); message=error=None
    if request.method=="POST":
        username=request.form.get("username","").strip(); password=request.form.get("new_password","")
        if not valid_linux_name(username):
            error=t("err_bad_username")
        else:
            password_valid, password_error = valid_password(password)
            if not password_valid:
                error = password_error
            else:
                try:
                    run(["sudo","chpasswd"], input=f"{username}:{password}\n")
                    audit(username, t("audit_passwd"))
                    message=t("msg_passwd_updated")
                except (subprocess.CalledProcessError, OSError):
                    error=t("err_passwd")
    return render_template(template, form=form, message=message, error=error)

@app.route("/change_passwd/", methods=["GET","POST"])
def change_passwd(): return password_page("change_passwd.html")
@app.route("/passwd_forget/", methods=["GET","POST"])
def passwd_forget(): return password_page("passwd_forget.html")


@app.route("/update_password_last_changed/", methods=["GET", "POST"])
def update_password_last_changed():
    form = form_data(("new_date", t("field_pwd_date"), "date"))
    message = error = None
    if request.method == "POST":
        new_date = request.form.get("new_date", "").strip()
        if not new_date:
            error = t("err_date_required")
        else:
            try:
                datetime.fromisoformat(new_date)
                env_path = BASE_DIR / ".env"
                if env_path.exists():
                    content = env_path.read_text()
                    if "ADMIN_PASSWORD_LAST_CHANGED=" in content:
                        import re as re_mod
                        content = re_mod.sub(r"ADMIN_PASSWORD_LAST_CHANGED=.*", f"ADMIN_PASSWORD_LAST_CHANGED={new_date}", content)
                    else:
                        content += f"\nADMIN_PASSWORD_LAST_CHANGED={new_date}\n"
                    env_path.write_text(content)
                    app.config["ADMIN_PASSWORD_LAST_CHANGED"] = new_date
                    audit("admin", t("audit_pwd_date"))
                    message = t("msg_pwd_date_updated").format(date=new_date)
                    form = form_data(("new_date", t("field_pwd_date"), "date"))
                else:
                    error = t("err_env_missing")
            except ValueError:
                error = t("err_bad_date")
    return render_template("update_password_last_changed.html", form=form, message=message, error=error)


@app.route("/request_log_access/", methods=["GET", "POST"])
def request_log_access():
    form=form_data(("email",t("field_email"),"email")); error=None
    if request.method=="POST":
        email=request.form.get("email", "").strip()
        if email not in app.config["LOG_EMAILS"]: error=t("err_email_denied")
        else:
            code="".join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(6)); session.update(log_access_email=email,log_access_code=code,log_access_time=datetime.now().isoformat())
            try: send_code(email,code); return redirect(url_for("verify_log_code"))
            except RuntimeError as exc: error=str(exc)
    return render_template("request_log_access.html",form=form,error=error)

@app.route("/verify_log_code/", methods=["GET","POST"])
def verify_log_code():
    form=form_data(("code",t("field_code"),"text")); error=None
    if request.method=="POST":
        timestamp=session.get("log_access_time", "")
        if not timestamp or datetime.now()>datetime.fromisoformat(timestamp)+timedelta(minutes=5): error=t("err_code_expired")
        elif request.form.get("code", "") == session.get("log_access_code"): session["log_access_granted"]=True; return redirect(url_for("view_logs_html"))
        else: error=t("err_code_wrong")
    return render_template("verify_log_code.html",form=form,error=error)

@app.post("/resend_log_code/")
def resend_log_code():
    email=session.get("log_access_email")
    if not email: flash(t("flash_email_missing"), "error"); return redirect(url_for("request_log_access"))
    code="".join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(6)); session.update(log_access_code=code,log_access_time=datetime.now().isoformat())
    try: send_code(email,code); flash(t("flash_code_resent"), "success")
    except RuntimeError as exc: flash(str(exc), "error")
    return redirect(url_for("verify_log_code"))

@app.route("/view_logs_html/")
def view_logs_html():
    if not session.get("log_access_granted"): return redirect(url_for("request_log_access"))
    path = BASE_DIR / "var" / "log" / "audit.jsonl"; logs = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try: logs.append(json.loads(line))
            except json.JSONDecodeError: app.logger.warning("Ligne d'audit invalide ignorée.")
    return render_template("log_wrapper.html", logs=list(reversed(logs)))


@app.route("/api/search_users/")
def api_search_users():
    query = request.args.get("q", "").strip()
    if not query or len(query) < 1:
        return []
    try:
        all_users = [u["username"] for u in passwd_rows()]
        matches = [u for u in all_users if u.startswith(query)][:10]
        return matches
    except (subprocess.CalledProcessError, OSError):
        return []


@app.route("/api/search_groups/")
def api_search_groups():
    query = request.args.get("q", "").strip()
    if not query or len(query) < 1:
        return []
    try:
        output = run(["getent", "group"]).stdout
        all_groups = [line.split(":")[0] for line in output.splitlines() if line.strip()]
        matches = [g for g in all_groups if g.startswith(query)][:10]
        return matches
    except (subprocess.CalledProcessError, OSError):
        return []


@app.route("/api/search_files/")
def api_search_files():
    query = request.args.get("q", "").strip()
    if not query:
        return []
    try:
        parent = os.path.dirname(query)
        partial = os.path.basename(query)
        if not os.path.isdir(parent):
            return []
        entries = []
        for name in os.listdir(parent):
            if partial and not name.startswith(partial):
                continue
            full = os.path.join(parent, name)
            if os.path.isdir(full):
                entries.append(full + "/")
            else:
                entries.append(full)
            if len(entries) >= 10:
                break
        return entries
    except OSError:
        return []


@app.errorhandler(404)
def not_found(_): return render_template("404.html"),404

if __name__ == "__main__": app.run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG", "") == "1")
