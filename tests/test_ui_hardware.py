import httpx

from wakehub.inventory import ui_setup


def _create(live_server, hub, path, body):
    response = httpx.post(
        f"{live_server}{path}",
        json=body,
        headers={"Authorization": f"Bearer {hub.token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_editing_each_hardware_type_stays_put_and_saves(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    created = [
        ("PDU one", "PDU renamed", _create(live_server, hub, "/api/v1/pdus", {"name": "PDU one", "host": "10.9.0.1", "port": 80})),
        ("AMT one", "AMT renamed", _create(live_server, hub, "/api/v1/amt", {"name": "AMT one", "host": "10.9.0.2", "password": "secret"})),
        ("Jet one", "Jet renamed", _create(live_server, hub, "/api/v1/jetkvm", {"name": "Jet one", "host": "10.9.0.3"})),
        ("Plug one", "Plug renamed", _create(live_server, hub, "/api/v1/plugs", {"name": "Plug one", "host": "10.9.0.4", "kind": "shelly"})),
        ("UPS one", "UPS renamed", _create(live_server, hub, "/api/v1/ups", {"name": "UPS one", "host": "10.9.0.5"})),
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#page-title")
        page.click("aside button[data-page=power]")
        page.wait_for_function("document.querySelector('#page-title').textContent === 'Hardware'")
        page.click("button[data-add-form=pdu-form]")
        page.click("#pdu-form input[name=name]")
        assert page.inner_text("#page-title") == "Hardware"
        for original, renamed, _row in created:
            card = page.locator("article.card", has_text=original)
            card.locator(".more-toggle").click()
            card.get_by_role("button", name="Edit", exact=True).click()
            form = page.locator("form.hardware-edit")
            form.wait_for()
            assert form.locator("input[name=name]").input_value() == original
            assert form.locator("input[name=host]").input_value()
            secret = form.locator("input[placeholder=unchanged]").first
            assert secret.input_value() == ""
            html = form.inner_html()
            assert html.find('name="name"') < html.find('name="host"') < html.find('name="port"')
            assert "pair" in html
            form.locator("input[name=name]").click()
            assert page.inner_text("#page-title") == "Hardware"
            form.locator("input[name=name]").fill(renamed)
            page.keyboard.press("Tab")
            page.eval_on_selector("#banner", "node => node.classList.add('hidden')")
            form.locator("[data-save]").click()
            page.wait_for_selector("#banner:not(.hidden)")
            assert page.inner_text("#banner") == "Saved", page.inner_text("#banner")
            assert page.inner_text("#page-title") == "Hardware"
            page.locator("article.card", has_text=renamed).first.wait_for()
        page.click("article.card:has-text('PDU renamed') button:has-text('Refresh names from device')")
        page.wait_for_selector("#banner.error")
        assert "did not return outlet names" in page.inner_text("#banner")
        assert page.inner_text("#page-title") == "Hardware"
        page.click("aside button[data-page=devices]")
        page.wait_for_function("document.querySelector('#page-title').textContent === 'Devices'")
        for _original, renamed, _row in created:
            assert renamed in page.inner_text("#view")
        page.select_option("#kind-filter", "pdu")
        assert "PDU renamed" in page.inner_text("#view")
        assert "AMT renamed" not in page.inner_text("#view")
        renamed = page.locator("article.card", has_text="PDU renamed")
        renamed.locator(".more-toggle").click()
        renamed.get_by_role("button", name="Edit").click()
        page.wait_for_selector("form.hardware-edit")
        assert page.inner_text("#page-title") == "PDU renamed"
        assert page.get_by_role("button", name="Re-read from device").count() >= 1
        page.click("#back-inventory")
        page.wait_for_function("document.querySelector('#page-title').textContent === 'Devices'")
        browser.close()
