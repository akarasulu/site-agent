from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


BASE_URL = os.environ.get("SITE_AGENT_ROUTER_BASE_URL", "https://192.168.1.1")
MODE = os.environ.get("SITE_AGENT_ROUTER_LIVE_MODE", "plan")
USER = os.environ.get("SITE_AGENT_ROUTER_USER", "admin")
PASSWORD = os.environ["SITE_AGENT_ROUTER_PASSWORD"]
RULE_NAME = os.environ.get("SITE_AGENT_ROUTER_TEST_NAME", "SA12121")
TARGET_IP = os.environ.get("SITE_AGENT_ROUTER_TEST_IP", "192.168.1.254")
PORT = os.environ.get("SITE_AGENT_ROUTER_TEST_PORT", "12121")
PROTOCOL = os.environ.get("SITE_AGENT_ROUTER_TEST_PROTOCOL", "TCP")
ARTIFACT_DIR = Path(os.environ.get("SITE_AGENT_ROUTER_LIVE_ARTIFACT_DIR", "/tmp/site-agent-router-live-write"))


@dataclass
class MatchResult:
    label: str
    matched: bool


def log(message: str) -> None:
    print(message, flush=True)


def pause(message: str) -> None:
    log("")
    log(message)
    if os.environ.get("SITE_AGENT_ROUTER_NO_PAUSE") == "1":
        log("Pause skipped because SITE_AGENT_ROUTER_NO_PAUSE=1.")
        return
    input("Press Enter to continue...")


def require_user_confirmation(message: str, expected: str = "yes") -> None:
    log("")
    log(message)
    if os.environ.get("SITE_AGENT_ROUTER_NO_PAUSE") == "1":
        log("Confirmation skipped because SITE_AGENT_ROUTER_NO_PAUSE=1.")
        return
    answer = input(f"Type {expected!r} to continue: ").strip()
    if answer != expected:
        raise RuntimeError(f"User confirmation failed; expected {expected!r}.")


def save_artifacts(page: Page, name: str) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ARTIFACT_DIR / f"{name}.png"), full_page=True)
    (ARTIFACT_DIR / f"{name}.html").write_text(page.content(), encoding="utf-8", errors="replace")


def first_visible(page: Page, selectors: list[str], timeout: int = 700) -> str | None:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout)
            return selector
        except PlaywrightTimeoutError:
            continue
    return None


def click_text(page: Page, labels: list[str], timeout: int = 1200) -> MatchResult:
    for label in labels:
        patterns = [
            page.get_by_role("button", name=re.compile(re.escape(label), re.I)),
            page.get_by_role("link", name=re.compile(re.escape(label), re.I)),
            page.get_by_text(re.compile(rf"^\s*{re.escape(label)}\s*$", re.I)),
            page.get_by_text(re.compile(re.escape(label), re.I)),
        ]
        for locator in patterns:
            try:
                locator.first.wait_for(state="visible", timeout=timeout)
                locator.first.click(timeout=timeout)
                page.wait_for_timeout(900)
                return MatchResult(label=label, matched=True)
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue
    return MatchResult(label=", ".join(labels), matched=False)


def login(page: Page) -> None:
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
    user_selector = first_visible(page, ["#Frm_Username", "input[name*=User i]", "input[type=text]", "input:not([type])"])
    pass_selector = first_visible(page, ["#Frm_Password", "input[type=password]", "input[name*=Pass i]"])
    if not user_selector or not pass_selector:
        save_artifacts(page, "login-fields-not-found")
        raise RuntimeError("Could not find login fields.")
    page.fill(user_selector, USER)
    page.fill(pass_selector, PASSWORD)
    login_selector = first_visible(page, ["#LoginId", "button:has-text('Login')", "input[type=submit]", "[role=button]:has-text('Login')"])
    if not login_selector:
        save_artifacts(page, "login-button-not-found")
        raise RuntimeError("Could not find login button.")
    page.click(login_selector)
    page.wait_for_timeout(3000)
    save_artifacts(page, "after-login")


