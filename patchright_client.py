"""Live-lookup layer. Embeds patchright (patched playwright), mirroring the
patchright.nlma.io pattern. Two targets:

  OCIS 2.0  https://eapps.courts.state.va.us/ocis/landing   -> statewide CRIMINAL/TRAFFIC
  CJISWeb   https://eapps.courts.state.va.us/CJISWeb/...     -> per-court CIVIL + CRIMINAL

CAPTCHA: OCIS + the district systems gate search behind a clickwrap Accept + reCAPTCHA.
We DO NOT auto-solve. On reCAPTCHA we raise CaptchaHandoff with a live page handle so the
caller surfaces a handoff (same pattern as patchright pr_human_step), human solves, run resumes.

SELECTORS below are placeholders marked TODO:LIVE — they MUST be confirmed against the live
(CAPTCHA-gated) DOM before production. Court selection is done by visible NAME, not internal code.
"""
from dataclasses import dataclass

OCIS_URL    = "https://eapps.courts.state.va.us/ocis/landing"
CJIS_CIRCUIT= "https://eapps.courts.state.va.us/CJISWeb/circuit.html"
CJIS_GD     = "https://eapps.courts.state.va.us/gdcourts"

class CaptchaHandoff(Exception):
    """Raised when a reCAPTCHA blocks progress. Carries the handoff context."""
    def __init__(self, target_url, page_id=None):
        self.target_url, self.page_id = target_url, page_id
        super().__init__(f"reCAPTCHA at {target_url} needs human solve")

@dataclass
class LiveConfig:
    headless: bool = True
    nav_timeout_ms: int = 30000

async def _new_page(cfg: LiveConfig):
    from patchright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=cfg.headless)
    ctx = await browser.new_context()
    page = await ctx.new_page()
    page.set_default_timeout(cfg.nav_timeout_ms)
    return pw, browser, page

async def search_criminal_statewide(name: str, dob: str = None, cfg: LiveConfig = LiveConfig()):
    """OCIS 2.0 statewide adult criminal/traffic by name. Returns list[dict] (schema.CaseRecord)."""
    pw, browser, page = await _new_page(cfg)
    try:
        await page.goto(OCIS_URL)
        # TODO:LIVE accept clickwrap  -> page.click("button:has-text('Accept')")
        # TODO:LIVE if page.locator("iframe[src*='recaptcha']").count(): raise CaptchaHandoff(OCIS_URL)
        # TODO:LIVE page.fill("#lastName", ...); page.fill("#firstName", ...); page.click("#searchBtn")
        # TODO:LIVE parse result rows -> CaseRecord(source="ocis", division="criminal"|"traffic", ...)
        raise NotImplementedError("OCIS selectors pending live recon (CAPTCHA-gated)")
    finally:
        await browser.close(); await pw.stop()

async def search_court(name: str, court_code: str, court_name: str, court_level: str,
                       division: str, cfg: LiveConfig = LiveConfig()):
    """CJISWeb per-court civil|criminal by name. court_level in {circuit, gd}."""
    pw, browser, page = await _new_page(cfg)
    try:
        await page.goto(CJIS_CIRCUIT if court_level == "circuit" else CJIS_GD)
        # TODO:LIVE select court by VISIBLE NAME: page.select_option("#courtSelect", label=court_name)
        # TODO:LIVE click Begin; choose division (Civil/Criminal); search by Name
        # TODO:LIVE handle reCAPTCHA -> raise CaptchaHandoff(...)
        # TODO:LIVE parse rows -> CaseRecord(source="cjisweb", court_code=court_code, ...)
        raise NotImplementedError("CJISWeb selectors pending live recon")
    finally:
        await browser.close(); await pw.stop()
