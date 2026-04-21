from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Error, Page, Response, TimeoutError, sync_playwright


DEFAULT_PROFILE_DIR = Path("~/.codex/browser_profiles/pku_library_chrome").expanduser()
DEFAULT_MANIFEST_PATH = Path("scripts/manual_pdf_url_manifest.seed.json")
DEFAULT_REPORT_PATH = Path("docs/experiments/browser_discovered_pdf_urls.json")
DEFAULT_BROWSER_PATH = Path("/usr/bin/chromium")
CLICK_TEXT_RE = re.compile(r"pdf|download|full\s*text|view\s*pdf|accepted\s*manuscript|working\s*paper", re.IGNORECASE)


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def looks_like_pdf_url(url: str) -> bool:
    lower = (url or "").strip().lower()
    return any(
        marker in lower
        for marker in [
            ".pdf",
            "/pdf/",
            "stamp.jsp",
            "/doi/pdf/",
            "/article/download/",
            "/download",
            "pdfft",
            "delivery.cfm",
        ]
    )


def prioritized_urls(urls: list[str]) -> list[str]:
    def score(url: str) -> tuple[int, str]:
        lower = url.lower()
        if "arxiv.org/pdf/" in lower:
            return (0, lower)
        if ".pdf" in lower or "/pdf/" in lower or "download" in lower or "stamp.jsp" in lower:
            return (1, lower)
        if "doi.org/" in lower:
            return (2, lower)
        return (3, lower)

    seen: set[str] = set()
    ordered: list[str] = []
    for url in sorted((item.strip() for item in urls if item and item.strip()), key=score):
        if url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return ordered


def _response_is_pdf_like(response: Response) -> bool:
    headers = {key.lower(): value for key, value in response.headers.items()}
    content_type = headers.get("content-type", "").lower()
    content_disposition = headers.get("content-disposition", "").lower()
    return (
        "application/pdf" in content_type
        or "application/octet-stream" in content_type
        or "filename=" in content_disposition
        or looks_like_pdf_url(response.url)
    )


def _response_record(response: Response) -> dict[str, str]:
    headers = {key.lower(): value for key, value in response.headers.items()}
    return {
        "url": response.url,
        "status": str(response.status),
        "content_type": headers.get("content-type", ""),
        "content_disposition": headers.get("content-disposition", ""),
    }


def extract_pdf_like_links(page: Page) -> list[str]:
    script = r"""
    () => {
      const out = [];
      const seen = new Set();
      const push = (value) => {
        if (!value) return;
        const clean = String(value).trim();
        if (!clean || seen.has(clean)) return;
        seen.add(clean);
        out.push(clean);
      };
      for (const node of document.querySelectorAll('a[href], iframe[src], embed[src], object[data]')) {
        push(node.href || node.src || node.data || '');
      }
      for (const node of document.querySelectorAll('a, button')) {
        const text = (node.innerText || node.textContent || '').trim();
        const href = node.href || node.getAttribute('href') || '';
        if (text && /pdf|download|full\s*text|view\s*pdf|accepted\s*manuscript|working\s*paper/i.test(text)) {
          push(href);
        }
      }
      return out;
    }
    """
    try:
        values = page.evaluate(script)
    except Error:
        values = []
    return [value for value in values if isinstance(value, str) and value.strip() and looks_like_pdf_url(value)]


def _collect_pdf_like_urls(context: BrowserContext, page: Page) -> list[str]:
    urls: list[str] = []
    for current in context.pages:
        current_url = current.url
        if current_url and looks_like_pdf_url(current_url):
            urls.append(current_url)
        urls.extend(extract_pdf_like_links(current))
    current_url = page.url
    if current_url and looks_like_pdf_url(current_url):
        urls.append(current_url)
    return prioritized_urls(urls)


def _click_pdf_controls(context: BrowserContext, page: Page, timeout_ms: int) -> tuple[list[str], list[dict[str, str]]]:
    discovered: list[str] = []
    click_attempts: list[dict[str, str]] = []

    for role in ("link", "button"):
        locator = page.get_by_role(role, name=CLICK_TEXT_RE)
        count = min(locator.count(), 4)
        for idx in range(count):
            target = locator.nth(idx)
            try:
                label = (target.inner_text(timeout=1500) or "").strip()
            except Error:
                label = ""
            href = ""
            try:
                href = target.get_attribute("href") or ""
            except Error:
                href = ""
            before_urls = set(_collect_pdf_like_urls(context, page))
            try:
                target.click(timeout=min(timeout_ms, 5000), force=True)
                page.wait_for_timeout(1200)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except TimeoutError:
                    pass
                after_urls = _collect_pdf_like_urls(context, page)
                for url in after_urls:
                    if url not in before_urls and url not in discovered:
                        discovered.append(url)
                click_attempts.append(
                    {
                        "role": role,
                        "label": label,
                        "href": href,
                        "status": "clicked",
                        "page_url": page.url,
                    }
                )
            except TimeoutError:
                click_attempts.append({"role": role, "label": label, "href": href, "error": "timeout"})
            except Error as exc:
                click_attempts.append({"role": role, "label": label, "href": href, "error": f"playwright_error:{exc}"})

    return prioritized_urls(discovered), click_attempts