def is_login_page(page: Page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=1500).lower()
    except Exception:
        return False
    return "please login" in text or ("username" in text and "password" in text and "login" in text)


def ensure_logged_in(page: Page) -> None:
    if is_login_page(page):
        log("Router returned to login page; re-authenticating before continuing.")
        login(page)


def navigate_to_port_forwarding(page: Page) -> None:
    ensure_logged_in(page)
    candidates = [
        "#state=internet/security/port-forwarding",
        "#state=internet/port-forwarding",
        "#state=port-forwarding",
        "#state=nat/port-forwarding",
        "#state=security/port-forwarding",
        "#state=application/port-forwarding",
    ]
    for fragment in candidates:
        page.goto(f"{BASE_URL}/{fragment}", wait_until="domcontentloaded", timeout=10000)
        page.wait_for_timeout(1500)
        ensure_logged_in(page)
        if is_login_page(page):
            continue
        if has_port_forwarding_text(page):
            save_artifacts(page, "port-forwarding-page")
            return

    for top in ["Internet", "Security", "Application", "Advanced", "NAT"]:
        click_text(page, [top], timeout=900)
        for child in ["Port Forwarding", "Port Mapping", "Virtual Server", "NAT", "Forwarding"]:
            result = click_text(page, [child], timeout=900)
            if result.matched and has_port_forwarding_text(page):
                save_artifacts(page, "port-forwarding-page")
                return

    save_artifacts(page, "port-forwarding-not-found")
    raise RuntimeError(f"Could not confidently find a port-forwarding page. Artifacts: {ARTIFACT_DIR}")


def has_port_forwarding_text(page: Page) -> bool:
    text = page.locator("body").inner_text(timeout=3000).lower()
    return (
        ("port forwarding" in text or "port mapping" in text or "virtual server" in text)
        and ("external" in text or "internal" in text or "wan" in text or "lan" in text or "protocol" in text)
    )


def fill_first_matching(page: Page, labels: list[str], value: str, required: bool = True) -> bool:
    for label in labels:
        locators = [
            page.get_by_label(re.compile(label, re.I)),
            page.locator(f"input[placeholder*='{label}' i]"),
            page.locator(f"input[name*='{label}' i]"),
            page.locator(f"input[id*='{label}' i]"),
        ]
        for locator in locators:
            try:
                target = locator.first
                target.wait_for(state="visible", timeout=700)
                target.fill(value, timeout=1000)
                return True
            except Exception:
                continue
    if required:
        log(f"Required field not found for labels: {labels}")
    return False


def select_first_matching(page: Page, labels: list[str], value: str, required: bool = False) -> bool:
    for label in labels:
        locators = [
            page.get_by_label(re.compile(label, re.I)),
            page.locator(f"select[name*='{label}' i]"),
            page.locator(f"select[id*='{label}' i]"),
        ]
        for locator in locators:
            try:
                target = locator.first
                target.wait_for(state="visible", timeout=700)
                try:
                    target.select_option(label=re.compile(value, re.I), timeout=1000)
                except Exception:
                    target.select_option(value=value, timeout=1000)
                return True
            except Exception:
                continue
    if required:
        log(f"Required select not found for labels: {labels}")
    return False


def check_enable(page: Page) -> None:
    for pattern in ["enable", "active", "on"]:
        try:
            box = page.get_by_label(re.compile(pattern, re.I)).first
            box.wait_for(state="visible", timeout=700)
            if not box.is_checked():
                box.check(timeout=1000)
            return
        except Exception:
            continue


def click_add(page: Page) -> None:
    result = click_text(page, ["Add", "New", "Create", "Add New", "New Item"], timeout=1200)
    if not result.matched:
        save_artifacts(page, "add-button-not-found")
        raise RuntimeError("Could not find Add/New button on port-forwarding page.")


