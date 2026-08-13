from tests.conftest import TEST_ADMIN_PASSWORD


def _print_one(client, url="https://example.com/article"):
    return client.post("/print", data={"url": url}, follow_redirects=False)


# --- login / logout -------------------------------------------------------


def test_admin_login_page(anon_client):
    resp = anon_client.get("/admin/login")
    assert resp.status_code == 200
    assert "Admin login" in resp.text
    assert 'name="password"' in resp.text


def test_admin_login_redirects_when_already_logged_in(admin_client):
    resp = admin_client.get("/admin/login", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pretty-print/admin"


def test_admin_login_wrong_password(anon_client):
    resp = anon_client.post(
        "/admin/login", data={"password": "wrong"}, follow_redirects=False
    )
    assert resp.status_code == 401
    assert "Wrong password" in resp.text


def test_admin_login_correct_password(anon_client):
    resp = anon_client.post(
        "/admin/login",
        data={"password": TEST_ADMIN_PASSWORD},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pretty-print/admin"


def test_admin_logout(admin_client):
    resp = admin_client.post("/admin/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pretty-print/admin/login"
    # Session cleared: /admin now bounces back to login.
    resp = admin_client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pretty-print/admin/login"


# --- access control -------------------------------------------------------


def test_admin_page_requires_login(anon_client):
    resp = anon_client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pretty-print/admin/login"


def test_admin_page_renders(admin_client, fake_fetcher):
    fake_fetcher()
    _print_one(admin_client)
    resp = admin_client.get("/admin")
    assert resp.status_code == 200
    assert "Delete from history" in resp.text
    assert "Example Article" in resp.text


def test_admin_delete_requires_login(anon_client, fake_fetcher):
    fake_fetcher()
    _print_one(anon_client)
    resp = anon_client.post("/admin/delete/1", follow_redirects=False)
    assert resp.status_code == 401


# --- delete ---------------------------------------------------------------


def test_admin_delete_removes_document(admin_client, fake_fetcher):
    fake_fetcher()
    _print_one(admin_client)
    assert admin_client.get("/d/1").status_code == 200

    resp = admin_client.post("/admin/delete/1", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pretty-print/admin?deleted=1"

    # Gone from the print view and from public history.
    assert admin_client.get("/d/1").status_code == 404
    assert "Example Article" not in admin_client.get("/history").text


def test_admin_delete_missing_doc_is_harmless(admin_client):
    resp = admin_client.post("/admin/delete/999", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pretty-print/admin?deleted=0"


def test_admin_delete_keeps_other_docs(admin_client, fake_fetcher):
    fake_fetcher()
    _print_one(admin_client, "https://example.com/one")
    _print_one(admin_client, "https://example.com/two")
    admin_client.post("/admin/delete/1", follow_redirects=False)
    assert admin_client.get("/d/2").status_code == 200
