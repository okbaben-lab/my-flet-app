import flet as ft
# import sqlite3  <-- Keeping this for row_factory references in your logic
import os
import shutil
import urllib.request # Added to fetch images for the PDF fix
import tempfile # ARDED: Crucial for Android file writing permissions
import pandas as pd # MOVED TO TOP: Required for APK builder
from fpdf import FPDF # MOVED TO TOP: Required for APK builder
from datetime import datetime, timedelta
from supabase import create_client, Client

# --- SUPABASE CONFIGURATION ---
SUPABASE_URL = "https://lbaquqyzbippicbvmcxr.supabase.co"
SUPABASE_KEY = "lbaquqyzbippicbvmcxr"

# SHIELD: Wrapped in try-except to prevent global crash if network is slow on app boot
try:
    # Note: Using the publishable key provided in your original create_client call
    supabase: Client = create_client(SUPABASE_URL, "sb_publishable_qIs62pb-XO17gSwhXubVqg_2ffU7MOl")
except Exception as e:
    supabase = None
    print(f"Supabase init error: {e}")

# --- CONFIGURATION ---
MACHINES = [
    "Presse 1", "Presse 2", "Presse 3", "Presse 4", "Presse 5", "Presse 6", 
    "Presse 7", "Presse 8", "Presse 9", "Presse 10", "Presse 11",
    "Compresseur d'air", "Aspirateur CNC", "Malaxeur matière", "Machine de colle",
    "Four machine de colle", "CNC profileuse", "CNC profileuse lourd", "Machine de peinture",
    "Four CNC", "Scotcheuse", "Emballeuse", "Cintreuse", "Groupe électrogène",
    "Four produit final", "Pèse matière 1", "Pèse matière 2", "Pèse matière 3",
    "Aspirateur presse", "Aspirateur manuel 1", "Aspirateur manuel 2", "Moule"
]

# --- DATABASE ENGINE (ADAPTED FOR SUPABASE) ---
def setup_db():
    class SupabaseWrapper:
        def execute(self, query, params=None):
            pass
        def commit(self): pass
        def cursor(self): return self
        def fetchone(self): return [1] 
    
    return SupabaseWrapper()

db_conn = setup_db()

