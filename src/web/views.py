"""Server-rendered HTML views for the web app (premium, Windsor-style).

Kept separate from routing in app.py. Functions take plain data structures so
they're easy to test and reason about.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

# Connect-route slug per platform value.
PLATFORM_SLUGS = {"meta_ads": "meta", "google_ads": "google-ads"}
PLATFORM_LABELS = {"meta_ads": "Meta Ads", "google_ads": "Google Ads"}
PLATFORM_ICONS = {"meta_ads": "f", "google_ads": "G"}


@dataclass(frozen=True)
class AccountView:
    external_account_id: str
    account_name: str
    selected: bool


@dataclass(frozen=True)
class PlatformView:
    platform: str
    accounts: list[AccountView]

    @property
    def label(self) -> str:
        return PLATFORM_LABELS.get(self.platform, self.platform)

    @property
    def slug(self) -> str:
        return PLATFORM_SLUGS.get(self.platform, self.platform)

    @property
    def icon(self) -> str:
        return PLATFORM_ICONS.get(self.platform, "•")

    @property
    def connected(self) -> bool:
        return len(self.accounts) > 0

    @property
    def selected_count(self) -> int:
        return sum(1 for a in self.accounts if a.selected)


_CSS = """
:root{--ink:#0f1419;--muted:#69748a;--line:#e1e6ec;--surface:#edf0f4;
  --slate:#3a4b63;--slate-deep:#26344a;--slate-soft:#eef2f7;--green:#2f8568;--green-soft:#e6f3ed;}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:linear-gradient(180deg,#f4f7fa,#e7ebf0);
  color:var(--ink);font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased;}
a{color:inherit}
.shell{width:min(1180px,calc(100vw - 40px));margin:0 auto;padding:18px 0 64px;}
.topnav{display:flex;align-items:center;justify-content:space-between;background:#fff;
  border:1px solid var(--line);border-radius:12px;box-shadow:0 1px 2px rgba(15,20,25,.04);
  padding:12px 20px;margin-bottom:28px;}
