import flet as ft
import os
import urllib.request
import subprocess
import tempfile
import sqlite3
import json
import threading
import pandas as pd
from fpdf import FPDF
from datetime import datetime, timedelta
from supabase import create_client, Client

# --- SUPABASE CONFIGURATION ---
SUPABASE_URL = "https://lbaquqyzbippicbvmcxr.supabase.co"
SUPABASE_KEY = "sb_publishable_qIs62pb-XO17gSwhXubVqg_2ffU7MOl"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    supabase = None
    print(f"Supabase init error: {e}")

MACHINES = [
    "Presse 1", "Presse 2", "Presse 3", "Presse 4", "Presse 5", "Presse 6",
    "Presse 7", "Presse 8", "Presse 9", "Presse 10", "Presse 11",
    "Compresseur d'air", "Aspirateur CNC", "Malaxeur matière", "Machine de colle",
    "Four machine de colle", "CNC profileuse", "CNC profileuse lourd", "Machine de peinture",
    "Four CNC", "Scotcheuse", "Emballeuse", "Cintreuse", "Groupe électrogène",
    "Four produit final", "Pèse matière 1", "Pèse matière 2", "Pèse matière 3",
    "Aspirateur presse", "Aspirateur manuel 1", "Aspirateur manuel 2", "Moule"
]


