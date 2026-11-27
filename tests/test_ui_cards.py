import httpx

from wakehub.inventory import ui_setup


def test_device_cards_keep_their_content_inside(live_server, hub):
    from playwright.sync_api import sync_playwright

    ui_setup(hub, hub.token, "correct horse", client="browser")
    headers = {"Authorization": f"Bearer {hub.token}"}
    office = httpx.post(
        f"{live_server}/api/v1/devices",
        headers=headers,
        json={"name": "UNRAID", "mac": "02:00:00:00:00:41", "host": "10.9.5.1"},
    ).json()
    httpx.post(
        f"{live_server}/api/v1/amt",
        headers=headers,
        json={"name": "UNRAID vPro", "host": "10.9.5.3", "password": "secret-amt", "device_id": office["id"]},
    )
    pdu = httpx.post(f"{live_server}/api/v1/pdus", headers=headers, json={"name": "NP-1601DU", "host": "192.168.0.8"}).json()
    for number, name in enumerate(
        ("Attic POE", "HDMI Streaming", "Home PC", "Internet Fiber Jack", "Network Gear", "Work HP", "Work Peplink"),
        start=1,
    ):
        hub.write(
            "INSERT INTO pdu_outlets (pdu_id, number, name, tags) VALUES (?, ?, ?, '[]')",
            (pdu["id"], number, name),
        )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1024, "height": 900})
        page.goto(live_server + "/")
        page.fill("#ui-password", "correct horse")
        page.click("button[data-cap=ui_login]")
        page.wait_for_selector("article.card")
        card = page.locator("article.card", has_text="NP-1601DU")
        card.locator("summary", has_text="Outlets").click()
        page.wait_for_selector("article.card .outlet-line")
        assert card.locator("text=Save tags").count() == 0
        assert card.locator(".outlet-tags").count() == 0
        page.evaluate("() => { document.querySelector('#device-grid').dataset.mark = 'stay'; }")
        page.evaluate("() => window.pollStatus()")
        page.wait_for_function("() => document.querySelector('#device-grid').dataset.mark === 'stay'")
        assert page.locator("details.outlets").first.get_attribute("open") is not None
        stored = page.evaluate("() => localStorage.getItem('wakehub.outlets')")
        assert stored and "1" in stored
        page.reload()
        page.wait_for_selector("article.card .outlet-line")
        assert page.locator("details.outlets").first.get_attribute("open") is not None

        def overflows(width):
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_selector("article.card .outlet-ops button")
            return page.evaluate(
                """() => {
                  const bad = [];
                  for (const card of document.querySelectorAll("article.card")) {
                    const box = card.getBoundingClientRect();
                    if (box.width < 1) continue;
                    if (box.right > window.innerWidth + 1 || box.left < -1) {
                      bad.push({ kind: "card", text: card.innerText.slice(0, 40), right: box.right, width: window.innerWidth });
                    }
                    for (const child of card.querySelectorAll("*")) {
                      if (child.closest(".menu")) continue;
                      const style = getComputedStyle(child);
                      if (style.display === "none" || style.visibility === "hidden") continue;
                      const rect = child.getBoundingClientRect();
                      if (rect.width < 1 || rect.height < 1) continue;
                      const past = rect.right > box.right + 1 || rect.left < box.left - 1 || rect.bottom > box.bottom + 1 || rect.top < box.top - 1;
                      if (past) bad.push({ kind: "child", text: (child.innerText || "").slice(0, 40), right: rect.right, cardRight: box.right });
                    }
                  }
                  return bad;
                }"""
            )

        for width in (360, 768, 1024, 1280):
            spilled = overflows(width)
            assert spilled == [], (width, spilled)
        card.locator(".more-toggle").click()
        card.get_by_role("button", name="Edit").click()
        page.wait_for_selector("form.hardware-edit [data-outlet-tag]")
        assert page.get_by_role("button", name="Save tags").count() >= 1
        assert page.locator("form.hardware-edit .name-error").count() == 1
        browser.close()
