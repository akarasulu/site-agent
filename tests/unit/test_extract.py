from site_agent.core.extract.html import extract_interactions


def test_extracts_forms_fields_and_transitions():
    html = """
    <html><head><title>Settings</title></head><body>
      <h1>Network Settings</h1>
      <form action="/save" method="post">
        <label>SSID</label><input name="ssid" placeholder="WiFi name">
        <input type="password" aria-label="Admin password">
        <button type="submit">Save</button>
      </form>
      <a href="/status">Status</a>
    </body></html>
    """
    page, forms, elements, transitions, evidence = extract_interactions(html, "https://example.com/settings")

    assert page.title == "Settings"
    assert page.headings == ["Network Settings"]
    assert len(forms) == 1
    assert len(elements) == 3
    assert [element.label for element in elements] == ["SSID", "Admin password", "Save"]
    assert transitions[0].target_url == "https://example.com/status"
    assert evidence
