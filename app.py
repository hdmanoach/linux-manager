"""Application Flask de gestion des utilisateurs et groupes Linux."""
import os
import random
import smtplib
import string
import subprocess
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from jinja2 import FileSystemLoader
from markupsafe import Markup, escape
import re
import json
from functools import wraps

from utils import logging_utils
from werkzeug.security import check_password_hash

BASE_DIR = Path(__file__).resolve().parent
FIELD_CLASS = "field"

class DjangoTemplateLoader(FileSystemLoader):
    """Compatibilité temporaire pour les tags Django conservés dans les templates."""
    def get_source(self, environment, template):
        source, filename, uptodate = super().get_source(environment, template)
        source = re.sub(r"\{%\s*url\s+'([^']+)'\s*%\}", r"{{ url_for('\1') }}", source)
        source = re.sub(r"\{%\s*csrf_token\s*%\}", "{{ csrf_token_input() }}", source)
        source = re.sub(r"\{%\s*empty\s*%\}", "{% else %}", source)
        source = re.sub(r"\|default:'([^']*)'", r"|default('\1')", source)
        def include(match):
            assignments = re.findall(r"(\w+)=((?:\"[^\"]*\")|(?:'[^']*')|True|False)", match.group(1))
            return "".join("{% set " + name + " = " + value + " %}" for name, value in assignments) + '{% include "partials/form_card.html" %}'
        source = re.sub(r'\{%\s*include\s+"partials/form_card.html"\s+with\s+(.+?)\s*%\}', include, source)
        return source, filename, uptodate


class Field:
    def __init__(self, name, label, value, type_): self.name, self.label, self.value, self.type, self.id_for_label = name, label, value, type_, f"id_{name}"
    def __html__(self):
        return Markup('<input class="field" id="%s" name="%s" type="%s" value="%s" required>' % (escape(self.id_for_label), escape(self.name), escape(self.type), escape(self.value)))
    __str__ = lambda self: str(self.__html__())


class FormData(dict):
    def __iter__(self): return iter(self.values())
    __getattr__ = dict.__getitem__


app = Flask(__name__, template_folder="manager/templates")
app.jinja_loader = DjangoTemplateLoader(str(BASE_DIR / "manager" / "templates"))
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "change-me-in-production")
app.config["LOG_EMAILS"] = set(filter(None, os.environ.get("ALLOWED_LOG_EMAILS", "").split(",")))
app.config["ADMIN_USERNAME"] = os.environ.get("ADMIN_USERNAME", "")
app.config["ADMIN_PASSWORD_HASH"] = os.environ.get("ADMIN_PASSWORD_HASH", "")


def current_admin():
    return session.get("admin_username")


@app.context_processor
def inject_security_context():
    def csrf_token_input():
        token = session.get("csrf_token")
        if not token:
            token = os.urandom(32).hex(); session["csrf_token"] = token
        return Markup(f'<input type="hidden" name="csrf_token" value="{token}">')
    return {"current_admin": current_admin(), "csrf_token_input": csrf_token_input}


@app.before_request
def protect_application():
    public_endpoints = {"login", "static", "not_found"}
    if request.method == "POST":
        if not session.get("csrf_token") or request.form.get("csrf_token") != session.get("csrf_token"):
            abort(400, "Jeton CSRF invalide.")
    if request.endpoint not in public_endpoints and not current_admin():
        return redirect(url_for("login", next=request.path))


def form_data(*fields):
    """Construit des champs simples, compatibles avec les templates existants."""
    values = request.form if request.method == "POST" else {}
    return FormData({name: Field(name, label, values.get(name, ""), type_) for name, label, type_ in fields})


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, text=True, **kwargs)


def send_code(email, code):
    host, port = os.environ.get("SMTP_HOST"), os.environ.get("SMTP_PORT", "587")
    username, password = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    if not all((host, username, password)):
        raise RuntimeError("Configurez SMTP_HOST, SMTP_USER et SMTP_PASSWORD pour envoyer les codes.")
    message = EmailMessage()
    message["Subject"] = "Code d'accès aux journaux"
    message["From"] = username
    message["To"] = email
    message.set_content(f"Voici votre code d'accès : {code}")
    with smtplib.SMTP(host, int(port)) as smtp:
        smtp.starttls(); smtp.login(username, password); smtp.send_message(message)


def valid_linux_name(value):
    return bool(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}\$?", value))


def audit(target, event, success=True):
    logging_utils.log_user_event(target, event, actor=current_admin() or "unknown", success=success)