# --- MAIN APP ---
def main(page: ft.Page):
    # --- 1. CRITICAL: REGISTER FILEPICKER IMMEDIATELY ---
    def on_file_result(e): # REMOVED TYPE HINT TO FIX CRITICAL ERROR
        if e.files:
            if page.current_upload_target == "ERR":
                page.photo_err_path = e.files[0].path
                page.snack_bar = ft.SnackBar(ft.Text("✅ Photo Erreur attachée"))
            elif page.current_upload_target == "SOL":
                page.photo_sol_path = e.files[0].path
                page.snack_bar = ft.SnackBar(ft.Text("✅ Photo Solution attachée"))
            elif page.current_upload_target == "PART":
                page.photo_part_path = e.files[0].path
                page.snack_bar = ft.SnackBar(ft.Text("✅ Photo Pièce attachée"))
            page.snack_bar.open = True
            page.update()

    file_picker = ft.FilePicker(on_result=on_file_result)
    page.overlay.append(file_picker) # REGISTERED BEFORE ANY BUTTON CALLS

    # --- 2. FORCE ANDROID PERMISSIONS ON STARTUP ---
    def request_android_permissions():
        try:
            # We explicitly request these so Android forces the pop-up
            page.request_permission(ft.PermissionType.STORAGE)
            page.request_permission(ft.PermissionType.CAMERA)
            page.request_permission(ft.PermissionType.MANAGE_EXTERNAL_STORAGE)
        except Exception as e:
            print(f"Permission Request Error: {e}")

    # Trigger permission request as soon as the app loads
    request_android_permissions()

    page.title = "BRIKS BY OKBA - Service maintenance"
    page.theme_mode = "dark"
    page.scroll = "auto"
    page.logged_in = False
    page.view = "LOGIN"
    
    # Persistent State
    page.photo_err_path = ""
    page.photo_sol_path = ""
    page.photo_part_path = "" 
    page.current_upload_target = ""

    # --- UPLOAD LOGIC ---
    def upload_to_supabase(local_path, folder):
        if not local_path or not os.path.exists(local_path):
            return ""
        try:
            user_clean = page.u_id if hasattr(page, 'u_id') else "anon"
            ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            ext = os.path.splitext(local_path)[1] or ".jpg"
            file_name = f"{folder}/{user_clean}_{ts}{ext}"
            
            with open(local_path, "rb") as f:
                supabase.storage.from_("maintenance").upload(file_name, f)
            
            return supabase.storage.from_("maintenance").get_public_url(file_name)
        except Exception as ex:
            print(f"Upload error: {ex}")
            return ""

    footer_tag = ft.Text("Made by Okba Bennaim", size=10, italic=True, color="grey500")
    header_brand = ft.Column([
        ft.Text("BRIKS BY OKBA", size=32, weight="bold", color="red"),
        ft.Text("SERVICE MAINTENANCE", size=12, color="red", italic=True),
    ], spacing=0, horizontal_alignment="center")

    def refresh():
        page.controls.clear()
        
        # --- LOGIN VIEW ---
        if not page.logged_in and page.view == "LOGIN":
            u_in = ft.TextField(label="Utilisateur", width=300)
            p_in = ft.TextField(label="Mot de passe", password=True, width=300)
            login_error = ft.Text("Identifiants incorrects", color="red", visible=False)
            
            def login(e):
                res = supabase.table("users").select("*").eq("username", u_in.value.lower()).eq("password", p_in.value).execute()
                if res.data:
                    page.logged_in = True
                    page.u_id = u_in.value.lower()
                    page.display_name = res.data[0].get('full_name', u_in.value)
                    page.view = "HOME"
                    refresh()
                else:
                    login_error.visible = True
                    page.update()

            page.add(ft.Column([
                ft.Container(height=50),
                header_brand, u_in, p_in,
                login_error,
                ft.ElevatedButton("ENTRER", on_click=login, width=300, bgcolor="red900"),
                ft.TextButton("Créer un compte (Sign Up)", on_click=lambda _: ch_v("SIGNUP")),
                footer_tag
            ], horizontal_alignment="center"))

        elif page.view == "SIGNUP":
            new_user = ft.TextField(label="Nom d'utilisateur (Login)", width=300)
            new_full = ft.TextField(label="Nom complet (Affichage)", width=300)
            new_pass = ft.TextField(label="Mot de passe", password=True, width=300)
            
            def register(e):
                try:
                    supabase.table("users").insert({
                        "username": new_user.value.lower(),
                        "full_name": new_full.value,
                        "password": new_pass.value
                    }).execute()
                    ch_v("LOGIN")
                except Exception as ex:
                    page.snack_bar = ft.SnackBar(ft.Text(f"Erreur lors de l'inscription : {ex}"))
                    page.snack_bar.open = True
                    page.update()

            page.add(ft.Column([
                ft.Container(height=50),
                header_brand,
                ft.Text("CRÉER UN COMPTE", weight="bold", size=20),
                new_user, new_full, new_pass,
                ft.ElevatedButton("S'INSCRIRE", on_click=register, width=300, bgcolor="blue900"),
                ft.TextButton("Retour à la connexion", on_click=lambda _: ch_v("LOGIN")),
                footer_tag
            ], horizontal_alignment="center"))

        # --- HOME VIEW ---
        elif page.view == "HOME":
            page.add(
                ft.Row([
                    ft.Column([
                        ft.Text("BRIKS BY OKBA", size=28, weight="bold", color="red"),
                        ft.Text("SERVICE MAINTENANCE", size=10, color="red", italic=True)
                    ], spacing=0),
                    ft.IconButton(ft.icons.SETTINGS, on_click=lambda _: ch_v("USER"))
                ], alignment="spaceBetween"),
                ft.Text(f"Opérateur: {page.display_name}", italic=True, color="grey"),
                ft.Divider(color="red"),
                ft.Column([
                    ft.ElevatedButton("INTERVENTION TECHNIQUE", icon=ft.icons.BUILD_CIRCLE, on_click=lambda _: ch_v("INTER"), width=350, height=55, bgcolor="blue900"),
                    ft.ElevatedButton("DEMANDE PIÈCE DE RECHANGE", icon=ft.icons.SHOPPING_CART, on_click=lambda _: ch_v("PART_REQ"), width=350, height=55, bgcolor="orange900"),
                    ft.ElevatedButton("GESTION STOCK (INVENTORY)", icon=ft.icons.INVENTORY, on_click=lambda _: ch_v("STOCK_MGR"), width=350, height=55, bgcolor="teal900"),
                    ft.ElevatedButton("HISTORIQUE DES RAPPORTS", icon=ft.icons.HISTORY, on_click=lambda _: ch_v("HISTORY"), width=350, height=55),
                    ft.ElevatedButton("TRACKING MOULES", icon=ft.icons.RECYCLING, on_click=lambda _: ch_v("MOLD"), width=350, height=55),
                    ft.ElevatedButton("CHECKS QUOTIDIENS / HEBDO", icon=ft.icons.CHECKLIST, on_click=lambda _: ch_v("ROUTINE"), width=350, height=55, bgcolor="green900"),
                ], horizontal_alignment="center", spacing=15),
                ft.Divider(), footer_tag
            )

        # --- SETTINGS / USER VIEW ---
        elif page.view == "USER":
            new_name = ft.TextField(label="Nouveau Nom d'affichage", value=page.display_name)
            new_pw = ft.TextField(label="Nouveau Mot de passe", password=True)
            
            def update_profile(e):
                supabase.table("users").update({"full_name": new_name.value, "password": new_pw.value}).eq("username", page.u_id).execute()
                page.display_name = new_name.value
                ch_v("HOME")

            page.add(
                ft.Row([ft.IconButton(ft.icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                ft.Text("PARAMÈTRES UTILISATEUR", weight="bold"),
                new_name, new_pw,
                ft.ElevatedButton("METTRE À JOUR", on_click=update_profile, bgcolor="blue"),
                ft.ElevatedButton("DÉCONNEXION", icon=ft.icons.LOGOUT, on_click=lambda _: (setattr(page, "logged_in", False), ch_v("LOGIN")), bgcolor="red900"),
                footer_tag
            )

        # --- PART REQUEST VIEW ---
        elif page.view == "PART_REQ":
            p_mach = ft.Dropdown(label="Machine Concernée", options=[ft.dropdown.Option(m) for m in MACHINES])
            p_name = ft.TextField(label="Nom de la pièce / Référence")
            p_qty = ft.TextField(label="Quantité", value="1", keyboard_type="number")
            p_urg = ft.Dropdown(label="Degré d'urgence", options=[ft.dropdown.Option("Normal"), ft.dropdown.Option("Urgent"), ft.dropdown.Option("Critique (Arrêt Machine)")])
            
            def save_part_req(e):
                img_url = upload_to_supabase(page.photo_part_path, "parts")
                supabase.table("part_requests").insert({
                    "machine": p_mach.value,
                    "piece_nom": p_name.value,
                    "qte": p_qty.value,
                    "urgence": p_urg.value,
                    "photo_path": img_url,
                    "dt": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "user": page.display_name
                }).execute()
                page.photo_part_path = ""
                ch_v("HOME")

            page.add(
                ft.Row([ft.IconButton(ft.icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                ft.Text("DEMANDE DE PIECE DE RECHANGE", weight="bold", color="orange"),
                p_mach, p_name, p_qty, p_urg,
                ft.ElevatedButton("PRENDRE PHOTO PIÈCE", icon=ft.icons.CAMERA_ALT, on_click=lambda _: (setattr(page, "current_upload_target", "PART"), file_picker.pick_files())),
                ft.ElevatedButton("ENVOYER LA DEMANDE", on_click=save_part_req, bgcolor="orange", width=350),
                ft.ElevatedButton("HISTORIQUE DEMANDES", icon=ft.icons.LIST_ALT, on_click=lambda _: ch_v("PART_HISTORY"), width=350),
                footer_tag
            )

        # --- PART HISTORY VIEW ---
        elif page.view == "PART_HISTORY":
            reqs = supabase.table("part_requests").select("*").order("id", desc=True).execute().data
            lv = ft.ListView(expand=True, spacing=10, height=500)
            
            for r in reqs:
                lv.controls.append(ft.Container(
                    content=ft.Column([
                        ft.Text(f"REF: PR-2026-{r['id']} | {r['piece_nom']}", weight="bold"),
                        ft.Text(f"Machine: {r['machine']} | Qte: {r['qte']} | Urgence: {r['urgence']}"),
                        ft.IconButton(ft.icons.PICTURE_AS_PDF, icon_color="orange", on_click=lambda e, row=r: export_part_pdf(row))
                    ]),
                    padding=10, border=ft.border.all(1, "orange"), border_radius=10
                ))
            
            page.add(ft.Row([ft.IconButton(ft.icons.ARROW_BACK, on_click=lambda _: ch_v("PART_REQ")), header_brand]), ft.Text("HISTORIQUE DES DEMANDES PIÈCES"), lv, footer_tag)

        # --- STOCK MANAGER VIEW ---
        elif page.view == "STOCK_MGR":
            def build_stock_list(search=""):
                stock_lv.controls.clear()
                query = supabase.table("inventory").select("*")
                if search: query = query.or_(f"designation.ilike.%{search}%,ref.ilike.%{search}%")
                items = query.execute().data
                
                for i in items:
                    is_low = i['stock_qty'] <= i['min_qty']
                    stock_lv.controls.append(ft.ListTile(
                        leading=ft.Icon(ft.icons.SETTINGS_SUGGEST, color="red" if is_low else "teal"),
                        title=ft.Text(f"{i['designation']} ({i['ref']})", weight="bold"),
                        subtitle=ft.Text(f"Emplacement: {i['location']} | Cat: {i['category']}"),
                        trailing=ft.Column([
                            ft.Text(f"Qté: {i['stock_qty']}", color="red" if is_low else "white", size=16, weight="bold"),
                            ft.Text("ALERTE" if is_low else "", color="red", size=10)
                        ], alignment="center"),
                        on_click=lambda e, item=i: open_stock_dialog(item)
                    ))
                page.update()

            def open_stock_dialog(item):
                qty_edit = ft.TextField(label="Ajuster Quantité (+/-)", value="0", width=100)
                
                def update_qty(e):
                    new_val = item['stock_qty'] + int(qty_edit.value)
                    supabase.table("inventory").update({"stock_qty": new_val}).eq("id", item['id']).execute()
                    supabase.table("inventory_logs").insert({
                        "part_id": item['id'], "action": "Manual Adjust", "qty": int(qty_edit.value), "machine": "N/A", "dt": datetime.now().strftime("%Y-%m-%d %H:%M")
                    }).execute()
                    dlg.open = False
                    build_stock_list()

                dlg = ft.AlertDialog(
                    title=ft.Text(f"Modifier {item['designation']}"),
                    content=ft.Column([ft.Text(f"Stock actuel: {item['stock_qty']}"), qty_edit], height=100),
                    actions=[ft.TextButton("Annuler", on_click=lambda _: (setattr(dlg, "open", False), page.update())), ft.ElevatedButton("Valider", on_click=update_qty)]
                )
                page.dialog = dlg; dlg.open = True; page.update()

            def open_add_part(e):
                r_f, d_f, c_f, q_f, m_f, l_f = ft.TextField(label="Référence"), ft.TextField(label="Désignation"), ft.TextField(label="Catégorie"), ft.TextField(label="Stock Initial", value="0"), ft.TextField(label="Stock Min", value="1"), ft.TextField(label="Emplacement")
                
                def save_new(e):
                    supabase.table("inventory").insert({
                        "ref": r_f.value, "designation": d_f.value, "category": c_f.value, "stock_qty": int(q_f.value), "min_qty": int(m_f.value), "location": l_f.value
                    }).execute()
                    add_dlg.open = False
                    build_stock_list()

                add_dlg = ft.AlertDialog(title=ft.Text("Nouvelle Pièce"), content=ft.Column([r_f, d_f, c_f, q_f, m_f, l_f], scroll="auto"), actions=[ft.ElevatedButton("Ajouter", on_click=save_new)])
                page.dialog = add_dlg; add_dlg.open = True; page.update()

            stock_lv = ft.ListView(expand=True, spacing=5, height=400)
            search_stock = ft.TextField(label="Chercher une pièce...", prefix_icon=ft.icons.SEARCH, on_change=lambda e: build_stock_list(e.control.value))
            
            page.add(
                ft.Row([ft.IconButton(ft.icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                ft.Row([ft.Text("GESTION DU STOCK PIÈCES", size=20, weight="bold"), ft.Icon(ft.icons.INVENTORY_2, color="teal")]),
                search_stock,
                ft.Row([ft.ElevatedButton("AJOUTER PIÈCE", icon=ft.icons.ADD, on_click=open_add_part, bgcolor="teal"), ft.ElevatedButton("EXPORT EXCEL", icon=ft.icons.FILE_DOWNLOAD, on_click=export_inventory_excel, bgcolor="green700")]),
                stock_lv, footer_tag
            )
            build_stock_list()

        # --- ROUTINE CHECK VIEW ---
        elif page.view == "ROUTINE":
            m_dd = ft.Dropdown(label="Machine", options=[ft.dropdown.Option(m) for m in MACHINES])
            c_grease, c_oil, c_elec, c_sec = ft.Checkbox(label="Graissage"), ft.Checkbox(label="Huilage"), ft.Checkbox(label="Serrage élec"), ft.Checkbox(label="Sécurité")
            dur_in = ft.TextField(label="Temps passé (Minutes)", keyboard_type="number")
            
            def save_r(e):
                supabase.table("routines").insert({
                    "machine": m_dd.value, "freq": "Daily", "graissage": str(c_grease.value), "huilage": str(c_oil.value), "serrage": str(c_elec.value), "securite": str(c_sec.value),
                    "duree": dur_in.value, "dt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user": page.display_name
                }).execute()
                ch_v("HOME")

            page.add(
                ft.Row([ft.IconButton(ft.icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                ft.Text("CHECK QUOTIDIEN", weight="bold"),
                m_dd, c_grease, c_oil, c_elec, c_sec, dur_in,
                ft.ElevatedButton("SAUVEGARDER", on_click=save_r, bgcolor="green", width=350),
                ft.Row([ft.ElevatedButton("HISTORIQUE", icon=ft.icons.HISTORY, on_click=lambda _: ch_v("ROUTINE_HISTORY")), ft.ElevatedButton("RAPPORT HEBDO (PDF)", icon=ft.icons.SUMMARIZE, on_click=generate_weekly_pdf, bgcolor="blue900")]),
                footer_tag
            )

        # --- ROUTINE HISTORY VIEW ---
        elif page.view == "ROUTINE_HISTORY":
            rows = supabase.table("routines").select("*").order("id", desc=True).execute().data
            lv = ft.ListView(expand=True, height=500)
            for r in rows:
                lv.controls.append(ft.Container(
                    content=ft.Column([
                        ft.Text(f"{r['dt']} - {r['machine']}", weight="bold"),
                        ft.Text(f"Par: {r['user']} | Durée: {r['duree']} min"),
                        ft.Text(f"Checklist: G:{r['graissage']} H:{r['huilage']} S:{r['serrage']} Sec:{r['securite']}", size=12)
                    ]),
                    padding=10, border=ft.border.all(1, "grey700"), border_radius=10
                ))
            page.add(ft.Row([ft.IconButton(ft.icons.ARROW_BACK, on_click=lambda _: ch_v("ROUTINE")), header_brand]), ft.Text("HISTORIQUE DES INSPECTIONS", weight="bold"), ft.ElevatedButton("EXPORTER EXCEL", icon=ft.icons.FILE_DOWNLOAD, on_click=export_routines_excel, bgcolor="green700"), lv, footer_tag)

        # --- INTERVENTION REPORT VIEW ---
        elif page.view == "INTER":
            dem = ft.TextField(label="Demandeur", value="Production")
            mold_ref_field = ft.TextField(label="Référence du Moule", visible=False)
            
            def on_sys_change(e):
                mold_ref_field.visible = (sys_dd.value == "Moule")
                page.update()

            sys_dd = ft.Dropdown(label="Machine / Système", options=[ft.dropdown.Option(m) for m in MACHINES], on_change=on_sys_change)
            s_ens = ft.TextField(label="Sous-Ensemble")
            m_type = ft.Dropdown(label="Type Maintenance", options=[ft.dropdown.Option("Corrective"), ft.dropdown.Option("Préventive")])
            piec = ft.TextField(label="Pièces de rechange")
            spare_price_in = ft.TextField(label="Coût Total (DZD)", keyboard_type="number", value="0")
            
            error_other_desc = ft.TextField(label="Précisez", visible=False)
            def on_source_change(e):
                error_other_desc.visible = (error_source.value == "Autre")
                page.update()

            error_source = ft.Dropdown(label="Source de l'erreur", options=[ft.dropdown.Option("Opérateur"), ft.dropdown.Option("Technique"), ft.dropdown.Option("Autre")], on_change=on_source_change)
            err_desc = ft.TextField(label="Désignation de l'Erreur", multiline=True, expand=True)
            sol_desc = ft.TextField(label="Désignation de la Solution", multiline=True, expand=True)
            
            def pick_img(target):
                page.current_upload_target = target
                file_picker.pick_files()

            def save_i(e):
                # Auto-destock if part name matches
                if piec.value:
                    part_res = supabase.table("inventory").select("id, stock_qty").eq("designation", piec.value).execute()
                    if part_res.data:
                        new_stock = part_res.data[0]['stock_qty'] - 1
                        supabase.table("inventory").update({"stock_qty": new_stock}).eq("id", part_res.data[0]['id']).execute()

                final_err_img_url = upload_to_supabase(page.photo_err_path, "errors")
                final_sol_img_url = upload_to_supabase(page.photo_sol_path, "solutions")

                supabase.table("inters").insert({
                    "demandeur": dem.value, "intervenant": page.display_name, "date": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                    "systeme": sys_dd.value, "sous_ens": s_ens.value, "error_desc": err_desc.value, "solution_desc": sol_desc.value,
                    "pieces": piec.value, "type_m": m_type.value, "photo_err": final_err_img_url, "photo_sol": final_sol_img_url,
                    "error_source": error_source.value, "error_other": error_other_desc.value, "user": page.display_name,
                    "mold_ref": mold_ref_field.value, "spare_price": spare_price_in.value
                }).execute()
                
                page.photo_err_path = ""
                page.photo_sol_path = ""
                ch_v("HOME")

            page.add(
                ft.Row([ft.IconButton(ft.icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                ft.Text("NOUVEAU RAPPORT D'INTERVENTION", weight="bold"),
                dem, sys_dd, mold_ref_field, s_ens, m_type, error_source, error_other_desc,
                ft.Row([err_desc, ft.IconButton(ft.icons.CAMERA_ALT, on_click=lambda _: pick_img("ERR"), icon_color="red")]),
                ft.Row([sol_desc, ft.IconButton(ft.icons.CAMERA_ALT, on_click=lambda _: pick_img("SOL"), icon_color="green")]),
                piec, spare_price_in,
                ft.ElevatedButton("ENREGISTRER LE RAPPORT", on_click=save_i, bgcolor="blue", width=350),
                footer_tag
            )

        # --- HISTORY VIEW ---
        elif page.view == "HISTORY":
            lv = ft.ListView(expand=True, spacing=10, height=500)
            
            def build_history(search_term=""):
                lv.controls.clear()
                query = supabase.table("inters").select("*")
                if search_term: query = query.or_(f"systeme.ilike.%{search_term}%,user.ilike.%{search_term}%")
                reports = query.order("id", desc=True).execute().data
                
                for r in reports:
                    lv.controls.append(ft.Container(
                        content=ft.Column([
                            ft.Row([ft.Text(f"REF: INT-2026-{r['id']} | {r['systeme']}", weight="bold"), ft.Text(f"par {r['user']}", size=10)]),
                            ft.Text(f"Date: {r['date']}"),
                            ft.Row([ft.IconButton(ft.icons.PICTURE_AS_PDF, icon_color="red", on_click=lambda e, row=r: export_pdf(row))])
                        ]),
                        padding=10, border=ft.border.all(1, "grey700"), border_radius=10
                    ))
                page.update()

            search_bar = ft.TextField(label="Chercher par machine ou utilisateur...", prefix_icon=ft.icons.SEARCH, on_change=lambda e: build_history(e.control.value))
            page.add(ft.Row([ft.IconButton(ft.icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]), ft.Text("HISTORIQUE DES INTERVENTIONS", size=20, weight="bold"), search_bar, ft.ElevatedButton("EXPORTER TOUT (EXCEL)", icon=ft.icons.TABLE_CHART, on_click=export_excel, width=350), lv, footer_tag)
            build_history()

        # --- MOLD TRACKING VIEW ---
        elif page.view == "MOLD":
            p_dd = ft.Dropdown(label="Presse", options=[ft.dropdown.Option(f"Presse {i+1}") for i in range(11)])
            o_m = ft.TextField(label="Moule Sortant", read_only=True)
            n_m = ft.TextField(label="Nouveau Moule à monter")
            
            def on_p_change(e):
                res = supabase.table("molds").select("new_m").eq("p_no", p_dd.value).order("id", desc=True).limit(1).execute()
                o_m.value = res.data[0]['new_m'] if res.data else "Vide"
                page.update()

            p_dd.on_change = on_p_change

            def save_m(e):
                supabase.table("molds").insert({
                    "p_no": p_dd.value, "old_m": o_m.value, "new_m": n_m.value, "dt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user": page.display_name
                }).execute()
                ch_v("HOME")

            page.add(
                ft.Row([ft.IconButton(ft.icons.ARROW_BACK, on_click=lambda _: ch_v("HOME")), header_brand]),
                ft.Text("CHANGEMENT ET TRACKING MOULE", weight="bold"),
                p_dd, o_m, n_m,
                ft.ElevatedButton("VALIDER LE CHANGEMENT", on_click=save_m, width=350),
                ft.ElevatedButton("VOIR HISTORIQUE MOULES", icon=ft.icons.HISTORY, on_click=lambda _: ch_v("MOLD_HISTORY"), width=350, bgcolor="blue900"),
                ft.ElevatedButton("EXPORTER MOULES (EXCEL)", icon=ft.icons.TABLE_CHART, on_click=export_molds_excel, width=350, bgcolor="green700"),
                footer_tag
            )

        elif page.view == "MOLD_HISTORY":
            m_reports = supabase.table("molds").select("*").order("id", desc=True).execute().data
            lv = ft.ListView(expand=True, spacing=10, height=500)
            for r in m_reports:
                lv.controls.append(ft.Container(
                    content=ft.Column([
                        ft.Row([ft.Text(f"{r['dt']} - {r['p_no']}", weight="bold"), ft.Text(f"par {r['user']}", size=10)]),
                        ft.Row([ft.Text(f"Sortant: {r['old_m']}   ➔   Nouveau: {r['new_m']}", color="amber")])
                    ]),
                    padding=10, border=ft.border.all(1, "grey700"), border_radius=10
                ))
            page.add(ft.Row([ft.IconButton(ft.icons.ARROW_BACK, on_click=lambda _: ch_v("MOLD")), header_brand]), ft.Text("HISTORIQUE DES CHANGEMENTS MOULES", weight="bold"), lv, footer_tag)

        page.update()

    # --- SHARED NAVIGATION ---
    def ch_v(v): 
        page.view = v
        refresh()

    # --- EXPORT LOGIC ---
    def export_routines_excel(e=None):
        data = supabase.table("routines").select("*").execute().data
        df = pd.DataFrame(data)
        base_name = f"Daily_Inspections_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        filename = os.path.join(tempfile.gettempdir(), base_name)
        df.to_excel(filename, index=False)
        page.snack_bar = ft.SnackBar(ft.Text(f"Exporté : {base_name}"))
        page.snack_bar.open = True
        page.update()
    
    def export_excel(e=None):
        data = supabase.table("inters").select("*").execute().data
        df = pd.DataFrame(data)
        base_name = f"Rapports_Global_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        filename = os.path.join(tempfile.gettempdir(), base_name)
        df.to_excel(filename, index=False)
        page.snack_bar = ft.SnackBar(ft.Text(f"Excel exporté : {base_name}"))
        page.snack_bar.open = True
        page.update()

    def export_molds_excel(e=None):
        data = supabase.table("molds").select("*").execute().data
        df = pd.DataFrame(data)
        base_name = f"Tracking_Moules_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        filename = os.path.join(tempfile.gettempdir(), base_name)
        df.to_excel(filename, index=False)
        page.snack_bar = ft.SnackBar(ft.Text(f"Excel exporté : {base_name}"))
        page.snack_bar.open = True
        page.update()

    def export_inventory_excel(e=None):
        data = supabase.table("inventory").select("*").execute().data
        df = pd.DataFrame(data)
        base_name = f"Stock_Inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        filename = os.path.join(tempfile.gettempdir(), base_name)
        df.to_excel(filename, index=False)
        page.snack_bar = ft.SnackBar(ft.Text(f"Inventaire exporté : {base_name}"))
        page.snack_bar.open = True
        page.update()

    # --- PDF GENERATION LOGIC ---
    def generate_weekly_pdf(e=None):
        try:
            last_week = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            data = supabase.table("routines").select("*").gte("dt", last_week).execute().data
            
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", 'B', 16)
            pdf.cell(190, 10, "RAPPORT DE MAINTENANCE HEBDOMADAIRE", ln=True, align='C')
            pdf.set_font("Arial", '', 10)
            
            for r in data:
                pdf.cell(190, 8, f"{r['dt']} - {r['machine']} - par {r['user']}", ln=True)
                pdf.cell(190, 6, f"Grease: {r['graissage']} | Oil: {r['huilage']} | Elec: {r['serrage']} | Sec: {r['securite']}", ln=True)
                pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            
            base_name = f"Rapport_Hebdo_{datetime.now().strftime('%Y%W')}.pdf"
            fname = os.path.join(tempfile.gettempdir(), base_name)
            pdf.output(fname)
            page.snack_bar = ft.SnackBar(ft.Text(f"PDF Hebdomadaire créé : {base_name}"))
            page.snack_bar.open = True
            page.update()
        except Exception as ex:
            page.snack_bar = ft.SnackBar(ft.Text(f"Erreur PDF : {ex}"))
            page.snack_bar.open = True
            page.update()

    def export_pdf(row):
        pdf = FPDF()
        pdf.add_page()
        
        # Header
        pdf.set_font("Arial", 'B', 22)
        pdf.cell(190, 10, "BRIKS BY OKBA", ln=True, align='C')
        pdf.set_font("Arial", 'I', 10)
        pdf.cell(190, 10, "SERVICE MAINTENANCE - RAPPORT TECHNIQUE", ln=True, align='C')
        pdf.ln(5)
        
        # Table Info
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(190, 10, f"INTERVENTION ID: {row.get('id', 'N/A')}", border=1, ln=True)
        pdf.set_font("Arial", '', 11)
        pdf.cell(95, 10, f"Machine: {row.get('systeme', '')}", border=1)
        pdf.cell(95, 10, f"Date: {row.get('date', '')}", border=1, ln=True)
        pdf.cell(95, 10, f"Intervenant: {row.get('intervenant', '')}", border=1)
        pdf.cell(95, 10, f"Demandeur: {row.get('demandeur', '')}", border=1, ln=True)
        
        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(190, 10, "DESCRIPTION DE L'ERREUR:", ln=True)
        pdf.set_font("Arial", '', 11)
        pdf.multi_cell(190, 8, row.get('error_desc', ''))
        
        # Photos from Supabase URLs
        if row.get('photo_err') and row.get('photo_err').startswith("http"):
            try:
                temp_err = os.path.join(tempfile.gettempdir(), f"temp_err_{os.urandom(4).hex()}.jpg")
                urllib.request.urlretrieve(row['photo_err'], temp_err)
                pdf.image(temp_err, x=10, y=pdf.get_y() + 5, w=80)
                os.remove(temp_err)
                pdf.ln(60)
            except Exception as e: print(f"Image error: {e}")

        pdf.ln(5)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(190, 10, "SOLUTION APPLIQUEE:", ln=True)
        pdf.set_font("Arial", '', 11)
        pdf.multi_cell(190, 8, row.get('solution_desc', ''))
        
        if row.get('photo_sol') and row.get('photo_sol').startswith("http"):
            try:
                temp_sol = os.path.join(tempfile.gettempdir(), f"temp_sol_{os.urandom(4).hex()}.jpg")
                urllib.request.urlretrieve(row['photo_sol'], temp_sol)
                pdf.image(temp_sol, x=10, y=pdf.get_y() + 5, w=80)
                os.remove(temp_sol)
                pdf.ln(60)
            except Exception as e: print(f"Image error: {e}")

        pdf.ln(10)
        pdf.cell(190, 10, "SIGNATURE TECHNIQUE", ln=True, align='R')
        
        base_name = f"Rapport_{row.get('id', 'N')}.pdf"
        fname = os.path.join(tempfile.gettempdir(), base_name)
        pdf.output(fname)
        
        page.snack_bar = ft.SnackBar(ft.Text(f"PDF généré : {base_name}"))
        page.snack_bar.open = True
        page.update()

    def export_part_pdf(row):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 18)
        pdf.cell(190, 10, "DEMANDE DE PIECE DE RECHANGE", ln=True, align='C')
        pdf.ln(10)
        pdf.set_font("Arial", '', 12)
        pdf.cell(190, 8, f"Date: {row.get('dt', '')}", ln=True)
        pdf.cell(190, 8, f"Demandeur: {row.get('user', '')}", ln=True)
        pdf.cell(190, 8, f"Piece: {row.get('piece_nom', '')}", ln=True)
        pdf.cell(190, 8, f"Machine: {row.get('machine', '')}", ln=True)
        pdf.cell(190, 8, f"Quantite: {row.get('qte', '')}", ln=True)
        pdf.cell(190, 8, f"Urgence: {row.get('urgence', '')}", ln=True)
        
        if row.get('photo_path') and row.get('photo_path').startswith("http"):
            try:
                temp_img = os.path.join(tempfile.gettempdir(), f"temp_part_{os.urandom(4).hex()}.jpg")
                urllib.request.urlretrieve(row['photo_path'], temp_img)
                pdf.image(temp_img, x=10, y=pdf.get_y() + 10, w=100)
                os.remove(temp_img)
            except Exception as e:
                print(f"Erreur d'image pièce: {e}")
        
        base_name = f"Demande_Piece_{row.get('id', 'N')}.pdf"
        fname = os.path.join(tempfile.gettempdir(), base_name)
        pdf.output(fname)
        
        page.snack_bar = ft.SnackBar(ft.Text(f"PDF généré : {base_name}"))
        page.snack_bar.open = True
        page.update()

    refresh()

ft.app(target=main)