def discover_urls(
    context: BrowserContext,
    page: Page,
    paper: dict[str, Any],
    timeout_ms: int,
    network_events: list[dict[str, str]],
) -> tuple[list[str], list[dict[str, Any]]]:
    source_urls = paper.get("all_pdf_like_urls") or paper.get("manual_urls") or []
    base_candidates = prioritized_urls(list(source_urls))
    attempts: list[dict[str, Any]] = []
    discovered: list[str] = []
    seen: set[str] = set(base_candidates)

    for url in base_candidates:
        attempt_page = context.new_page()
        before_network = len(network_events)
        try:
            response = attempt_page.goto(url, wait_until="commit", timeout=timeout_ms)
            attempt_page.wait_for_timeout(1200)
            try:
                attempt_page.wait_for_load_state("networkidle", timeout=5000)
            except TimeoutError:
                pass
            final_url = attempt_page.url
            if final_url and looks_like_pdf_url(final_url) and final_url not in seen:
                seen.add(final_url)
                discovered.append(final_url)
            for item in _collect_pdf_like_urls(context, attempt_page):
                if item in seen:
                    continue
                seen.add(item)
                discovered.append(item)
            clicked_urls, click_attempts = _click_pdf_controls(context, attempt_page, timeout_ms=timeout_ms)
            for item in clicked_urls:
                if item in seen:
                    continue
                seen.add(item)
                discovered.append(item)
            network_hits = network_events[before_network:]
            for hit in network_hits:
                hit_url = hit.get("url", "")
                if hit_url and hit_url not in seen:
                    seen.add(hit_url)
                    discovered.append(hit_url)
            attempts.append(
                {
                    "url": url,
                    "final_url": final_url,
                    "status": str(response.status) if response is not None else "no_response",
                    "content_type": response.headers.get("content-type", "") if response is not None else "",
                    "click_attempts": click_attempts,
                    "network_hits": network_hits,
                }
            )
        except TimeoutError:
            attempts.append({"url": url, "error": "timeout"})
        except Error as exc:
            attempts.append({"url": url, "error": f"playwright_error:{exc}"})
        finally:
            try:
                attempt_page.close()
            except Error:
                pass

    return prioritized_urls(base_candidates + discovered), attempts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Use a logged-in browser session to discover final PDF URLs for missing papers.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--browser-path", default=str(DEFAULT_BROWSER_PATH))
    parser.add_argument("--login-url", default="https://www.lib.pku.edu.cn/portal/cn/")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--skip-login-pause", action="store_true")
    parser.add_argument("--headless", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest_path = Path(args.manifest).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    profile_dir = Path(args.profile_dir).expanduser().resolve()
    browser_path = Path(args.browser_path).expanduser().resolve()

    manifest = load_manifest(manifest_path)
    papers = list(manifest.get("papers") or [])
    if args.limit is not None:
        papers = papers[: args.limit]

    report_records: list[dict[str, Any]] = []
    report_payload: dict[str, Any] = {
        "manifest_path": str(manifest_path),
        "browser_path": str(browser_path),
        "paper_count": len(papers),
        "records": report_records,
    }

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            executable_path=str(browser_path),
            headless=args.headless,
            accept_downloads=False,
            args=["--no-sandbox"],
        )
        network_events: list[dict[str, str]] = []

        def handle_response(response: Response) -> None:
            try:
                if _response_is_pdf_like(response):
                    network_events.append(_response_record(response))
            except Error:
                return

        context.on("response", handle_response)
        page = context.new_page()
        if args.login_url:
            try:
                page.goto(args.login_url, wait_until="commit", timeout=int(args.timeout * 1000))
            except Error as exc:
                print(json.dumps({"login_url": args.login_url, "warning": f"login_navigation_failed:{exc}"}, ensure_ascii=False))
        if not args.skip_login_pause:
            input("Complete PKU library login in the browser, then press Enter here to continue...")

        for paper in papers:
            all_urls, attempts = discover_urls(context, page, paper, timeout_ms=int(args.timeout * 1000), network_events=network_events)
            report_records.append(
                {
                    "paper_id": paper.get("paper_id"),
                    "title": paper.get("title"),
                    "manual_urls": paper.get("manual_urls") or [],
                    "all_pdf_like_urls": all_urls,
                    "attempts": attempts,
                }
            )
            save_report(report_path, report_payload)
            print(json.dumps({"paper_id": paper.get("paper_id"), "title": paper.get("title"), "url_count": len(all_urls)}, ensure_ascii=False))

        context.close()

    print(f"report_path={report_path}")


if __name__ == "__main__":
    main()