def fill_rule(page: Page) -> None:
    missing = []
    if not fill_first_matching(page, ["service name", "application name", "rule name", "name", "description"], RULE_NAME, required=False):
        log("No rule-name field found; continuing if this UI does not require one.")
    if not fill_first_matching(page, ["internal host", "internal client", "lan ip", "client ip", "server ip", "host ip", "ip address"], TARGET_IP):
        missing.append("target IP")
    for labels in [
        ["external start", "wan start", "public start", "external port start", "start external"],
        ["external end", "wan end", "public end", "external port end", "end external"],
        ["internal start", "lan start", "private start", "internal port start", "start internal"],
        ["internal end", "lan end", "private end", "internal port end", "end internal"],
        ["external port", "wan port", "public port"],
        ["internal port", "lan port", "private port"],
        ["port"],
    ]:
        fill_first_matching(page, labels, PORT, required=False)
    select_first_matching(page, ["protocol"], PROTOCOL, required=False)
    check_enable(page)
    if missing:
        save_artifacts(page, "required-fields-not-found")
        raise RuntimeError(f"Could not fill required fields: {', '.join(missing)}")


def has_zte_port_forwarding_fields(page: Page) -> bool:
    return page.locator('[id="OBJ_FWPM_ID.Alias:portForwarding"]').count() > 0