@app.route("/login/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not app.config["ADMIN_USERNAME"] or not app.config["ADMIN_PASSWORD_HASH"]:
            error = "Les identifiants administrateur ne sont pas configurés sur le serveur."
        elif username == app.config["ADMIN_USERNAME"] and check_password_hash(app.config["ADMIN_PASSWORD_HASH"], password):
            session.clear(); session["admin_username"] = username
            destination = request.args.get("next") or url_for("menu")
            return redirect(destination)
        else:
            error = "Identifiants incorrects."
    return render_template("login.html", error=error)


@app.post("/logout/")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@app.route("/menu/")
def menu():
    return render_template("menu.html")


def action_page(template, fields, command_builder, success, danger=False):
    form = form_data(*fields); message = error = None
    if request.method == "POST":
        values = {name: request.form.get(name, "").strip() for name, *_ in fields}
        names = [value for key, value in values.items() if key in {"username", "group_name"}]
        if not all(values.values()):
            error = "Tous les champs sont obligatoires."
        elif not all(valid_linux_name(value) for value in names):
            error = "Le nom doit contenir uniquement des minuscules, chiffres, tirets ou soulignés."
        else:
            try:
                command, input_text = command_builder(values)
                run(command, input=input_text) if input_text is not None else run(command)
                audit(values.get("username") or values.get("group_name"), template.removesuffix(".html"))
                message = success(values)
                form = form_data(*fields)
            except (subprocess.CalledProcessError, OSError) as exc:
                app.logger.error("Commande système échouée: %s", exc)
                error = "L'opération a échoué. Vérifiez les informations puis réessayez."
    return render_template(template, form=form, message=message, error=error, danger=danger)


@app.route("/create_user/", methods=["GET", "POST"])
def create_user():
    fields = (("username", "Nom d'utilisateur", "text"), ("password", "Mot de passe", "password"))
    form = form_data(*fields); message = error = None
    if request.method == "POST":
        username, password = request.form.get("username", "").strip(), request.form.get("password", "")
        if not username or not password:
            error = "Tous les champs sont obligatoires."
        elif not valid_linux_name(username):
            error = "Nom d’utilisateur Linux invalide."
        else:
            try:
                run(["sudo", "adduser", "--disabled-password", "--gecos", "", username])
                run(["sudo", "chpasswd"], input=f"{username}:{password}\n")
                audit(username, "Création utilisateur")
                message = f"Utilisateur « {username} » créé avec succès."; form = form_data(*fields)
            except (subprocess.CalledProcessError, OSError) as exc:
                app.logger.error("Création utilisateur échouée: %s", exc); error = "Impossible de créer l’utilisateur."
    return render_template("create_user.html", form=form, message=message, error=error)


@app.route("/create_group/", methods=["GET", "POST"])
def create_group():
    return action_page("create_group.html", (("group_name", "Nom du groupe", "text"),), lambda v: (["sudo", "addgroup", v["group_name"]], None), lambda v: f"Groupe « {v['group_name']} » créé avec succès.")


@app.route("/add_user_to_group/", methods=["GET", "POST"])
def add_user_to_group():
    return action_page("add_user_to_group.html", (("username", "Nom d'utilisateur", "text"), ("group_name", "Nom du groupe", "text")), lambda v: (["sudo", "usermod", "-aG", v["group_name"], v["username"]], None), lambda v: f"Utilisateur ajouté au groupe « {v['group_name']} ».")


@app.route("/add_user_to_group_sudo/", methods=["GET", "POST"])
def add_user_to_group_sudo():
    return action_page("add_user_to_group_sudo.html", (("username", "Nom d'utilisateur", "text"),), lambda v: (["sudo", "usermod", "-aG", "sudo", v["username"]], None), lambda v: f"Accès sudo accordé à « {v['username']} ».")


@app.route("/remove_user_from_group/", methods=["GET", "POST"])
def remove_user_from_group():
    return action_page("remove_user_from_group.html", (("username", "Nom d'utilisateur", "text"), ("group_name", "Nom du groupe", "text")), lambda v: (["sudo", "gpasswd", "-d", v["username"], v["group_name"]], None), lambda v: "Utilisateur retiré du groupe.")


@app.route("/delete_group/", methods=["GET", "POST"])
def delete_group():
    return action_page("delete_group.html", (("group_name", "Nom du groupe", "text"),), lambda v: (["sudo", "groupdel", v["group_name"]], None), lambda v: "Groupe supprimé.", True)


@app.route("/delete_user/", methods=["GET", "POST"])
def delete_user():
    return action_page("delete_user.html", (("username", "Nom d'utilisateur", "text"),), lambda v: (["sudo", "userdel", v["username"]], None), lambda v: "Utilisateur supprimé.", True)


@app.route("/show_user_groups/", methods=["GET", "POST"])
def show_user_groups():
    form = form_data(("username", "Nom d'utilisateur", "text")); username = None; groups = []; error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        if not valid_linux_name(username): error = "Nom d’utilisateur Linux invalide."
        elif username:
            try: groups = run(["groups", username]).stdout.partition(":")[2].split()
            except (subprocess.CalledProcessError, OSError): error = "Impossible de récupérer les groupes de cet utilisateur."
    return render_template("show_user_groups.html", form=form, username=username, user_groups=groups, error=error)


@app.route("/show_group_users/", methods=["GET", "POST"])
def show_group_users():
    form = form_data(("group_name", "Nom du groupe", "text")); group_name = None; users = []; error = None
    if request.method == "POST":
        group_name = request.form.get("group_name", "").strip()
        if not valid_linux_name(group_name): error = "Nom de groupe Linux invalide."
        elif group_name:
            try: users = [u for u in run(["getent", "group", group_name]).stdout.strip().split(":")[3].split(",") if u]
            except (subprocess.CalledProcessError, OSError, IndexError): error = "Impossible de récupérer les membres de ce groupe."
    return render_template("show_group_users.html", form=form, group_name=group_name, group_users=users, error=error)


def passwd_rows():
    return [{"username": p[0], "uid": p[2], "gid": p[3], "home_directory": p[5], "shell": p[6]} for p in (line.split(":") for line in run(["getent", "passwd"]).stdout.splitlines()) if len(p) >= 7]

@app.route("/list_users/", methods=["GET", "POST"])
def list_users():
    query = request.form.get("username", "").strip(); error = None
    try: users = [u for u in passwd_rows() if not query or u["username"].startswith(query)]
    except (subprocess.CalledProcessError, OSError): users=[]; error="Impossible de récupérer les utilisateurs."
    return render_template("list_users.html", form=form_data(("username", "Nom d'utilisateur", "text")), user_list=users, error=error)


@app.route("/list_groups/", methods=["GET", "POST"])
def list_groups():
    query = request.form.get("group_name", "").strip(); error = None
    try:
        groups=[{"group_name":p[0],"gid":p[2],"member":p[3]} for p in (line.split(":") for line in run(["getent","group"]).stdout.splitlines()) if len(p)>=4 and (not query or p[0]==query)]
    except (subprocess.CalledProcessError, OSError): groups=[]; error="Impossible de récupérer les groupes."
    return render_template("list_groups.html", form=form_data(("group_name", "Nom du groupe", "text")), group_list=groups, error=error)


@app.route("/logged_in_users/", methods=["GET", "POST"])
def logged_in_users():
    query=request.form.get("username", "").strip(); users=[]; error=None
    try:
        for p in (line.split() for line in run(["who", "-u"]).stdout.splitlines()):
            if len(p)>=5 and (not query or query in p[0]): users.append({"username":p[0],"terminal":p[1],"login_time":" ".join(p[2:4]),"host":p[-2],"pid":p[-1]})
    except (subprocess.CalledProcessError, OSError): error="Impossible de récupérer les sessions actives."
    return render_template("logged_in_users.html", form=form_data(("username", "Nom d'utilisateur", "text")), users=users, error=error)


def password_page(template):
    form=form_data(("username","Nom d'utilisateur","text"),("new_password","Nouveau mot de passe","password")); message=error=None
    if request.method=="POST":
        username=request.form.get("username","").strip(); password=request.form.get("new_password","")
        if not valid_linux_name(username):
            error="Nom d’utilisateur Linux invalide."
        else:
            try:
                run(["sudo","chpasswd"], input=f"{username}:{password}\n")
                audit(username, "Changement de mot de passe")
                message="Mot de passe mis à jour avec succès."
            except (subprocess.CalledProcessError, OSError):
                error="Impossible de modifier le mot de passe."
    return render_template(template, form=form, message=message, error=error)

@app.route("/change_passwd/", methods=["GET","POST"])
def change_passwd(): return password_page("change_passwd.html")
@app.route("/passwd_forget/", methods=["GET","POST"])
def passwd_forget(): return password_page("passwd_forget.html")


@app.route("/request_log_access/", methods=["GET", "POST"])
def request_log_access():
    form=form_data(("email","Adresse email autorisée","email")); error=None
    if request.method=="POST":
        email=request.form.get("email", "").strip()
        if email not in app.config["LOG_EMAILS"]: error="Cette adresse n’est pas autorisée à accéder aux journaux."
        else:
            code="".join(random.choices(string.ascii_uppercase+string.digits,k=6)); session.update(log_access_email=email,log_access_code=code,log_access_time=datetime.now().isoformat())
            try: send_code(email,code); return redirect(url_for("verify_log_code"))
            except RuntimeError as exc: error=str(exc)
    return render_template("request_log_access.html",form=form,error=error)

@app.route("/verify_log_code/", methods=["GET","POST"])
def verify_log_code():
    form=form_data(("code","Code de vérification","text")); error=None
    if request.method=="POST":
        timestamp=session.get("log_access_time", "")
        if not timestamp or datetime.now()>datetime.fromisoformat(timestamp)+timedelta(minutes=5): error="Code expiré."
        elif request.form.get("code", "") == session.get("log_access_code"): session["log_access_granted"]=True; return redirect(url_for("view_logs_html"))
        else: error="Code incorrect."
    return render_template("verify_log_code.html",form=form,error=error)

@app.post("/resend_log_code/")
def resend_log_code():
    email=session.get("log_access_email")
    if not email: flash("Adresse e-mail indisponible.", "error"); return redirect(url_for("request_log_access"))
    code="".join(random.choices(string.ascii_uppercase+string.digits,k=6)); session.update(log_access_code=code,log_access_time=datetime.now().isoformat())
    try: send_code(email,code); flash("Un nouveau code a été envoyé.", "success")
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

@app.route("/test-404/")
def test_404(): abort(404)
@app.errorhandler(404)
def not_found(_): return render_template("404.html"),404

if __name__ == "__main__": app.run(host="127.0.0.1", port=5000, debug=True)