.topnav img{height:28px;display:block}
.topnav .who{display:flex;align-items:center;gap:14px;color:var(--muted);font-size:14px}
.btn{display:inline-block;border:0;cursor:pointer;text-decoration:none;font-weight:700;font-size:14px;
  background:linear-gradient(135deg,#415471,#29384f);color:#fff;padding:10px 18px;border-radius:10px;
  box-shadow:0 8px 18px rgba(38,52,74,.22);}
.btn.ghost{background:#fff;color:var(--slate-deep);border:1px solid var(--line);box-shadow:none}
.btn.sm{padding:7px 14px;font-size:13px}
.hero h1{font-size:34px;letter-spacing:-.025em;margin:0 0 8px}
.hero p{color:var(--muted);margin:0 0 26px;font-size:16px;max-width:640px;line-height:1.55}
.grid{display:grid;grid-template-columns:300px minmax(0,1fr);gap:18px;align-items:start}
.panel{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 10px 30px rgba(22,32,50,.07);}
.side{padding:16px}
.side h2,.main h2{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin:4px 6px 14px}
.src{display:flex;align-items:center;gap:12px;padding:12px;border-radius:12px;border:1px solid transparent}
.src+.src{margin-top:4px}
.src:hover{background:var(--slate-soft)}
.ico{width:38px;height:38px;border-radius:10px;display:grid;place-items:center;font-weight:800;color:#fff;flex:0 0 auto}
.ico.meta_ads{background:#1877f2}.ico.google_ads{background:#1a73e8}
.src .meta{flex:1;min-width:0}
.src .name{font-weight:700}
.src .status{font-size:12.5px;color:var(--muted)}
.src .status.on{color:var(--green);font-weight:700}
.main{padding:24px 26px}
.empty{display:grid;place-items:center;min-height:280px;color:var(--muted);text-align:center}
.acct-card{border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:16px}
.acct-card .head{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.acct-card .head strong{font-size:16px}
.pill{font-size:12px;font-weight:700;color:var(--green-deep,#2f8568);background:var(--green-soft);
  border:1px solid #cfe8dc;border-radius:999px;padding:4px 10px}
.acct{display:flex;align-items:center;gap:12px;padding:10px 6px;border-top:1px solid #f0f2f6}
.acct input{width:18px;height:18px;accent-color:var(--slate)}
.acct .an{font-weight:600}.acct .ai{color:var(--muted);font-size:12.5px;margin-left:auto}
.save{margin-top:14px;display:flex;justify-content:flex-end}
.card-signin{max-width:460px;margin:8vh auto 0;text-align:center}
.muted{color:var(--muted);line-height:1.55}
"""


def render_page(body: str, *, title: str = "OudSeed") -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title>"
        "<link rel='icon' type='image/png' href='/assets/oudseed-logo.png'>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


def render_signin() -> str:
    body = (
        "<div class='shell'><main class='panel card-signin' style='padding:44px'>"
        "<img src='/assets/oudseed-wordmark.png' alt='OudSeed' style='height:34px;margin-bottom:18px'>"
        "<h1 style='font-size:26px;margin:0 0 10px'>Connect your ad data</h1>"
        "<p class='muted'>Sign in to connect Meta and Google Ads and get automatic "
        "AI performance reports.</p>"
        "<p style='margin-top:18px'><a class='btn' href='/auth/google/login'>Sign in with Google</a></p>"
        "</main></div>"
    )
    return render_page(body)


def _topnav(user_label: str) -> str:
    return (
        "<nav class='topnav'>"
        "<a href='/'><img src='/assets/oudseed-wordmark.png' alt='OudSeed'></a>"
        f"<div class='who'><span>{html.escape(user_label)}</span>"
        "<form method='post' action='/auth/logout' style='margin:0'>"
        "<button class='btn ghost sm' type='submit'>Sign out</button></form></div>"
        "</nav>"
    )


def _sidebar(platforms: list[PlatformView]) -> str:
    rows = []
    for p in platforms:
        if p.connected:
            status = f"<div class='status on'>Connected · {p.selected_count}/{len(p.accounts)} selected</div>"
            action = f"<a class='btn ghost sm' href='/connect/{p.slug}/start'>Reconnect</a>"
        else:
            status = "<div class='status'>Not connected</div>"
            action = f"<a class='btn sm' href='/connect/{p.slug}/start'>Connect</a>"
        rows.append(
            f"<div class='src'><div class='ico {p.platform}'>{p.icon}</div>"
            f"<div class='meta'><div class='name'>{html.escape(p.label)}</div>{status}</div>"
            f"{action}</div>"
        )
    return "<aside class='panel side'><h2>Data sources</h2>" + "".join(rows) + "</aside>"


def _account_form(p: PlatformView) -> str:
    items = []
    for a in p.accounts:
        checked = "checked" if a.selected else ""
        name = html.escape(a.account_name or a.external_account_id)
        ext = html.escape(a.external_account_id)
        items.append(
            "<label class='acct'>"
            f"<input type='checkbox' name='account' value='{ext}' {checked}>"
            f"<span class='an'>{name}</span><span class='ai'>{ext}</span></label>"
        )
    return (
        "<form class='acct-card' method='post' action='/accounts/select'>"
        f"<input type='hidden' name='platform' value='{html.escape(p.platform)}'>"
        "<div class='head'>"
        f"<strong>{html.escape(p.label)}</strong>"
        f"<span class='pill'>{p.selected_count}/{len(p.accounts)} syncing</span></div>"
        + "".join(items)
        + "<div class='save'><button class='btn sm' type='submit'>Save selection</button></div>"
        "</form>"
    )


def render_dashboard(user_label: str, platforms: list[PlatformView]) -> str:
    connected = [p for p in platforms if p.connected]
    if connected:
        main_body = "<h2>Select accounts to sync</h2>" + "".join(
            _account_form(p) for p in connected
        )
    else:
        main_body = (
            "<div class='empty'><div>"
            "<div style='font-size:18px;font-weight:700;color:var(--ink)'>No data sources yet</div>"
            "<p class='muted'>Connect Meta or Google Ads on the left to pull your ad data.</p>"
            "</div></div>"
        )
    body = (
        "<div class='shell'>"
        + _topnav(user_label)
        + "<div class='hero'><h1>Connect your ad data</h1>"
        "<p>Connect your ad platforms, choose the accounts to sync, and OudSeed turns "
        "them into dashboards and automatic AI performance reports.</p></div>"
        "<div class='grid'>"
        + _sidebar(platforms)
        + "<section class='panel main'>"
        + main_body
        + "</section></div></div>"
    )
    return render_page(body)