def set_value(page: Page, selector: str, value: str) -> None:
    page.locator(selector).first.wait_for(state="attached", timeout=1500)
    page.eval_on_selector(
        selector,
        """(element, value) => {
            element.value = value;
            element.dispatchEvent(new Event('input', {bubbles: true}));
            element.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        value,
    )


def set_checked(page: Page, selector: str) -> None:
    page.locator(selector).first.wait_for(state="attached", timeout=1500)
    page.eval_on_selector(
        selector,
        """(element) => {
            element.checked = true;
            element.dispatchEvent(new Event('click', {bubbles: true}));
            element.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
    )


def click_selector(page: Page, selector: str) -> None:
    page.locator(selector).first.wait_for(state="attached", timeout=1500)
    try:
        page.locator(selector).first.click(force=True, timeout=1500)
    except Exception:
        page.eval_on_selector(
            selector,
            """(element) => {
                element.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                element.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                element.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                if (typeof element.click === 'function') {
                    element.click();
                }
            }""",
        )


def zte_visible_new_suffix(page: Page) -> str:
    suffix = page.evaluate(
        """() => {
            const visible = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            };
            const aliases = [...document.querySelectorAll('input[id^="OBJ_FWPM_ID.Alias:portForwarding"]')]
                .filter(visible)
                .filter((element) => element.value === '');
            const last = aliases[aliases.length - 1];
            if (!last) {
                return null;
            }
            const parts = last.id.split(':');
            return parts.length >= 3 ? parts[2] : '';
        }"""
    )
    if suffix is None:
        save_artifacts(page, "zte-visible-new-suffix-not-found")
        raise RuntimeError("Could not find visible new port-forwarding editor suffix.")
    return str(suffix)


def zte_id(base: str, suffix: str) -> str:
    return f'[id="{base}{":" + suffix if suffix else ""}"]'


def zte_fill_rule(page: Page, enabled: bool) -> str:
    click_selector(page, '[id="addInstBar_portForwarding"]')
    page.wait_for_timeout(700)
    suffix = zte_visible_new_suffix(page)
    set_checked(page, zte_id("OBJ_FWPM_ID.Enable1:portForwarding", suffix) if enabled else zte_id("OBJ_FWPM_ID.Enable0:portForwarding", suffix))
    set_value(page, zte_id("OBJ_FWPM_ID.Alias:portForwarding", suffix), RULE_NAME)
    page.eval_on_selector(
        zte_id("OBJ_FWPM_ID.Protocol:portForwarding", suffix),
        """(element, protocol) => {
            const wanted = protocol.toLowerCase();
            const option = [...element.options].find((item) =>
                item.value.toLowerCase() === wanted || item.textContent.toLowerCase().includes(wanted)
            );
            if (!option) {
                throw new Error(`Protocol option not found: ${protocol}`);
            }
            element.value = option.value;
            element.dispatchEvent(new Event('input', {bubbles: true}));
            element.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        PROTOCOL,
    )
    for index, octet in enumerate(["0", "0", "0", "0"]):
        set_value(page, zte_id(f"sub_OBJ_FWPM_ID.RemoteHost:portForwarding{index}", suffix), octet)
        set_value(page, zte_id(f"sub_OBJ_FWPM_ID.RemoteHostEndRange:portForwarding{index}", suffix), octet)
    set_value(page, zte_id("OBJ_FWPM_ID.RemoteHost:portForwarding", suffix), "0.0.0.0")
    set_value(page, zte_id("OBJ_FWPM_ID.RemoteHostEndRange:portForwarding", suffix), "0.0.0.0")
    set_value(page, zte_id("OBJ_FWPM_ID.InternalClient:portForwarding", suffix), TARGET_IP)
    set_value(page, zte_id("OBJ_FWPM_ID.ExternalPort:portForwarding", suffix), PORT)
    set_value(page, zte_id("OBJ_FWPM_ID.ExternalPortEndRange:portForwarding", suffix), PORT)
    set_value(page, zte_id("OBJ_FWPM_ID.InternalPort:portForwarding", suffix), PORT)
    set_value(page, zte_id("OBJ_FWPM_ID.InternalPortEndRange:portForwarding", suffix), PORT)
    return suffix


def zte_debug_visible_fields(page: Page, stage: str) -> None:
    fields = page.evaluate(
        """() => [...document.querySelectorAll('#portForwarding input, #portForwarding select')].map((element) => {
            const rect = element.getBoundingClientRect();
            const style = window.getComputedStyle(element);
            return {
                id: element.id,
                name: element.name,
                type: element.tagName.toLowerCase() === 'select' ? 'select' : element.type,
                value: element.value,
                checked: element.checked === true,
                visible: rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none',
                rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
            };
        })"""
    )
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    import json

    (ARTIFACT_DIR / f"visible-fields-{stage}.json").write_text(json.dumps(fields, indent=2, sort_keys=True), encoding="utf-8")


def zte_debug_fill_no_apply(page: Page) -> None:
    zte_debug_visible_fields(page, "before-fill")
    zte_fill_rule(page, enabled=False)
    zte_debug_visible_fields(page, "after-fill")
    save_artifacts(page, "debug-after-fill-no-apply")


def zte_apply_new_rule(page: Page, suffix: str) -> None:
    click_selector(page, zte_id("Btn_apply_portForwarding", suffix))
    page.wait_for_timeout(3000)
    click_text(page, ["OK", "Yes", "Confirm"], timeout=900)
    page.wait_for_timeout(2000)


def zte_rule_index(page: Page) -> str | None:
    return page.evaluate(
        """(ruleName) => {
            const inputs = [...document.querySelectorAll('input[id^="OBJ_FWPM_ID.Alias:portForwarding"]')];
            for (const input of inputs) {
                if (input.value === ruleName) {
                    const parts = input.id.split(':');
                    return parts.length >= 3 ? parts[2] : '';
                }
            }
            const titles = [...document.querySelectorAll('[id^="instName_portForwarding"]')];
            for (const title of titles) {
                if ((title.getAttribute('title') || title.textContent || '').trim() === ruleName) {
                    return title.id.split(':')[1] || '';
                }
            }
            return null;
        }""",
        RULE_NAME,
    )


def zte_activate_rule(page: Page) -> None:
    index = zte_rule_index(page)
    if index is None:
        save_artifacts(page, "zte-activate-index-not-found")
        raise RuntimeError("Could not find created rule index for activation.")
    suffix = f":{index}" if index else ""
    set_checked(page, f'[id="OBJ_FWPM_ID.Enable1:portForwarding{suffix}"]')
    click_selector(page, f'[id="Btn_apply_portForwarding{suffix}"]')
    page.wait_for_timeout(3000)
    click_text(page, ["OK", "Yes", "Confirm"], timeout=900)
    page.wait_for_timeout(2000)


def zte_deactivate_rule(page: Page) -> None:
    index = zte_rule_index(page)
    if index is None:
        save_artifacts(page, "zte-deactivate-index-not-found")
        raise RuntimeError("Could not find created rule index for deactivation.")
    suffix = f":{index}" if index else ""
    set_checked(page, f'[id="OBJ_FWPM_ID.Enable0:portForwarding{suffix}"]')
    click_selector(page, f'[id="Btn_apply_portForwarding{suffix}"]')
    page.wait_for_timeout(3000)
    click_text(page, ["OK", "Yes", "Confirm"], timeout=900)
    page.wait_for_timeout(2000)


def zte_delete_rule(page: Page) -> None:
    index = zte_rule_index(page)
    if index is None:
        save_artifacts(page, "zte-delete-index-not-found")
        raise RuntimeError("Could not find created rule index for deletion.")
    suffix = f":{index}" if index else ""
    click_selector(page, f'[id="instDelete_Btn_delete_Delete{suffix}"]')
    page.wait_for_timeout(1000)
    click_text(page, ["OK", "Yes", "Confirm"], timeout=1200)
    page.wait_for_timeout(3000)


def click_save_apply(page: Page) -> None:
    result = click_text(page, ["Apply", "Save", "OK", "Submit"], timeout=1500)
    if not result.matched:
        save_artifacts(page, "save-button-not-found")
        raise RuntimeError("Could not find Apply/Save button.")
    page.wait_for_timeout(2500)


def page_contains_rule(page: Page) -> bool:
    text = page.locator("body").inner_text(timeout=3000)
    return RULE_NAME in text or PORT in text


def delete_rule(page: Page) -> None:
    if not page_contains_rule(page):
        raise RuntimeError("Rule is not visible before delete; refusing cleanup click.")
    row = page.locator("tr", has_text=re.compile(re.escape(RULE_NAME) + "|" + re.escape(PORT))).first
    try:
        row.wait_for(state="visible", timeout=1200)
        for label in ["Delete", "Remove"]:
            button = row.get_by_role("button", name=re.compile(label, re.I)).first
            try:
                button.wait_for(state="visible", timeout=800)
                button.click(timeout=1000)
                page.wait_for_timeout(1000)
                click_text(page, ["OK", "Yes", "Confirm"], timeout=1000)
                page.wait_for_timeout(2500)
                return
            except Exception:
                continue
    except Exception:
        pass
    result = click_text(page, ["Delete", "Remove"], timeout=1200)
    if not result.matched:
        save_artifacts(page, "delete-button-not-found")
        raise RuntimeError("Could not find Delete/Remove control for cleanup.")
    click_text(page, ["OK", "Yes", "Confirm"], timeout=1000)
    page.wait_for_timeout(2500)


def create_rule_disabled(page: Page) -> None:
    if has_zte_port_forwarding_fields(page):
        suffix = zte_fill_rule(page, enabled=False)
        save_artifacts(page, "before-create-disabled-apply")
        zte_apply_new_rule(page, suffix)
        return
    click_add(page)
    fill_rule(page)
    save_artifacts(page, "before-create-apply")
    click_save_apply(page)


def activate_rule(page: Page) -> None:
    if has_zte_port_forwarding_fields(page):
        zte_activate_rule(page)
        return
    log("Generic activation fallback: rule was created with enable/on selected where available.")


def deactivate_rule(page: Page) -> None:
    if has_zte_port_forwarding_fields(page):
        zte_deactivate_rule(page)
        return
    log("Generic deactivation fallback: no reliable disable control was detected before delete.")


def cleanup_rule(page: Page) -> None:
    if has_zte_port_forwarding_fields(page):
        zte_delete_rule(page)
        return
    delete_rule(page)


def main() -> int:
    log(f"Live router port-forward test mode: {MODE}")
    log(f"Rule: {RULE_NAME}, target={TARGET_IP}, port={PORT}, protocol={PROTOCOL}")
    if not (1 <= len(RULE_NAME) <= 10):
        raise RuntimeError("Router validation rule name must be 1-10 characters for this external validation profile.")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        try:
            login(page)
            navigate_to_port_forwarding(page)
            log(f"Port-forwarding UI located. Artifacts: {ARTIFACT_DIR}")
            if MODE == "plan":
                log("Plan mode stops before Add/Create. Re-run with apply mode and confirmation env var for live changes.")
                return 0
            if MODE == "debug-fill":
                zte_debug_fill_no_apply(page)
                log(f"Debug fill artifacts written to {ARTIFACT_DIR}")
                return 0
            if MODE == "cleanup":
                if not page_contains_rule(page):
                    save_artifacts(page, "cleanup-rule-not-found")
                    log("Cleanup mode: temporary rule is not visible; nothing to delete.")
                    return 0
                deactivate_rule(page)
                save_artifacts(page, "cleanup-after-deactivate")
                ensure_logged_in(page)
                navigate_to_port_forwarding(page)
                cleanup_rule(page)
                save_artifacts(page, "cleanup-after-delete")
                navigate_to_port_forwarding(page)
                if page_contains_rule(page):
                    save_artifacts(page, "cleanup-delete-verification-failed")
                    raise RuntimeError("Cleanup mode: temporary rule still appears after delete.")
                log("Cleanup mode: temporary rule deleted and no longer visible to automation.")
                return 0

            require_user_confirmation(
                "Preflight: please log into the router manually and confirm the bogus rule is NOT present before the test starts.",
                expected="absent",
            )
            ensure_logged_in(page)
            navigate_to_port_forwarding(page)
            if page_contains_rule(page):
                log("Temporary rule already appears present; skipping create and moving to manual inactive confirmation.")
                save_artifacts(page, "preexisting-rule-found")
            else:
                log("Creating temporary disabled port-forward rule.")
                create_rule_disabled(page)
                save_artifacts(page, "after-create")
            require_user_confirmation(
                "Manual check: confirm the bogus rule is present and inactive/disabled.",
                expected="inactive",
            )

            ensure_logged_in(page)
            navigate_to_port_forwarding(page)
            if not page_contains_rule(page):
                save_artifacts(page, "created-rule-not-found")
                raise RuntimeError("Temporary rule was not found after create.")
            log("Temporary rule is present after create.")
            activate_rule(page)
            save_artifacts(page, "after-activate")
            ensure_logged_in(page)
            navigate_to_port_forwarding(page)
            if not page_contains_rule(page):
                save_artifacts(page, "activated-rule-not-found")
                raise RuntimeError("Temporary rule was not found after activation.")
            require_user_confirmation(
                "Manual check: confirm the bogus rule is present and active/enabled.",
                expected="active",
            )

            ensure_logged_in(page)
            navigate_to_port_forwarding(page)
            deactivate_rule(page)
            save_artifacts(page, "after-deactivate")
            ensure_logged_in(page)
            navigate_to_port_forwarding(page)
            cleanup_rule(page)
            save_artifacts(page, "after-delete")
            navigate_to_port_forwarding(page)
            if page_contains_rule(page):
                save_artifacts(page, "delete-verification-failed")
                raise RuntimeError("Temporary rule still appears after delete.")
            require_user_confirmation(
                "Manual final check: confirm the bogus rule is no longer present.",
                expected="gone",
            )
            log("Temporary rule deactivated, deleted, and manually confirmed gone.")
            return 0
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
