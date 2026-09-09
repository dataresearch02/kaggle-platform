c = get_config()  # noqa: F821
# Only the same-origin Arena parent may frame the notebook UI.
c.ServerApp.tornado_settings = {
    "headers": {"Content-Security-Policy": "frame-ancestors 'self'"}
}
c.ServerApp.root_dir = "/home/jovyan/work"
c.ServerApp.open_browser = False

# Enables the same-origin Arena toolbar to use the public JupyterLab command API.
c.LabApp.expose_app_in_browser = True
