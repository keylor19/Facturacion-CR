"""El panel web se sirve con cabeceras de seguridad."""


def test_panel_se_sirve_con_csp(app_client):
    r = app_client.get("/panel/")
    assert r.status_code == 200
    assert 'id="app"' in r.text
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-inline" not in csp
    assert r.headers["x-frame-options"] == "DENY"


def test_raiz_redirige_al_panel(app_client):
    r = app_client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/panel/"


def test_archivos_del_panel(app_client):
    for ruta in ("js/app.js", "js/api.js", "js/dom.js", "js/vistas/emitir.js", "css/app.css"):
        assert app_client.get(f"/panel/{ruta}").status_code == 200, ruta


def test_api_no_se_cachea(app_client):
    assert app_client.get("/api/v1/health").headers["cache-control"] == "no-store"
