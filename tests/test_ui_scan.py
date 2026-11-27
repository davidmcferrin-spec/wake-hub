from wakehub.inventory import ui_setup


def test_scan_field_stays_on_the_scan_page(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("#page-title")
        page.click("aside button[data-page=scan]")
        page.wait_for_function("document.querySelector('#page-title').textContent === 'Scan'")
        page.click("#cidr")
        page.fill("#cidr", "10.4.0.0/24")
        assert page.inner_text("#page-title") == "Scan"
        assert page.input_value("#cidr") == "10.4.0.0/24"
        browser.close()
