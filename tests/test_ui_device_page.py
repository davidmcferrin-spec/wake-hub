import httpx

from wakehub.crypto import decrypt
from wakehub.inventory import ui_setup


def _card(page, name):
    return page.locator("article").filter(has=page.get_by_role("heading", name=name, exact=True))


def test_open_shows_the_device_page_and_edit_saves_the_amt(live_server, hub, monkeypatch):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    base = live_server + "/api/v1"
    device = httpx.post(
        f"{base}/devices",
        headers=headers,
        json={"name": "Office PC", "mac": "02:00:00:00:00:77", "host": "10.4.0.77"},
    ).json()
    amt = httpx.post(
        f"{base}/amt",
        headers=headers,
        json={"name": "Office AMT", "host": "10.4.0.78", "password": "secret-amt", "device_id": device["id"]},
    ).json()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#device-search")
        card = _card(page, "Office PC")
        card.locator("button.name-button").click()
        page.wait_for_function("location.hash.indexOf('#/devices/') === 0")
        assert page.locator("#device-form").count() == 0
        assert "Methods" in page.inner_text("article.detail")
        page.click("#back-inventory")
        page.wait_for_selector("#device-search")
        card = _card(page, "Office PC")
        card.locator("summary", has_text="More").click()
        card.get_by_role("button", name="Open", exact=True).click()
        page.wait_for_function("location.hash.indexOf('#/devices/') === 0")
        assert page.locator("#device-form").count() == 0
        page.get_by_role("button", name="Edit", exact=True).click()
        page.wait_for_selector("#device-form")
        assert page.locator("article.detail").count() == 0
        page.locator("details.method-row[data-kind=amt] > summary").click()
        page.fill("details.method-row[data-kind=amt] [name=method_host]", "10.9.9.99")
        page.fill("details.method-row[data-kind=amt] [name=method_password]", "new-secret")
        page.fill("#reach_timeout", "12")
        with page.expect_response(lambda response: response.request.method == "PATCH" and "/devices/" in response.url) as first_save:
            page.click("#device-form button[type=submit]")
        assert first_save.value.ok
        saved = next(item for item in httpx.get(f"{base}/amt", headers=headers).json() if item["id"] == amt["id"])
        assert saved["host"] == "10.9.9.99"
        assert decrypt(hub.cipher, hub.query_one("SELECT password_enc FROM amt_endpoints WHERE id = ?", (amt["id"],))["password_enc"]) == "new-secret"
        assert httpx.get(f"{base}/devices/{device['id']}", headers=headers).json()["reach_timeout"] == 12
        card = _card(page, "Office PC")
        card.locator("summary", has_text="More").click()
        card.get_by_role("button", name="Edit").click()
        page.wait_for_selector("#device-form")
        page.fill("#reach_timeout", "")
        with page.expect_response(lambda response: response.request.method == "PATCH" and "/devices/" in response.url) as second_save:
            page.click("#device-form button[type=submit]")
        assert second_save.value.ok
        assert httpx.get(f"{base}/devices/{device['id']}", headers=headers).json()["reach_timeout"] is None
        browser.close()

    seen = []

    class Capture:
        def __init__(self, host, username, password, *, port=16992, use_tls=False, insecure_tls=False, timeout=15, poster=None):
            seen.append((host, password))

        def request_power(self, action):
            return {"action": action, "ok": True}

    monkeypatch.setattr("wakehub.endpoints.AmtClient", Capture)
    powered = httpx.post(f"{base}/devices/{device['id']}/power", headers=headers, json={"action": "on", "method": "amt"})
    assert powered.status_code == 200, powered.text
    assert seen == [("10.9.9.99", "new-secret")]