def setup_db(page):
    candidates = []

    try:
        sp = getattr(page, "storage_path", None)
        if sp:
            candidates.append(sp)
    except Exception:
        pass

    try:
        candidates.append(tempfile.gettempdir())
    except Exception:
        pass

    candidates.append(".")

    last_error = None

    for base_dir in candidates:
        try:
            os.makedirs(base_dir, exist_ok=True)
            db_path = os.path.join(base_dir, "briks_local.db")
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS local_inters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    remote_id INTEGER,
                    demandeur TEXT,
                    intervenant TEXT,
                    date TEXT,
                    systeme TEXT,
                    sous_ens TEXT,
                    error_desc TEXT,
                    solution_desc TEXT,
                    pieces TEXT,
                    type_m TEXT,
                    photo_err TEXT,
                    photo_sol TEXT,
                    error_source TEXT,
                    error_other TEXT,
                    user TEXT,
                    mold_ref TEXT,
                    spare_price TEXT,
                    synced INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS local_part_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    remote_id INTEGER,
                    machine TEXT,
                    piece_nom TEXT,
                    qte TEXT,
                    urgence TEXT,
                    photo_path TEXT,
                    dt TEXT,
                    user TEXT,
                    synced INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS local_routines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    remote_id INTEGER,
                    machine TEXT,
                    freq TEXT,
                    graissage TEXT,
                    huilage TEXT,
                    serrage TEXT,
                    securite TEXT,
                    duree TEXT,
                    remarks TEXT,
                    dt TEXT,
                    user TEXT,
                    synced INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS local_mold_parameters (
                    mold_name TEXT PRIMARY KEY,
                    modele TEXT,
                    matiere TEXT,
                    mpa TEXT,
                    cycle TEXT,
                    temps TEXT,
                    updated_by TEXT,
                    updated_at TEXT,
                    synced INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS local_press_current_mold (
                    presse TEXT PRIMARY KEY,
                    mold_name TEXT,
                    modele TEXT,
                    matiere TEXT,
                    mpa TEXT,
                    cycle TEXT,
                    temps TEXT,
                    updated_by TEXT,
                    updated_at TEXT,
                    synced INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS local_molds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    remote_id INTEGER,
                    p_no TEXT,
                    old_m TEXT,
                    new_m TEXT,
                    modele TEXT,
                    matiere TEXT,
                    mpa TEXT,
                    cycle TEXT,
                    temps TEXT,
                    dt TEXT,
                    user TEXT,
                    synced INTEGER DEFAULT 0
                )
            """)
            conn.commit()
            print(f"LOCAL DB READY: {db_path}")
            return conn
        except Exception as ex:
            last_error = ex

    raise last_error if last_error else Exception("Impossible d'ouvrir la base locale")

def main(page: ft.Page):
    try:
        page.title = "BRIKS - Service maintenance"
        page.theme_mode = "dark"
        page.scroll = ft.ScrollMode.AUTO
        page.bgcolor = "#0f0f0f"
        page.padding = 10

        page.logged_in = False
        page.view = "LOGIN"

        page.photo_err_path = ""
        page.photo_sol_path = ""
        page.photo_part_path = ""
        page.current_upload_target = ""
        page.last_action_status = ""
        page.current_report = None

        def show_ui_error(e):
            print(f"FLET UI ERROR: {e.data}")
            try:
                page.snack_bar = ft.SnackBar(
                    ft.Text(f"UI ERROR: {str(e.data)}", color="white"),
                    open=True
                )
                page.update()
            except Exception as ex:
                print("FAILED TO SHOW UI ERROR:", ex)

        page.on_error = show_ui_error

        def request_android_permissions():
            try:
                if hasattr(page, "permission_handler"):
                    for perm in [
                        getattr(ft.PermissionType, "CAMERA", None),
                        getattr(ft.PermissionType, "STORAGE", None),
                        getattr(ft.PermissionType, "MANAGE_EXTERNAL_STORAGE", None),
                    ]:
                        if perm is not None:
                            try:
                                page.permission_handler.request_permission(perm)
                            except Exception as ex:
                                print(f"Permission request failed: {ex}")
                elif hasattr(page, "request_permission"):
                    for perm in [
                        getattr(ft.PermissionType, "CAMERA", None),
                        getattr(ft.PermissionType, "STORAGE", None),
                    ]:
                        if perm is not None:
                            try:
                                page.request_permission(perm)
                            except Exception as ex:
                                print(f"Permission request failed: {ex}")
            except Exception as ex:
                print(f"PERMISSION ERROR: {ex}")

        request_android_permissions()

        local_conn = setup_db(page)

        def local_execute(sql, params=()):
            cur = local_conn.cursor()
            cur.execute(sql, params)
            local_conn.commit()
            return cur

        def local_query_all(sql, params=()):
            cur = local_conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]

        def local_query_one(sql, params=()):
            cur = local_conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None

        def online_available():
            try:
                urllib.request.urlopen("https://www.google.com", timeout=2)
                return True
            except Exception:
                return False

        def sync_to_supabase():
            if not online_available() or supabase is None:
                return
            try:
                # mold parameters
                for row in local_query_all("SELECT * FROM local_mold_parameters WHERE synced = 0"):
                    payload = {
                        "mold_name": row["mold_name"],
                        "modele": row["modele"],
                        "matiere": row["matiere"],
                        "mpa": float(row["mpa"]) if str(row["mpa"]).strip() else None,
                        "cycle": int(float(row["cycle"])) if str(row["cycle"]).strip() else None,
                        "temps": row["temps"],
                        "updated_by": row["updated_by"],
                        "updated_at": row["updated_at"],
                    }
                    existing = supabase.table("mold_parameters").select("id").eq("mold_name", row["mold_name"]).limit(1).execute()
                    if existing.data:
                        supabase.table("mold_parameters").update(payload).eq("id", existing.data[0]["id"]).execute()
                    else:
                        supabase.table("mold_parameters").insert(payload).execute()
                    local_execute("UPDATE local_mold_parameters SET synced = 1 WHERE mold_name = ?", (row["mold_name"],))

                # current press molds
                for row in local_query_all("SELECT * FROM local_press_current_mold WHERE synced = 0"):
                    payload = {
                        "presse": row["presse"],
                        "mold_name": row["mold_name"],
                        "modele": row["modele"],
                        "matiere": row["matiere"],
                        "mpa": float(row["mpa"]) if str(row["mpa"]).strip() else None,
                        "cycle": int(float(row["cycle"])) if str(row["cycle"]).strip() else None,
                        "temps": row["temps"],
                        "updated_by": row["updated_by"],
                        "updated_at": row["updated_at"],
                    }
                    existing = supabase.table("press_current_mold").select("id").eq("presse", row["presse"]).limit(1).execute()
                    if existing.data:
                        supabase.table("press_current_mold").update(payload).eq("id", existing.data[0]["id"]).execute()
                    else:
                        supabase.table("press_current_mold").insert(payload).execute()
                    local_execute("UPDATE local_press_current_mold SET synced = 1 WHERE presse = ?", (row["presse"],))

                # mold history
                for row in local_query_all("SELECT * FROM local_molds WHERE synced = 0 ORDER BY id ASC"):
                    payload = {
                        "p_no": row["p_no"],
                        "old_m": row["old_m"],
                        "new_m": row["new_m"],
                        "modele": row["modele"],
                        "matiere": row["matiere"],
                        "mpa": float(row["mpa"]) if str(row["mpa"]).strip() else None,
                        "cycle": int(float(row["cycle"])) if str(row["cycle"]).strip() else None,
                        "temps": row["temps"],
                        "dt": row["dt"],
                        "user": row["user"],
                    }
                    res = supabase.table("molds").insert(payload).execute()
                    rid = res.data[0]["id"] if getattr(res, "data", None) else None
                    local_execute("UPDATE local_molds SET synced = 1, remote_id = ? WHERE id = ?", (rid, row["id"]))

                # interventions
                for row in local_query_all("SELECT * FROM local_inters WHERE synced = 0 ORDER BY id ASC"):
                    payload = {k: row[k] for k in ["demandeur","intervenant","date","systeme","sous_ens","error_desc","solution_desc","pieces","type_m","error_source","error_other","user","mold_ref","spare_price"]}
                    payload["photo_err"] = upload_to_supabase(row["photo_err"], "errors") if row.get("photo_err") else ""
                    payload["photo_sol"] = upload_to_supabase(row["photo_sol"], "solutions") if row.get("photo_sol") else ""
                    res = supabase.table("inters").insert(payload).execute()
                    rid = res.data[0]["id"] if getattr(res, "data", None) else None
                    local_execute("UPDATE local_inters SET synced = 1, remote_id = ? WHERE id = ?", (rid, row["id"]))

                # routines
                for row in local_query_all("SELECT * FROM local_routines WHERE synced = 0 ORDER BY id ASC"):
                    payload = {k: row[k] for k in ["machine","freq","graissage","huilage","serrage","securite","duree","remarks","dt","user"]}
                    res = supabase.table("routines").insert(payload).execute()
                    rid = res.data[0]["id"] if getattr(res, "data", None) else None
                    local_execute("UPDATE local_routines SET synced = 1, remote_id = ? WHERE id = ?", (rid, row["id"]))

                # part requests
                for row in local_query_all("SELECT * FROM local_part_requests WHERE synced = 0 ORDER BY id ASC"):
                    payload = {k: row[k] for k in ["machine","piece_nom","qte","urgence","dt","user"]}
                    payload["photo_path"] = upload_to_supabase(row["photo_path"], "parts") if row.get("photo_path") else ""
                    res = supabase.table("part_requests").insert(payload).execute()
                    rid = res.data[0]["id"] if getattr(res, "data", None) else None
                    local_execute("UPDATE local_part_requests SET synced = 1, remote_id = ? WHERE id = ?", (rid, row["id"]))
            except Exception as ex:
                print("SYNC ERROR:", ex)

        def trigger_sync():
            try:
                threading.Thread(target=sync_to_supabase, daemon=True).start()
            except Exception as ex:
                print("TRIGGER SYNC ERROR:", ex)

        def cache_remote_basics():
            if supabase is None or not online_available():
                return
            try:
                molds = supabase.table("molds").select("*").order("id", desc=True).limit(200).execute().data
                for r in reversed(molds or []):
                    exists = local_query_one("SELECT id FROM local_molds WHERE remote_id = ?", (r["id"],))
                    if not exists:
                        local_execute(
                            "INSERT INTO local_molds (remote_id, p_no, old_m, new_m, modele, matiere, mpa, cycle, temps, dt, user, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                            (r.get("id"), r.get("p_no"), r.get("old_m"), r.get("new_m"), r.get("modele"), r.get("matiere"), str(r.get("mpa","") or ""), str(r.get("cycle","") or ""), str(r.get("temps","") or ""), r.get("dt"), r.get("user"),)
                        )
                pcm = supabase.table("press_current_mold").select("*").execute().data
                for r in pcm or []:
                    local_execute(
                        "INSERT OR REPLACE INTO local_press_current_mold (presse, mold_name, modele, matiere, mpa, cycle, temps, updated_by, updated_at, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                        (r.get("presse"), r.get("mold_name"), r.get("modele"), r.get("matiere"), str(r.get("mpa","") or ""), str(r.get("cycle","") or ""), str(r.get("temps","") or ""), r.get("updated_by",""), r.get("updated_at",""))
                    )
            except Exception as ex:
                print("CACHE REMOTE ERROR:", ex)

        cache_remote_basics()
        trigger_sync()


        def upload_to_supabase(local_path, folder):
            if not local_path or not os.path.exists(local_path):
                return ""
            try:
                user_clean = page.u_id if hasattr(page, "u_id") else "anon"
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                ext = os.path.splitext(local_path)[1]
                if not ext:
                    ext = ".jpg"

                file_name = f"{folder}/{user_clean}_{ts}{ext}"

                with open(local_path, "rb") as f:
                    supabase.storage.from_("maintenance").upload(file_name, f)

                return supabase.storage.from_("maintenance").get_public_url(file_name)
            except Exception as ex:
                print(f"Upload error: {ex}")
                return ""

        def resolve_photo_source(value, folder):
            raw = (value or "").strip()
            if not raw:
                return ""
            if raw.startswith("http://") or raw.startswith("https://"):
                return raw
            if os.path.exists(raw):
                return upload_to_supabase(raw, folder)
            return ""


        
        async def pick_from_gallery(target):
            try:
                page.current_upload_target = target
                page.last_action_status = f"Ouverture galerie: {target}"
                page.update()

                files = await ft.FilePicker().pick_files(allow_multiple=False)

                if not files:
                    page.last_action_status = "Aucune image sélectionnée."
                    page.snack_bar = ft.SnackBar(ft.Text(page.last_action_status))
                    page.snack_bar.open = True
                    page.update()
                    return

                first = files[0]
                file_path = getattr(first, "path", None) or getattr(first, "name", None)
                if not file_path:
                    page.last_action_status = "Impossible de récupérer l'image."
                    page.snack_bar = ft.SnackBar(ft.Text(page.last_action_status))
                    page.snack_bar.open = True
                    page.update()
                    return

                if page.current_upload_target == "ERR":
                    page.photo_err_path = file_path
                    msg = "✅ Photo problème attachée depuis la galerie"
                elif page.current_upload_target == "SOL":
                    page.photo_sol_path = file_path
                    msg = "✅ Photo solution attachée depuis la galerie"
                elif page.current_upload_target == "PART":
                    page.photo_part_path = file_path
                    msg = "✅ Photo pièce attachée depuis la galerie"
                else:
                    msg = "✅ Image attachée"

                page.last_action_status = msg
                page.snack_bar = ft.SnackBar(ft.Text(msg))
                page.snack_bar.open = True
                page.update()

            except Exception as ex:
                page.last_action_status = f"Galerie non disponible: {ex}"
                page.snack_bar = ft.SnackBar(ft.Text(page.last_action_status))
                page.snack_bar.open = True
                page.update()

        def on_media_result(e):
            try:
                files = getattr(e, "files", None) or []
                if not files:
                    page.snack_bar = ft.SnackBar(ft.Text("Aucune photo sélectionnée."))
                    page.snack_bar.open = True
                    page.update()
                    return

                first = files[0]
                file_path = getattr(first, "path", None) or getattr(first, "name", None)
                if not file_path:
                    page.snack_bar = ft.SnackBar(ft.Text("Impossible de récupérer la photo."))
                    page.snack_bar.open = True
                    page.update()
                    return

                if page.current_upload_target == "ERR":
                    page.photo_err_path = file_path
                    msg = "✅ Photo problème attachée"
                elif page.current_upload_target == "SOL":
                    page.photo_sol_path = file_path
                    msg = "✅ Photo solution attachée"
                elif page.current_upload_target == "PART":
                    page.photo_part_path = file_path
                    msg = "✅ Photo pièce attachée"
                else:
                    msg = "✅ Photo attachée"

                page.last_action_status = msg
                page.snack_bar = ft.SnackBar(ft.Text(msg))
                page.snack_bar.open = True
                page.update()
            except Exception as ex:
                print(f"MEDIA RESULT ERROR: {ex}")
                page.last_action_status = f"Erreur photo: {ex}"
                page.snack_bar = ft.SnackBar(ft.Text(f"Erreur photo: {ex}"))
                page.snack_bar.open = True
                page.update()

        page.on_media = on_media_result

        
        def capture_photo(target):
            page.run_task(pick_from_gallery, target)

        def get_download_dir():
            preferred = "/storage/emulated/0/Download"
            try:
                os.makedirs(preferred, exist_ok=True)
                return preferred
            except Exception:
                return tempfile.gettempdir()

        def get_export_path(filename):
            return os.path.join(get_download_dir(), filename)

        def try_open_file(filepath):
            try:
                if hasattr(page, "launch_url"):
                    page.launch_url(f"file://{filepath}")
                    return
            except Exception:
                pass
            try:
                subprocess.Popen(["am", "start", "-a", "android.intent.action.VIEW", "-d", f"file://{filepath}"])
            except Exception as ex:
                print(f"OPEN FILE ERROR: {ex}")

        footer_tag = ft.Text("Made by Okba Bennaim", size=10, italic=True, color="grey500")

        header_brand = ft.Column(
            [
                ft.Text("BRIKS", size=32, weight="bold", color="red"),
                ft.Text("SERVICE MAINTENANCE", size=12, color="red", italic=True),
            ],
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        content_area = ft.Container(expand=True)

        def ch_v(v):
            page.view = v
            refresh()

        def open_report_viewer(row):
            page.current_report = row
            ch_v("REPORT_VIEW")

        def safe_screen(*controls):
            return ft.Container(
                content=ft.Column(
                    list(controls),
                    scroll=ft.ScrollMode.AUTO,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    expand=True,
                ),
                padding=20,
                expand=True,
            )

        def refresh():
            try:
                print(f"REFRESH VIEW => {page.view}")
                screen = None

                if not page.logged_in and page.view == "LOGIN":
                    u_in = ft.TextField(label="Utilisateur", width=320)
                    p_in = ft.TextField(label="Mot de passe", password=True, width=320)
                    login_error = ft.Text("Identifiants incorrects", color="red", visible=False)

                    login_btn = ft.ElevatedButton("ENTRER", width=320, bgcolor="red900")
                    loading_ring = ft.ProgressRing(visible=False, color="red")

                    def login(e):
                        login_btn.disabled = True
                        loading_ring.visible = True
                        login_error.visible = False
                        page.update()

                        try:
                            if supabase is None:
                                raise Exception("Supabase non initialisé")

                            res = (
                                supabase.table("users")
                                .select("*")
                                .eq("username", (u_in.value or "").lower())
                                .eq("password", p_in.value or "")
                                .execute()
                            )

                            print("LOGIN RESPONSE:", res.data)

                            if res.data:
                                page.logged_in = True
                                page.u_id = (u_in.value or "").lower()
                                page.display_name = res.data[0].get("full_name", u_in.value or "Utilisateur")
                                page.view = "HOME"
                                refresh()
                                return
                            else:
                                login_error.value = "Identifiants incorrects ou utilisateur introuvable."
                                login_error.visible = True

                        except Exception as ex:
                            print("LOGIN ERROR:", ex)
                            login_error.value = f"Erreur de connexion: {str(ex)}"
                            login_error.visible = True

                        login_btn.disabled = False
                        loading_ring.visible = False
                        page.update()

                    login_btn.on_click = login

                    screen = safe_screen(
                        ft.Container(height=50),
                        header_brand,
                        u_in,
                        p_in,
                        login_error,
                        loading_ring,
                        login_btn,
                        ft.TextButton("Créer un compte (Sign Up)", on_click=lambda _: ch_v("SIGNUP")),
                        footer_tag,
                    )

                elif page.view == "SIGNUP":
                    new_user = ft.TextField(label="Nom d'utilisateur (Login)", width=320)
                    new_full = ft.TextField(label="Nom complet (Affichage)", width=320)
                    new_pass = ft.TextField(label="Mot de passe", password=True, width=320)

                    def register(e):
                        if not new_user.value or not new_pass.value:
                            page.snack_bar = ft.SnackBar(ft.Text("Veuillez remplir tous les champs."))
                            page.snack_bar.open = True
                            page.update()
                            return

                        try:
                            supabase.table("users").insert(
                                {
                                    "username": new_user.value.lower(),
                                    "full_name": new_full.value,
                                    "password": new_pass.value,
                                }
                            ).execute()

                            page.snack_bar = ft.SnackBar(ft.Text("Compte créé avec succès ! Connectez-vous."))
                            page.snack_bar.open = True
                            ch_v("LOGIN")
                        except Exception as ex:
                            page.snack_bar = ft.SnackBar(ft.Text(f"Erreur : {ex}"))
                            page.snack_bar.open = True
                            page.update()

                    screen = safe_screen(
                        ft.Container(height=50),
                        header_brand,
                        ft.Text("CRÉER UN COMPTE", weight="bold", size=20),
                        new_user,
                        new_full,
                        new_pass,
                        ft.ElevatedButton("S'INSCRIRE", on_click=register, width=320, bgcolor="blue900"),
                        ft.TextButton("Retour à la connexion", on_click=lambda _: ch_v("LOGIN")),
                        footer_tag,
                    )

                elif page.view == "HOME":
                    screen = ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Column(
                                            [
                                                ft.Text("VERSION: OKBA-2026-REPAIRED", color="yellow", size=12),
                                                ft.Text("BRIKS", size=28, weight="bold", color="red"),
                                                ft.Text("SERVICE MAINTENANCE", size=10, color="red", italic=True),
                                            ],
                                            spacing=0,
                                        ),
                                        ft.IconButton(ft.Icons.SETTINGS, on_click=lambda _: ch_v("USER")),
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                ),
                                ft.Text(
                                    f"Opérateur: {getattr(page, 'display_name', 'Utilisateur')}",
                                    italic=True,
                                    color="grey",
                                ),
                                ft.Divider(color="red"),
                                ft.Column(
                                    [
                                        ft.ElevatedButton(
                                            "INTERVENTION TECHNIQUE",
                                            icon=ft.Icons.BUILD_CIRCLE,
                                            on_click=lambda _: ch_v("INTER"),
                                            width=320,
                                            height=55,
                                            bgcolor="blue900",
                                        ),
                                        ft.ElevatedButton(
                                            "DEMANDE PIÈCE DE RECHANGE",
                                            icon=ft.Icons.SHOPPING_CART,
                                            on_click=lambda _: ch_v("PART_REQ"),
                                            width=320,
                                            height=55,
                                            bgcolor="orange900",
                                        ),
                                        ft.ElevatedButton(
                                            "GESTION STOCK (INVENTORY)",
                                            icon=ft.Icons.INVENTORY,
                                            on_click=lambda _: ch_v("STOCK_MGR"),
                                            width=320,
                                            height=55,
                                            bgcolor="teal900",
                                        ),
                                        ft.ElevatedButton(
                                            "HISTORIQUE DES RAPPORTS",
                                            icon=ft.Icons.HISTORY,
                                            on_click=lambda _: ch_v("HISTORY"),
                                            width=320,
                                            height=55,
                                        ),
                                        ft.ElevatedButton(
                                            "TRACKING MOULES",
                                            icon=ft.Icons.RECYCLING,
                                            on_click=lambda _: ch_v("MOLD"),
                                            width=320,
                                            height=55,
                                        ),
                                        ft.ElevatedButton(
                                            "CHECKS QUOTIDIENS / HEBDO",
                                            icon=ft.Icons.CHECKLIST,
                                            on_click=lambda _: ch_v("ROUTINE"),
                                            width=320,
                                            height=55,
                                            bgcolor="green900",
                                        ),
                                    ],
                                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                    spacing=15,
                                ),
                                ft.Divider(),
                                footer_tag,
                            ],
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            scroll=ft.ScrollMode.AUTO,
                            expand=True,
                        ),
                        padding=20,
                        expand=True,
                    )

                elif page.view == "USER":
                    new_name = ft.TextField(label="Nouveau Nom d'affichage", value=getattr(page, "display_name", ""))
                    new_pw = ft.TextField(label="Nouveau Mot de passe", password=True)

                    def update_profile(e):
                        try:
                            payload = {"full_name": new_name.value}
                            if new_pw.value:
                                payload["password"] = new_pw.value

                            supabase.table("users").update(payload).eq("username", page.u_id).execute()
                            page.display_name = new_name.value
                            page.snack_bar = ft.SnackBar(ft.Text("Profil mis à jour !"))
                            page.snack_bar.open = True
                            ch_v("HOME")
                        except Exception as ex:
                            page.snack_bar = ft.SnackBar(ft.Text(f"Erreur: {ex}"))
                            page.snack_bar.open = True
                            page.update()

                    screen = safe_screen(
                        ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                        ft.Text("PARAMÈTRES UTILISATEUR", weight="bold"),
                        new_name,
                        new_pw,
                        ft.ElevatedButton("METTRE À JOUR", on_click=update_profile, bgcolor="blue"),
                        ft.ElevatedButton(
                            "DÉCONNEXION",
                            icon=ft.Icons.LOGOUT,
                            on_click=lambda _: (setattr(page, "logged_in", False), ch_v("LOGIN")),
                            bgcolor="red900",
                        ),
                        footer_tag,
                    )

                elif page.view == "PART_REQ":
                    p_mach = ft.Dropdown(label="Machine Concernée", options=[ft.dropdown.Option(m) for m in MACHINES])
                    p_name = ft.TextField(label="Nom de la pièce / Référence")
                    p_qty = ft.TextField(label="Quantité", value="1", keyboard_type="number")
                    p_urg = ft.Dropdown(
                        label="Degré d'urgence",
                        options=[
                            ft.dropdown.Option("Normal"),
                            ft.dropdown.Option("Urgent"),
                            ft.dropdown.Option("Critique (Arrêt Machine)"),
                        ],
                    )

                    def save_part_req(e):
                        try:
                            payload = {
                                "machine": p_mach.value,
                                "piece_nom": p_name.value,
                                "qte": p_qty.value,
                                "urgence": p_urg.value,
                                "photo_path": page.photo_part_path or "",
                                "dt": datetime.now().strftime("%d/%m/%Y %H:%M"),
                                "user": page.display_name,
                            }
                            local_execute("INSERT INTO local_part_requests (machine, piece_nom, qte, urgence, photo_path, dt, user, synced) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                                          (payload["machine"], payload["piece_nom"], payload["qte"], payload["urgence"], payload["photo_path"], payload["dt"], payload["user"]))
                            page.photo_part_path = ""
                            trigger_sync()
                            page.snack_bar = ft.SnackBar(ft.Text("✅ Demande pièce enregistrée localement"))
                            page.snack_bar.open = True
                            page.update()
                            ch_v("HOME")
                        except Exception as ex:
                            page.snack_bar = ft.SnackBar(ft.Text(f"Erreur: {ex}"))
                            page.snack_bar.open = True
                            page.update()

                    def pick_part_img(e):
                        page.run_task(pick_from_gallery, "PART")

                    screen = safe_screen(
                        ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                        ft.Text("DEMANDE DE PIÈCE DE RECHANGE", weight="bold", color="orange"),
                        p_mach,
                        p_name,
                        p_qty,
                        p_urg,
                        ft.ElevatedButton("CHOISIR PHOTO PIÈCE", icon=ft.Icons.PHOTO_LIBRARY, on_click=pick_part_img),
                        ft.ElevatedButton("ENVOYER LA DEMANDE", on_click=save_part_req, bgcolor="orange", width=320),
                        ft.ElevatedButton(
                            "HISTORIQUE DEMANDES",
                            icon=ft.Icons.LIST_ALT,
                            on_click=lambda _: ch_v("PART_HISTORY"),
                            width=320,
                        ),
                        footer_tag,
                    )

                elif page.view == "PART_HISTORY":
                    reqs = local_query_all("SELECT * FROM local_part_requests ORDER BY id DESC")
                    lv = ft.ListView(expand=True, spacing=10)
                    for r in reqs:
                        lv.controls.append(
                            ft.Container(
                                content=ft.Column(
                                    [
                                        ft.Text(f"REF: PR-2026-{r['id']} | {r['piece_nom']}", weight="bold"),
                                        ft.Text(f"Machine: {r['machine']} | Qte: {r['qte']} | Urgence: {r['urgence']}"),
                                        ft.IconButton(
                                            ft.Icons.PICTURE_AS_PDF,
                                            icon_color="orange",
                                            on_click=lambda e, row=r: export_part_pdf(row),
                                        ),
                                    ]
                                ),
                                padding=10,
                                border=ft.border.all(1, "orange"),
                                border_radius=10,
                            )
                        )

                    screen = safe_screen(
                        ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: ch_v("PART_REQ")), header_brand]),
                        ft.Text("HISTORIQUE DES DEMANDES PIÈCES"),
                        lv,
                        footer_tag,
                    )

                elif page.view == "STOCK_MGR":
                    stock_lv = ft.ListView(expand=True, spacing=5)

                    def build_stock_list(search=""):
                        try:
                            stock_lv.controls.clear()
                            query = supabase.table("inventory").select("*")
                            if search:
                                query = query.or_(f"designation.ilike.%{search}%,ref.ilike.%{search}%")
                            items = query.execute().data

                            for i in items:
                                is_low = i["stock_qty"] <= i["min_qty"]
                                stock_lv.controls.append(
                                    ft.ListTile(
                                        leading=ft.Icon(ft.Icons.SETTINGS_SUGGEST, color="red" if is_low else "teal"),
                                        title=ft.Text(f"{i['designation']} ({i['ref']})", weight="bold"),
                                        subtitle=ft.Text(f"Emplacement: {i['location']} | Cat: {i['category']}"),
                                        trailing=ft.Column(
                                            [
                                                ft.Text(
                                                    f"Qté: {i['stock_qty']}",
                                                    color="red" if is_low else "white",
                                                    size=16,
                                                    weight="bold",
                                                ),
                                                ft.Text("ALERTE" if is_low else "", color="red", size=10),
                                            ],
                                            alignment=ft.MainAxisAlignment.CENTER,
                                        ),
                                        on_click=lambda e, item=i: open_stock_dialog(item),
                                    )
                                )
                            page.update()
                        except Exception as ex:
                            print("STOCK ERROR:", ex)

                    def open_stock_dialog(item):
                        qty_edit = ft.TextField(label="Ajuster Quantité (+/-)", value="0", width=100)

                        def update_qty(e):
                            try:
                                new_val = item["stock_qty"] + int(qty_edit.value)
                                supabase.table("inventory").update({"stock_qty": new_val}).eq("id", item["id"]).execute()
                                supabase.table("inventory_logs").insert(
                                    {
                                        "part_id": item["id"],
                                        "action": "Manual Adjust",
                                        "qty": int(qty_edit.value),
                                        "machine": "N/A",
                                        "dt": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                    }
                                ).execute()
                                dlg.open = False
                                page.update()
                                build_stock_list()
                            except Exception as ex:
                                page.snack_bar = ft.SnackBar(ft.Text(f"Erreur: {ex}"))
                                page.snack_bar.open = True
                                page.update()

                        dlg = ft.AlertDialog(
                            title=ft.Text(f"Modifier {item['designation']}"),
                            content=ft.Column([ft.Text(f"Stock actuel: {item['stock_qty']}"), qty_edit], height=100),
                            actions=[
                                ft.TextButton("Annuler", on_click=lambda _: (setattr(dlg, "open", False), page.update())),
                                ft.ElevatedButton("Valider", on_click=update_qty),
                            ],
                        )
                        page.dialog = dlg
                        dlg.open = True
                        page.update()

                    def open_add_part(e):
                        r_f = ft.TextField(label="Référence")
                        d_f = ft.TextField(label="Désignation")
                        c_f = ft.TextField(label="Catégorie")
                        q_f = ft.TextField(label="Stock Initial", value="0")
                        m_f = ft.TextField(label="Stock Minimum", value="1")
                        l_f = ft.TextField(label="Emplacement")

                        def save_new(e):
                            try:
                                supabase.table("inventory").insert(
                                    {
                                        "ref": r_f.value,
                                        "designation": d_f.value,
                                        "category": c_f.value,
                                        "stock_qty": int(q_f.value),
                                        "min_qty": int(m_f.value),
                                        "location": l_f.value,
                                    }
                                ).execute()
                                add_dlg.open = False
                                page.update()
                                build_stock_list()
                            except Exception as ex:
                                page.snack_bar = ft.SnackBar(ft.Text(f"Erreur: {ex}"))
                                page.snack_bar.open = True
                                page.update()

                        add_dlg = ft.AlertDialog(
                            title=ft.Text("Nouvelle Pièce"),
                            content=ft.Column([r_f, d_f, c_f, q_f, m_f, l_f], scroll=ft.ScrollMode.AUTO),
                            actions=[ft.ElevatedButton("Ajouter", on_click=save_new)],
                        )
                        page.dialog = add_dlg
                        add_dlg.open = True
                        page.update()

                    search_stock = ft.TextField(
                        label="Chercher une pièce...",
                        prefix_icon=ft.Icons.SEARCH,
                        on_change=lambda e: build_stock_list(e.control.value),
                    )

                    screen = safe_screen(
                        ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                        ft.Row(
                            [
                                ft.Text("GESTION DU STOCK PIÈCES", size=20, weight="bold"),
                                ft.Icon(ft.Icons.INVENTORY_2, color="teal"),
                            ]
                        ),
                        search_stock,
                        ft.Row(
                            [
                                ft.ElevatedButton("AJOUTER PIÈCE", icon=ft.Icons.ADD, on_click=open_add_part, bgcolor="teal"),
                                ft.ElevatedButton(
                                    "EXPORT EXCEL",
                                    icon=ft.Icons.FILE_DOWNLOAD,
                                    on_click=export_inventory_excel,
                                    bgcolor="green700",
                                ),
                            ]
                        ),
                        stock_lv,
                        footer_tag,
                    )
                    build_stock_list()

                elif page.view == "ROUTINE":
                    m_dd = ft.Dropdown(label="Machine", options=[ft.dropdown.Option(m) for m in MACHINES])
                    c_grease = ft.Checkbox(label="Graissage")
                    c_oil = ft.Checkbox(label="Huilage")
                    c_elec = ft.Checkbox(label="Serrage électriques")
                    c_sec = ft.Checkbox(label="Test sécurité")
                    dur_in = ft.TextField(label="Temps passé (Minutes)", keyboard_type="number")
                    remarks_in = ft.TextField(label="Remarques / Description", multiline=True, min_lines=2, max_lines=4, width=320)

                    def save_r(e):
                        try:
                            payload = {
                                "machine": m_dd.value,
                                "freq": "Daily",
                                "graissage": str(c_grease.value),
                                "huilage": str(c_oil.value),
                                "serrage": str(c_elec.value),
                                "securite": str(c_sec.value),
                                "duree": dur_in.value,
                                "remarks": remarks_in.value,
                                "dt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "user": page.display_name,
                            }
                            local_execute("INSERT INTO local_routines (machine, freq, graissage, huilage, serrage, securite, duree, remarks, dt, user, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                                          (payload["machine"], payload["freq"], payload["graissage"], payload["huilage"], payload["serrage"], payload["securite"], payload["duree"], payload["remarks"], payload["dt"], payload["user"]))
                            trigger_sync()
                            page.snack_bar = ft.SnackBar(ft.Text("✅ Check enregistré localement"))
                            page.snack_bar.open = True
                            page.update()
                            ch_v("HOME")
                        except Exception as ex:
                            page.snack_bar = ft.SnackBar(ft.Text(f"Erreur: {ex}"))
                            page.snack_bar.open = True
                            page.update()

                    screen = safe_screen(
                        ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                        ft.Text("CHECK QUOTIDIEN", weight="bold"),
                        m_dd,
                        c_grease,
                        c_oil,
                        c_elec,
                        c_sec,
                        dur_in,
                        remarks_in,
                        ft.ElevatedButton("SAUVEGARDER", on_click=save_r, bgcolor="green", width=320),
                        ft.Row(
                            [
                                ft.ElevatedButton("HISTORIQUE", icon=ft.Icons.HISTORY, on_click=lambda _: ch_v("ROUTINE_HISTORY")),
                                ft.ElevatedButton(
                                    "RAPPORT HEBDO (PDF)",
                                    icon=ft.Icons.SUMMARIZE,
                                    on_click=generate_weekly_pdf,
                                    bgcolor="blue900",
                                ),
                            ]
                        ),
                        footer_tag,
                    )

                elif page.view == "ROUTINE_HISTORY":
                    rows = local_query_all("SELECT * FROM local_routines ORDER BY id DESC")
                    lv = ft.ListView(expand=True)

                    for r in rows:
                        lv.controls.append(
                            ft.Container(
                                content=ft.Column(
                                    [
                                        ft.Text(f"{r['dt']} - {r['machine']}", weight="bold"),
                                        ft.Text(f"Par: {r['user']} | Durée: {r['duree']} min"),
                                        ft.Text(
                                            f"Checklist: G:{r['graissage']} H:{r['huilage']} S:{r['serrage']} Sec:{r['securite']}",
                                            size=12,
                                        ),
                                        ft.Text(f"Remarques: {r.get('remarks', '')}", size=12, color="grey400"),
                                    ]
                                ),
                                padding=10,
                                border=ft.border.all(1, "grey700"),
                                border_radius=10,
                            )
                        )

                    screen = safe_screen(
                        ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: ch_v("ROUTINE")), header_brand]),
                        ft.Text("HISTORIQUE DES INSPECTIONS", weight="bold"),
                        ft.ElevatedButton(
                            "EXPORTER EXCEL",
                            icon=ft.Icons.FILE_DOWNLOAD,
                            on_click=export_routines_excel,
                            bgcolor="green700",
                        ),
                        lv,
                        footer_tag,
                    )

                elif page.view == "INTER":
                    dem = ft.TextField(label="Demandeur", value="Production")
                    mold_ref_field = ft.TextField(label="Référence du Moule", visible=False)

                    def on_sys_change(e):
                        mold_ref_field.visible = sys_dd.value == "Moule"
                        page.update()

                    sys_dd = ft.Dropdown(
                        label="Machine / Système",
                        options=[ft.dropdown.Option(m) for m in MACHINES],
                    )
                    sys_dd.on_change = on_sys_change
                    s_ens = ft.TextField(label="Sous-Ensemble")
                    m_type = ft.Dropdown(
                        label="Type Maintenance",
                        options=[ft.dropdown.Option("Corrective"), ft.dropdown.Option("Préventive")],
                    )
                    piec = ft.TextField(label="Pièces de rechange")
                    spare_price_in = ft.TextField(label="Coût Total Pièces (DZD)", keyboard_type="number", value="0")

                    error_other_desc = ft.TextField(label="Précisez le type d'erreur", visible=False)

                    def on_source_change(e):
                        error_other_desc.visible = error_source.value == "Autre"
                        page.update()

                    error_source = ft.Dropdown(
                        label="Source de l'erreur",
                        options=[
                            ft.dropdown.Option("Opérateur"),
                            ft.dropdown.Option("Technique"),
                            ft.dropdown.Option("Autre"),
                        ],
                    )
                    error_source.on_change = on_source_change

                    err_desc = ft.TextField(label="Identification de l'Erreur", multiline=True)
                    sol_desc = ft.TextField(label="Solution Apportée", multiline=True)

                    def pick_img(target):
                        page.last_action_status = f"Clic photo: {target}"
                        page.update()
                        page.run_task(pick_from_gallery, target)

                    def save_i(e):
                        try:
                            if piec.value:
                                part = local_query_one("SELECT * FROM inventory_cache WHERE designation = ?", (piec.value,)) if False else None

                            payload = {
                                "demandeur": dem.value,
                                "intervenant": page.display_name,
                                "date": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                                "systeme": sys_dd.value,
                                "sous_ens": s_ens.value,
                                "error_desc": err_desc.value,
                                "solution_desc": sol_desc.value,
                                "pieces": piec.value,
                                "type_m": m_type.value,
                                "photo_err": page.photo_err_path or "",
                                "photo_sol": page.photo_sol_path or "",
                                "error_source": error_source.value,
                                "error_other": error_other_desc.value,
                                "user": page.display_name,
                                "mold_ref": mold_ref_field.value,
                                "spare_price": spare_price_in.value,
                            }
                            local_execute(
                                "INSERT INTO local_inters (demandeur, intervenant, date, systeme, sous_ens, error_desc, solution_desc, pieces, type_m, photo_err, photo_sol, error_source, error_other, user, mold_ref, spare_price, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                                (payload["demandeur"], payload["intervenant"], payload["date"], payload["systeme"], payload["sous_ens"], payload["error_desc"], payload["solution_desc"], payload["pieces"], payload["type_m"], payload["photo_err"], payload["photo_sol"], payload["error_source"], payload["error_other"], payload["user"], payload["mold_ref"], payload["spare_price"])
                            )
                            page.photo_err_path = ""
                            page.photo_sol_path = ""
                            trigger_sync()
                            page.snack_bar = ft.SnackBar(ft.Text("✅ Rapport enregistré localement"))
                            page.snack_bar.open = True
                            page.update()
                            ch_v("HOME")
                        except Exception as ex:
                            page.snack_bar = ft.SnackBar(ft.Text(f"Erreur: {ex}"))
                            page.snack_bar.open = True
                            page.update()

                    screen = safe_screen(
                        ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                        ft.Text("NOUVEAU RAPPORT D'INTERVENTION", weight="bold"),
                        ft.Text(page.last_action_status or "Photo: utilisez la galerie pour choisir une image.", color="yellow"),
                        dem,
                        sys_dd,
                        mold_ref_field,
                        s_ens,
                        m_type,
                        error_source,
                        error_other_desc,
                        ft.Column([
                            err_desc,
                            ft.ElevatedButton("CHOISIR PHOTO PROBLÈME", icon=ft.Icons.PHOTO_LIBRARY, on_click=lambda e: pick_img("ERR"), bgcolor="red900"),
                        ]),
                        ft.Column([
                            sol_desc,
                            ft.ElevatedButton("CHOISIR PHOTO SOLUTION", icon=ft.Icons.PHOTO_LIBRARY, on_click=lambda e: pick_img("SOL"), bgcolor="green900"),
                        ]),
                        piec,
                        spare_price_in,
                        ft.ElevatedButton("ENREGISTRER & DESTOCKER", on_click=save_i, bgcolor="blue", width=320),
                        footer_tag,
                    )

                elif page.view == "REPORT_VIEW":
                    row = page.current_report or {}
                    imgs = []
                    if row.get("photo_err"):
                        imgs.append(ft.Column([ft.Text("Photo problème", weight="bold", color="red"), ft.Image(src=row.get("photo_err"), width=300, height=180, fit=ft.ImageFit.CONTAIN)]))
                    if row.get("photo_sol"):
                        imgs.append(ft.Column([ft.Text("Photo solution", weight="bold", color="green"), ft.Image(src=row.get("photo_sol"), width=300, height=180, fit=ft.ImageFit.CONTAIN)]))

                    screen = safe_screen(
                        ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: ch_v("HISTORY")), header_brand]),
                        ft.Text("APERÇU DU RAPPORT", weight="bold", size=20),
                        ft.Text(f"REF: INT-LOCAL-{row.get('id','')}", weight="bold"),
                        ft.Text(f"Machine / Système: {row.get('systeme','')}"),
                        ft.Text(f"Date: {row.get('date','')}"),
                        ft.Text(f"Intervenant: {row.get('intervenant', row.get('user',''))}"),
                        ft.Text(f"Demandeur: {row.get('demandeur','')}"),
                        ft.Text(f"Type maintenance: {row.get('type_m','')}"),
                        ft.Text(f"Source erreur: {row.get('error_source','')}"),
                        ft.Text("Identification de l'erreur", weight="bold"),
                        ft.Text(row.get('error_desc','') or "-"),
                        ft.Text("Solution apportée", weight="bold"),
                        ft.Text(row.get('solution_desc','') or "-"),
                        *imgs,
                        ft.Row([
                            ft.ElevatedButton("TÉLÉCHARGER PDF", icon=ft.Icons.PICTURE_AS_PDF, on_click=lambda e, data=row: export_pdf(data), bgcolor="red900"),
                            ft.ElevatedButton("EXPORT EXCEL", icon=ft.Icons.TABLE_CHART, on_click=export_excel, bgcolor="green700"),
                        ], wrap=True),
                        footer_tag,
                    )

                elif page.view == "HISTORY":
                    lv = ft.ListView(expand=True, spacing=10)

                    def build_history(search_term=""):
                        try:
                            lv.controls.clear()
                            reports = local_query_all("SELECT * FROM local_inters ORDER BY id DESC")
                            if search_term:
                                reports = [r for r in reports if search_term.lower() in str(r.get("systeme","")).lower() or search_term.lower() in str(r.get("user","")).lower()]

                            for r in reports:
                                lv.controls.append(
                                    ft.Container(
                                        content=ft.Column(
                                            [
                                                ft.Row([ft.Text(f"REF: INT-2026-{r['id']} | {r['systeme']}", weight="bold")]),
                                                ft.Row(
                                                    [
                                                        ft.IconButton(
                                                            ft.Icons.VISIBILITY,
                                                            icon_color="blue",
                                                            on_click=lambda e, row=r: open_report_viewer(row),
                                                        ),
                                                        ft.IconButton(
                                                            ft.Icons.PICTURE_AS_PDF,
                                                            icon_color="red",
                                                            on_click=lambda e, row=r: export_pdf(row),
                                                        )
                                                    ]
                                                ),
                                            ]
                                        ),
                                        padding=10,
                                        border=ft.border.all(1, "grey700"),
                                        border_radius=10,
                                    )
                                )
                            page.update()
                        except Exception as ex:
                            print("HISTORY ERROR:", ex)

                    search_bar = ft.TextField(
                        label="Chercher par machine...",
                        prefix_icon=ft.Icons.SEARCH,
                        on_change=lambda e: build_history(e.control.value),
                    )
                    screen = safe_screen(
                        ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                        ft.Text("HISTORIQUE DES INTERVENTIONS", size=20, weight="bold"),
                        search_bar,
                        ft.ElevatedButton(
                            "EXPORTER EXCEL (INTERVENTIONS)",
                            icon=ft.Icons.TABLE_CHART,
                            on_click=export_excel,
                            width=320,
                        ),
                        lv,
                        footer_tag,
                    )
                    build_history()

                elif page.view == "MOLD":
                    MODEL_PARAMS = {
                        "D927": {"modele": "11", "matiere": "A018", "mpa": "24", "cycle": "4", "temps": "320"},
                        "FDB1399": {"modele": "11", "matiere": "A018", "mpa": "16", "cycle": "4", "temps": "320"},
                        "D1630": {"modele": "11", "matiere": "A018", "mpa": "20", "cycle": "4", "temps": "320"},
                        "D1871": {"modele": "11", "matiere": "A018", "mpa": "24", "cycle": "4", "temps": "320"},
                        "D1455": {"modele": "11", "matiere": "A018", "mpa": "24", "cycle": "4", "temps": "360"},
                        "D1316": {"modele": "11", "matiere": "A018", "mpa": "24", "cycle": "4", "temps": "360"},
                        "D1375": {"modele": "11", "matiere": "A018", "mpa": "21", "cycle": "4", "temps": "360"},
                        "D1872": {"modele": "11", "matiere": "A018", "mpa": "23", "cycle": "4", "temps": "320"},
                        "D1761": {"modele": "11", "matiere": "A018", "mpa": "20", "cycle": "4", "temps": "320"},
                        "D497": {"modele": "11", "matiere": "A018", "mpa": "15", "cycle": "3", "temps": "300"},
                        "D1717": {"modele": "11", "matiere": "A018", "mpa": "18", "cycle": "4", "temps": "320"},
                        "D1107": {"modele": "23", "matiere": "A018", "mpa": "21", "cycle": "4", "temps": "320"},
                        "D1456": {"modele": "23", "matiere": "A018", "mpa": "22", "cycle": "4", "temps": "320"},
                        "D340": {"modele": "23", "matiere": "A018", "mpa": "22", "cycle": "4", "temps": "320"},
                        "FDB4349": {"modele": "23", "matiere": "A018", "mpa": "24", "cycle": "4", "temps": "320"},
                        "D1985": {"modele": "23", "matiere": "A018", "mpa": "24", "cycle": "4", "temps": "320"},
                        "D1108": {"modele": "23", "matiere": "A018", "mpa": "23", "cycle": "4", "temps": "320"},
                        "D768": {"modele": "23", "matiere": "A018", "mpa": "19", "cycle": "4", "temps": "320"},
                        "D2236": {"modele": "23", "matiere": "A018", "mpa": "25", "cycle": "4", "temps": "320"},
                        "GDB1681": {"modele": "23", "matiere": "A018", "mpa": "24", "cycle": "4", "temps": "320"},
                        "D1760": {"modele": "23", "matiere": "A018", "mpa": "21", "cycle": "4", "temps": "320"},
                        "D1633": {"modele": "23", "matiere": "A018", "mpa": "22", "cycle": "4", "temps": "320"},
                        "D2484": {"modele": "23", "matiere": "A018", "mpa": "23", "cycle": "4", "temps": "320"},
                        "D2023": {"modele": "23", "matiere": "A018", "mpa": "24", "cycle": "4", "temps": "320"},
                        "77368831/WVA25323": {"modele": "23", "matiere": "A018", "mpa": "19", "cycle": "4", "temps": "320"},
                        "77368368": {"modele": "23", "matiere": "A018", "mpa": "24", "cycle": "3", "temps": "300"},
                        "D1950": {"modele": "23", "matiere": "A018", "mpa": "20", "cycle": "4", "temps": "320"},
                        "GDB400": {"modele": "23", "matiere": "A018", "mpa": "21", "cycle": "4", "temps": "320"},
                    }

                    p_dd = ft.Dropdown(label="Presse", options=[ft.dropdown.Option(f"Presse {i}") for i in range(1, 12)])
                    o_m = ft.TextField(label="Moule Sortant", read_only=True)
                    n_m = ft.TextField(label="Nouveau Moule")
                    info_txt = ft.Text("", color="yellow")
                    model_no = ft.TextField(label="Modèle")
                    matiere = ft.TextField(label="Matière", value="A018")
                    mpa = ft.TextField(label="Mpa")
                    cycle = ft.TextField(label="Cycle")
                    temps = ft.TextField(label="Temps (s)")

                    def fill_fields(data, mold_name=None):
                        if mold_name is not None:
                            o_m.value = str(mold_name or "")
                        model_no.value = str(data.get("modele", "") or "")
                        matiere.value = str(data.get("matiere", "A018") or "A018")
                        mpa.value = str(data.get("mpa", "") or "")
                        cycle.value = str(data.get("cycle", "") or "")
                        temps.value = str(data.get("temps", "") or "")

                    def clear_param_fields():
                        model_no.value = ""
                        matiere.value = "A018"
                        mpa.value = ""
                        cycle.value = ""
                        temps.value = ""

                    def load_press_current_mold():
                        try:
                            if not p_dd.value:
                                o_m.value = ""
                                clear_param_fields()
                                info_txt.value = ""
                                page.update()
                                return

                            press = p_dd.value
                            current = local_query_one("SELECT * FROM local_press_current_mold WHERE presse = ?", (press,))
                            if not current and supabase is not None:
                                try:
                                    res = supabase.table("press_current_mold").select("*").eq("presse", press).limit(1).execute()
                                    if res.data:
                                        row = res.data[0]
                                        local_execute(
                                            "INSERT OR REPLACE INTO local_press_current_mold (presse, mold_name, modele, matiere, mpa, cycle, temps, updated_by, updated_at, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                                            (row.get("presse"), row.get("mold_name"), row.get("modele"), row.get("matiere"), str(row.get("mpa","") or ""), str(row.get("cycle","") or ""), str(row.get("temps","") or ""), row.get("updated_by",""), row.get("updated_at",""))
                                        )
                                        current = local_query_one("SELECT * FROM local_press_current_mold WHERE presse = ?", (press,))
                                except Exception as ex:
                                    print("REMOTE CURRENT MOLD LOAD ERROR:", ex)

                            if not current:
                                hist = local_query_one("SELECT * FROM local_molds WHERE p_no = ? ORDER BY id DESC LIMIT 1", (press,))
                                if hist:
                                    current = {
                                        "mold_name": hist.get("new_m", "") or "",
                                        "modele": hist.get("modele", "") or "",
                                        "matiere": hist.get("matiere", "A018") or "A018",
                                        "mpa": hist.get("mpa", "") or "",
                                        "cycle": hist.get("cycle", "") or "",
                                        "temps": hist.get("temps", "") or "",
                                    }

                            if current:
                                loaded_name = str(current.get("mold_name", "") or "")
                                fill_fields(current, loaded_name)
                                info_txt.value = f"Moule sortant chargé: {loaded_name}" if loaded_name else "Aucun ancien moule enregistré pour cette presse."
                            else:
                                o_m.value = ""
                                clear_param_fields()
                                info_txt.value = "Aucun ancien moule enregistré pour cette presse."
                            page.update()
                        except Exception as ex:
                            print("MOLD LOAD ERROR:", ex)
                            info_txt.value = f"Erreur chargement presse: {ex}"
                            page.update()

                    def load_mold_params_by_name():
                        try:
                            mold_name = (n_m.value or "").strip().upper()
                            if not mold_name:
                                load_press_current_mold()
                                return
                            if mold_name in MODEL_PARAMS:
                                fill_fields(MODEL_PARAMS[mold_name], o_m.value)
                                info_txt.value = "Paramètres chargés automatiquement."
                                page.update()
                                return
                            row = local_query_one("SELECT * FROM local_mold_parameters WHERE mold_name = ?", (mold_name,))
                            if not row and supabase is not None:
                                try:
                                    db_res = supabase.table("mold_parameters").select("*").eq("mold_name", mold_name).limit(1).execute()
                                    if db_res.data:
                                        rr = db_res.data[0]
                                        local_execute(
                                            "INSERT OR REPLACE INTO local_mold_parameters (mold_name, modele, matiere, mpa, cycle, temps, updated_by, updated_at, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                                            (rr.get("mold_name"), rr.get("modele"), rr.get("matiere"), str(rr.get("mpa","") or ""), str(rr.get("cycle","") or ""), str(rr.get("temps","") or ""), rr.get("updated_by",""), rr.get("updated_at",""))
                                        )
                                        row = local_query_one("SELECT * FROM local_mold_parameters WHERE mold_name = ?", (mold_name,))
                                except Exception as ex:
                                    print("REMOTE PARAM LOAD ERROR:", ex)
                            if row:
                                fill_fields(row, o_m.value)
                                info_txt.value = "Paramètres récupérés."
                            else:
                                clear_param_fields()
                                info_txt.value = "Aucun paramètre trouvé. Vous pouvez les saisir puis enregistrer."
                            page.update()
                        except Exception as ex:
                            print("LOAD MOLD PARAMS ERROR:", ex)
                            info_txt.value = f"Erreur paramètres: {ex}"
                            page.update()

                    p_dd.on_change = lambda e: load_press_current_mold()
                    n_m.on_change = lambda e: load_mold_params_by_name()

                    def save_m(e):
                        try:
                            if not p_dd.value:
                                page.snack_bar = ft.SnackBar(ft.Text("Choisissez une presse."))
                                page.snack_bar.open = True
                                page.update()
                                return
                            mold_name = (n_m.value or "").strip().upper()
                            if not mold_name:
                                page.snack_bar = ft.SnackBar(ft.Text("Entrez le nom du moule."))
                                page.snack_bar.open = True
                                page.update()
                                return

                            old_mold = (o_m.value or "").strip()
                            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                            local_execute(
                                "INSERT OR REPLACE INTO local_mold_parameters (mold_name, modele, matiere, mpa, cycle, temps, updated_by, updated_at, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                                (mold_name, model_no.value, matiere.value or "A018", str(mpa.value).strip(), str(cycle.value).strip(), temps.value, page.display_name, now_str)
                            )
                            local_execute(
                                "INSERT OR REPLACE INTO local_press_current_mold (presse, mold_name, modele, matiere, mpa, cycle, temps, updated_by, updated_at, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                                (p_dd.value, mold_name, model_no.value, matiere.value or "A018", str(mpa.value).strip(), str(cycle.value).strip(), temps.value, page.display_name, now_str)
                            )
                            local_execute(
                                "INSERT INTO local_molds (p_no, old_m, new_m, modele, matiere, mpa, cycle, temps, dt, user, synced) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                                (p_dd.value, old_mold, mold_name, model_no.value, matiere.value or "A018", str(mpa.value).strip(), str(cycle.value).strip(), temps.value, now_str, page.display_name)
                            )
                            o_m.value = mold_name
                            n_m.value = ""
                            info_txt.value = "✅ Changement moule enregistré localement."
                            page.snack_bar = ft.SnackBar(ft.Text("✅ Changement moule enregistré localement."))
                            page.snack_bar.open = True
                            page.update()
                            trigger_sync()
                            load_press_current_mold()
                        except Exception as ex:
                            print("SAVE MOLD ERROR:", ex)
                            info_txt.value = f"Erreur moule: {ex}"
                            page.snack_bar = ft.SnackBar(ft.Text(f"Erreur moule: {ex}"))
                            page.snack_bar.open = True
                            page.update()

                    screen = safe_screen(
                        ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                        ft.Text("CHANGEMENT MOULE (SMED)", size=20, weight="bold"),
                        p_dd,
                        o_m,
                        n_m,
                        info_txt,
                        model_no,
                        matiere,
                        mpa,
                        cycle,
                        temps,
                        ft.ElevatedButton("VALIDER", on_click=save_m, width=320, bgcolor="blue900"),
                        ft.ElevatedButton("HISTORIQUE DES MOULES", icon=ft.Icons.HISTORY_TOGGLE_OFF, on_click=lambda _: ch_v("MOLD_HISTORY"), width=320),
                        footer_tag,
                    )

                elif page.view == "MOLD_HISTORY":
                    m_reports = local_query_all("SELECT * FROM local_molds ORDER BY id DESC")
                    lv = ft.ListView(expand=True, spacing=10)

                    for r in m_reports:
                        lv.controls.append(
                            ft.Container(
                                content=ft.Column(
                                    [
                                        ft.Row([ft.Text(f"{r['dt']} - {r['p_no']}", weight="bold")]),
                                        ft.Row([ft.Text(f"Sortant: {r.get('old_m', '')}   ➔ Nouveau: {r.get('new_m', '')}")]),
                                        ft.Text(
                                            f"Modèle: {r.get('modele', '')} | Matière: {r.get('matiere', '')} | Mpa: {r.get('mpa', '')} | Cycle: {r.get('cycle', '')} | Temps: {r.get('temps', '')}",
                                            size=12,
                                            color="grey400",
                                        ),
                                    ]
                                ),
                                padding=10,
                                border=ft.border.all(1, "grey700"),
                                border_radius=10,
                            )
                        )

                    screen = safe_screen(
                        ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: ch_v("MOLD")), header_brand]),
                        ft.Text("HISTORIQUE DES MOULES", weight="bold"),
                        lv,
                        footer_tag,
                    )

                else:
                    screen = safe_screen(
                        header_brand,
                        ft.Text(f"Vue inconnue: {page.view}", color="red"),
                        ft.ElevatedButton("Retour Accueil", on_click=lambda _: ch_v("HOME")),
                        footer_tag,
                    )

                content_area.content = screen

                if content_area not in page.controls:
                    page.controls.clear()
                    page.add(content_area)

                page.update()

            except Exception as e:
                print(f"Error in refresh: {e}")
                content_area.content = safe_screen(
                    ft.Text("ERREUR D'AFFICHAGE", color="red", size=24, weight="bold"),
                    ft.Text(str(e), color="white"),
                    ft.ElevatedButton("Retour Login", on_click=lambda _: ch_v("LOGIN")),
                    footer_tag,
                )
                if content_area not in page.controls:
                    page.controls.clear()
                    page.add(content_area)
                page.update()

        def export_with_message(path, success_text):
            page.snack_bar = ft.SnackBar(ft.Text(success_text))
            page.snack_bar.open = True
            page.update()
            try_open_file(path)

        def export_routines_excel(e=None):
            try:
                data = local_query_all("SELECT * FROM local_routines ORDER BY id DESC")
                df = pd.DataFrame(data)
                base_name = f"BRIKS_Daily_Inspections_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                filename = get_export_path(base_name)
                df.to_excel(filename, index=False)
                export_with_message(filename, f"Exporté : {base_name}")
            except Exception as ex:
                page.snack_bar = ft.SnackBar(ft.Text(f"Erreur export: {ex}"))
                page.snack_bar.open = True
                page.update()

        def export_excel(e=None):
            try:
                data = local_query_all("SELECT * FROM local_inters ORDER BY id DESC")
                df = pd.DataFrame(data)
                base_name = f"BRIKS_Rapports_Global_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                filename = get_export_path(base_name)
                df.to_excel(filename, index=False)
                export_with_message(filename, f"Excel exporté : {base_name}")
            except Exception as ex:
                page.snack_bar = ft.SnackBar(ft.Text(f"Erreur export: {ex}"))
                page.snack_bar.open = True
                page.update()

        def export_molds_excel(e=None):
            try:
                data = supabase.table("molds").select("*").execute().data
                df = pd.DataFrame(data)
                base_name = f"BRIKS_Tracking_Moules_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                filename = get_export_path(base_name)
                df.to_excel(filename, index=False)
                export_with_message(filename, f"Excel exporté : {base_name}")
            except Exception as ex:
                page.snack_bar = ft.SnackBar(ft.Text(f"Erreur export: {ex}"))
                page.snack_bar.open = True
                page.update()

        def export_inventory_excel(e=None):
            try:
                data = supabase.table("inventory").select("*").execute().data
                df = pd.DataFrame(data)
                base_name = f"BRIKS_Stock_Inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                filename = get_export_path(base_name)
                df.to_excel(filename, index=False)
                export_with_message(filename, f"Inventaire exporté : {base_name}")
            except Exception as ex:
                page.snack_bar = ft.SnackBar(ft.Text(f"Erreur export: {ex}"))
                page.snack_bar.open = True
                page.update()

        def generate_weekly_pdf(e=None):
            try:
                last_week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
                data = local_query_all("SELECT * FROM local_routines WHERE dt >= ? ORDER BY id DESC", (last_week,))

                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", "B", 16)
                pdf.cell(190, 10, "BRIKS - RAPPORT HEBDOMADAIRE", ln=True, align="C")
                pdf.set_font("Arial", "", 10)
                pdf.cell(190, 10, f"Période: du {last_week} au {datetime.now().strftime('%Y-%m-%d')}", ln=True, align="C")
                pdf.ln(10)

                pdf.set_font("Arial", "B", 10)
                pdf.cell(40, 10, "Date/Heure", 1)
                pdf.cell(40, 10, "Machine", 1)
                pdf.cell(30, 10, "Opérateur", 1)
                pdf.cell(80, 10, "Points de contrôle", 1)
                pdf.ln()

                pdf.set_font("Arial", "", 8)
                for r in data:
                    checklist = f"Gr:{r['graissage']}, Hu:{r['huilage']}, Se:{r['serrage']}, Sec:{r['securite']}"
                    pdf.cell(40, 8, str(r["dt"]), 1)
                    pdf.cell(40, 8, str(r["machine"]), 1)
                    pdf.cell(30, 8, str(r["user"]), 1)
                    pdf.cell(80, 8, checklist, 1)
                    pdf.ln()

                base_name = f"Rapport_Hebdo_{datetime.now().strftime('%Y%W')}.pdf"
                fname = get_export_path(base_name)
                pdf.output(fname)

                export_with_message(fname, f"Rapport Hebdo créé: {base_name}")
            except Exception as ex:
                page.snack_bar = ft.SnackBar(ft.Text(f"Erreur : {ex}"))
                page.snack_bar.open = True
                page.update()

        def export_pdf(row):
            try:
                pdf = FPDF()
                pdf.add_page()

                pdf.set_font("Arial", "B", 22)
                pdf.set_text_color(140, 0, 0)
                pdf.cell(190, 10, "BRIKS", ln=True, align="C")
                pdf.set_font("Arial", "I", 10)
                pdf.cell(190, 6, "RAPPORT D'INTERVENTION TECHNIQUE", ln=True, align="C")
                pdf.ln(5)

                pdf.set_text_color(0, 0, 0)
                pdf.set_font("Arial", "B", 9)

                pdf.cell(100, 8, f"Machine: {row.get('systeme', '')}", border=1)
                pdf.cell(90, 8, f"Date: {row.get('date', '')}", border=1, ln=True)
                pdf.cell(100, 8, f"Source de l'erreur: {row.get('error_source', '')}", border=1)
                pdf.cell(90, 8, f"Intervenant: {row.get('intervenant', '')}", border=1, ln=True)
                pdf.ln(5)

                def draw_section(title, desc, photo_url, y_start):
                    pdf.set_xy(10, y_start)
                    pdf.set_font("Arial", "B", 9)
                    pdf.cell(95, 8, title, border="LTR", ln=True)
                    pdf.set_font("Arial", "", 8)

                    pdf.multi_cell(95, 5, str(desc), border="LR")
                    current_y = pdf.get_y()
                    if current_y < y_start + 48:
                        pdf.cell(95, (y_start + 48) - current_y, "", border="LRB", ln=True)
                    else:
                        pdf.cell(95, 0, "", border="T", ln=True)

                    pdf.set_xy(110, y_start)
                    pdf.set_font("Arial", "B", 9)
                    pdf.cell(80, 8, "PHOTO:", border=1, ln=True)
                    pdf.set_xy(110, y_start + 8)
                    pdf.cell(80, 40, "", border=1, ln=True)

                    if photo_url and str(photo_url).startswith("http"):
                        try:
                            temp_img = os.path.join(tempfile.gettempdir(), f"temp_img_{os.urandom(4).hex()}.jpg")
                            urllib.request.urlretrieve(photo_url, temp_img)
                            pdf.image(temp_img, x=112, y=y_start + 10, w=76, h=36)
                            os.remove(temp_img)
                        except Exception:
                            pass

                    return max(pdf.get_y(), y_start + 48) + 5

                y_next = draw_section("1. IDENTIFICATION DE L'ERREUR:", row.get("error_desc", ""), row.get("photo_err", ""), pdf.get_y())
                y_next = draw_section("2. SOLUTION APPORTEE:", row.get("solution_desc", ""), row.get("photo_sol", ""), y_next)

                pdf.set_xy(10, y_next)
                pdf.set_font("Arial", "B", 9)
                pdf.cell(190, 8, "CONSOMMABLES & PIECES DE RECHANGE:", border=1, ln=True)
                pdf.set_font("Arial", "", 8)
                pdf.cell(190, 8, f"Description: {row.get('pieces', '')}", border="LR", ln=True)
                pdf.cell(190, 8, f"Coût: {row.get('spare_price', '0')} DZD", border="LRB", ln=True)

                pdf.ln(20)
                pdf.set_font("Arial", "", 9)
                pdf.cell(95, 5, "Chef de Production", align="C")
                pdf.cell(95, 5, "Service Maintenance", align="C", ln=True)

                base_name = f"Rapport_{row.get('id', 'N')}_{datetime.now().strftime('%H%M%S')}.pdf"
                fname = get_export_path(base_name)
                pdf.output(fname)

                export_with_message(fname, f"Rapport PDF généré : {base_name}")
            except Exception as ex:
                page.snack_bar = ft.SnackBar(ft.Text(f"Erreur PDF: {ex}"))
                page.snack_bar.open = True
                page.update()

        def export_part_pdf(row):
            try:
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Arial", "B", 16)
                pdf.cell(190, 10, "DEMANDE DE PIECE DE RECHANGE", ln=True, align="C")
                pdf.ln(10)

                pdf.set_font("Arial", "", 12)
                pdf.cell(190, 8, f"Reference: PR-2026-{row.get('id', '')}", ln=True)
                pdf.cell(190, 8, f"Piece: {row.get('piece_nom', '')}", ln=True)
                pdf.cell(190, 8, f"Machine: {row.get('machine', '')}", ln=True)
                pdf.cell(190, 8, f"Quantite: {row.get('qte', '')}", ln=True)
                pdf.cell(190, 8, f"Urgence: {row.get('urgence', '')}", ln=True)

                if row.get("photo_path") and str(row.get("photo_path")).startswith("http"):
                    try:
                        temp_img = os.path.join(tempfile.gettempdir(), f"temp_part_{os.urandom(4).hex()}.jpg")
                        urllib.request.urlretrieve(row["photo_path"], temp_img)
                        pdf.image(temp_img, x=10, y=pdf.get_y() + 10, w=100)
                        os.remove(temp_img)
                    except Exception:
                        pass

                base_name = f"Demande_Piece_{row.get('id', 'N')}.pdf"
                fname = get_export_path(base_name)
                pdf.output(fname)

                export_with_message(fname, f"PDF généré : {base_name}")
            except Exception as ex:
                page.snack_bar = ft.SnackBar(ft.Text(f"Erreur PDF: {ex}"))
                page.snack_bar.open = True
                page.update()

        refresh()

    except Exception as fatal_error:
        page.add(
            ft.Text(
                f"CRITICAL ERROR: {str(fatal_error)}",
                color="white",
                bgcolor="red",
                size=20,
                weight="bold",
            )
        )
        page.update()

ft.app(target=main)