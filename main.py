import flet as ft

def main(page: ft.Page):
    page.title = "Briks Test App"
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    # Simple Permission Checker
    ph = ft.PermissionHandler()
    page.overlay.append(ph)

    def check_perm(e):
        ph.request_permission(ft.PermissionType.STORAGE)
        page.update()

    page.add(
        ft.Text("✅ IF YOU SEE THIS, FLET IS WORKING!", size=20, weight="bold", color="green"),
        ft.ElevatedButton("Test Permissions Popup", on_click=check_perm),
        ft.Text("Version: 2.0.2", size=12, color="grey")
    )

ft.app(target=main)
