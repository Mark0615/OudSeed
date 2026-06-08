"""Server-rendered HTML views — Shopify-admin-style app shell.

Layout: a dark top bar (white logo, a white progress stepper, account menu), a
light left nav sidebar (Home / Connections / Reports / Settings), and a main
content area that hosts the connect flow (data-source cards, account selection,
Preview data).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

from src.web.preview import PreviewData, PreviewWindow

_ASSETS_DIR = Path(__file__).resolve().parents[2] / "frontend" / "prototype" / "assets"

PLATFORM_SLUGS = {"meta_ads": "meta", "google_ads": "google-ads"}
PLATFORM_LABELS = {
    "meta_ads": "Meta Ads",
    "google_ads": "Google Ads",
    "instagram": "Instagram",
    "ga4": "Google Analytics 4",
    "line_ads": "LINE Ads",
}
# Brand logo files served from /assets (frontend/prototype/assets).
PLATFORM_ICON_FILE = {
    "meta_ads": "icon-meta.png",
    "google_ads": "icon-google-ads.png",
    "instagram": "icon-instagram.png",
    "ga4": "icon-ga4.png",
    "line_ads": "icon-line.png",
}
COMING_SOON = ("instagram", "ga4", "line_ads")

# Customer-facing export destinations: (kind, label, description).
DESTINATIONS = (
    ("bigquery", "BigQuery", "Send your data to a BigQuery dataset."),
    ("data_studio", "Data Studio", "Build dashboards in Google Data Studio."),
    ("google_sheets", "Google Sheets", "Export your data into a Google Sheet."),
)
# Brand logos auto-used when present in /assets; otherwise a letter tile shows.
DESTINATION_ICON_FILE = {
    "bigquery": "icon-bigquery.png",
    "data_studio": "icon-datastudio.png",
    "google_sheets": "icon-google_sheet.png",
}
_DEST_FALLBACK = {
    "bigquery": ("BQ", "#669df6"),
    "data_studio": ("DS", "#4285f4"),
    "google_sheets": ("GS", "#0f9d58"),
}

# Minimal inline SVG nav icons (Lucide-style, currentColor).
_ICONS = {
    "home": "<path d='M3 10.5 12 4l9 6.5'/><path d='M5 9.5V20h14V9.5'/>",
    "plug": "<path d='M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0z'/><path d='M12 16v5'/>",
    "report": "<path d='M4 20V4M4 20h16M8 16v-5M13 16V8M18 16v-3'/>",
    "settings": "<circle cx='12' cy='12' r='3'/><path d='M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 0 0-1.7-1L14.5 3h-5l-.4 2.6a7 7 0 0 0-1.7 1l-2.3-1-2 3.4L3.1 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 1.7 1l.4 2.6h5l.4-2.6a7 7 0 0 0 1.7-1l2.3 1 2-3.4-2-1.5a7 7 0 0 0 .1-1z'/>",
}


@dataclass(frozen=True)
class AccountView:
    external_account_id: str
    account_name: str
    selected: bool


@dataclass(frozen=True)
class DestinationView:
    """Current onboarding destination config, for prefilling the form."""

    configured: bool = False
    selected: tuple[str, ...] = ()  # selected export destination kinds
    email_enabled: bool = False
    report_type: str = "monthly"
    delivery_day: str = "1"
    depth: str = "standard"
    email_to: str = ""
    timezone: str = "Asia/Taipei"


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
    def connected(self) -> bool:
        return len(self.accounts) > 0

    @property
    def selected_count(self) -> int:
        return sum(1 for a in self.accounts if a.selected)


_CSS = """
:root{--ink:#10141a;--muted:#69748a;--line:#e4e8ee;--bg:#f6f7f9;
  --slate:#3a4b63;--slate-deep:#26344a;--slate-soft:#eef2f7;--green:#2f8568;--green-soft:#e6f3ed;
  --bar:#171b22;--nav:#fbfcfd;--radius:14px;--shadow:0 1px 2px rgba(16,20,26,.06),0 8px 24px rgba(16,20,26,.05);}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;min-height:100dvh;background:var(--bg);color:var(--ink);
  font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
/* Top bar (dark) */
.topbar{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:18px;
  background:var(--bar);color:#fff;padding:0 18px;height:56px}
.topbar .logo img{height:26px;display:block}
/* Top-bar progress stepper (white text + white lines) */
.topbar .flow{flex:1;display:flex;align-items:center;justify-content:center;gap:0;min-width:0}
.fstep{display:flex;align-items:center;gap:8px;color:#828b9b;white-space:nowrap}
.fstep .fn{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;line-height:1;
  border:1.5px solid #39414f;font-size:11.5px;font-weight:700}
.fstep .ft{font-size:13px;font-weight:600}
.fstep.active{color:#fff}
.fstep.active .fn{border-color:#fff;color:#fff}
.fstep.done{color:#dfe3ea}
.fstep.done .fn{border-color:#fff;background:#fff;color:var(--bar)}
.fline{width:38px;height:1.5px;background:#39414f;margin:0 12px;flex:0 0 auto}
.fline.done{background:#fff}
.topbar .acct{display:flex;align-items:center;gap:9px}
.topbar .acct .nm{font-size:13.5px;color:#e6e9ee;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.topbar .avatar{width:30px;height:30px;border-radius:7px;display:grid;place-items:center;
  background:linear-gradient(135deg,#5566d6,#7d4fd6);color:#fff;font-weight:700;font-size:13px}
.topbar form{margin:0}
.linkbtn{background:none;border:0;color:#aab2c0;cursor:pointer;font-size:12.5px;padding:4px}
.linkbtn:hover{color:#fff}
/* App body: nav + main */
.app{display:grid;grid-template-columns:228px minmax(0,1fr);min-height:calc(100dvh - 56px)}
.nav{background:var(--nav);border-right:1px solid var(--line);padding:14px 12px}
.nav a{display:flex;align-items:center;gap:11px;padding:9px 11px;border-radius:9px;color:#3b4453;
  font-weight:600;font-size:14px;margin-bottom:2px}
.nav a svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.nav a:hover{background:#f0f2f5}
.nav a.active{background:var(--slate);color:#fff}
.nav .grp{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin:16px 11px 8px}
/* Main */
.main{padding:28px 34px;max-width:1180px}
h1{font-size:27px;letter-spacing:-.02em;margin:0 0 6px}
.sub{color:var(--muted);margin:0 0 24px;font-size:15px;line-height:1.5;max-width:600px}
.sec{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin:26px 2px 12px}
/* Data source cards */
.sources{display:grid;grid-template-columns:repeat(auto-fit,minmax(176px,1fr));gap:12px}
.scard{background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:16px;box-shadow:var(--shadow)}
.scard.soon{opacity:.55}
.scard .top{display:flex;align-items:center;gap:11px;margin-bottom:12px}
.tile{width:42px;height:42px;border-radius:10px;display:grid;place-items:center;flex:0 0 auto;
  background:#fff;border:1px solid var(--line);overflow:hidden}
.tile img{width:100%;height:100%;object-fit:contain;padding:5px}
.tile.fallback{background:#eef2f7;color:var(--slate);font-weight:800;font-size:18px;border-color:transparent}
.scard .nm{font-weight:700}
.scard .st{font-size:12.5px;color:var(--muted)}.scard .st.ok{color:var(--green);font-weight:700}
.btn{display:inline-block;border:0;cursor:pointer;font-weight:700;font-size:13.5px;text-align:center;
  background:linear-gradient(135deg,#415471,#29384f);color:#fff;padding:9px 15px;border-radius:9px;box-shadow:0 6px 14px rgba(38,52,74,.18)}
.btn.ghost{background:#fff;color:var(--slate-deep);border:1px solid var(--line);box-shadow:none}
.btn.sm{padding:7px 13px;font-size:13px}.btn.block{display:block;width:100%}
/* Account selection */
.acct-card{background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px;margin-bottom:14px;box-shadow:var(--shadow)}
.acct-card .head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;gap:12px;flex-wrap:wrap}
.acct-card .head strong{font-size:15px}
.head-right{display:flex;align-items:center;gap:14px}
.selall{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:600;color:var(--slate-deep);cursor:pointer;user-select:none}
.selall input{width:17px;height:17px;accent-color:var(--slate)}
.pill{font-size:12px;font-weight:700;color:var(--green);background:var(--green-soft);border:1px solid #cfe8dc;border-radius:999px;padding:4px 10px}
.acct{display:flex;align-items:center;gap:12px;padding:10px 2px;border-top:1px solid #f0f2f6}
.acct input{width:18px;height:18px;accent-color:var(--slate)}
.acct .an{font-weight:600;font-size:14px}.acct .ai{color:var(--muted);font-size:12.5px;margin-left:auto}
.save{margin-top:12px;display:flex;justify-content:flex-end}
.preview{background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:20px;box-shadow:var(--shadow)}
.preview .head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px;flex-wrap:wrap}
.preview h3{margin:0;font-size:16px}
.range{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}
.range a{padding:7px 13px;font-size:13px;font-weight:700;color:var(--muted);background:#fff}
.range a.active{background:var(--slate-soft);color:var(--slate-deep)}
.range button{padding:7px 13px;font-size:13px;font-weight:700;color:var(--muted);background:#fff;border:0;cursor:pointer;font-family:inherit}
.range button.active{background:var(--slate-soft);color:var(--slate-deep)}
.pv-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(136px,1fr));gap:12px;margin:14px 0 4px}
.pv-tile{border:1px solid var(--line);border-radius:11px;padding:13px 14px;background:#fbfcfd}
.pv-tile .k{font-size:12px;color:var(--muted);font-weight:600}
.pv-tile .v{font-size:21px;font-weight:800;letter-spacing:-.01em;margin-top:4px}
.pv-table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
.pv-table th{text-align:left;color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.05em;padding:8px 10px;border-bottom:1px solid var(--line)}
.pv-table td{padding:9px 10px;border-bottom:1px solid var(--line)}
.pv-table th.num,.pv-table td.num{text-align:right;font-variant-numeric:tabular-nums}
.pv-plat{display:inline-block;font-size:11px;font-weight:700;color:var(--slate-deep);background:var(--slate-soft);border-radius:6px;padding:2px 7px}
.head-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.banner{border-radius:11px;padding:12px 15px;margin:0 0 18px;font-size:14px;font-weight:600;border:1px solid}
.banner.ok{background:var(--green-soft);border-color:#bfe3d3;color:#1f6b51}
.banner.warn{background:#fff5e6;border-color:#f2d9a8;color:#8a5a12}
.banner.error{background:#fdeeee;border-color:#f3c9c9;color:#a23434}
.note{color:var(--muted);font-size:13.5px;line-height:1.5;margin:6px 0 0}
/* Choose destination */
.dest-card{background:#fff;border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px;margin-bottom:14px;box-shadow:var(--shadow)}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin:6px 0}
.dchoice{display:flex;align-items:flex-start;gap:11px;border:1.5px solid var(--line);border-radius:12px;padding:13px 14px;cursor:pointer}
.dchoice:hover{border-color:#cfd6e0}
.dchoice:has(input:checked){border-color:var(--slate);background:var(--slate-soft)}
.dchoice input{margin-top:3px;width:18px;height:18px;accent-color:var(--slate);flex:0 0 auto}
.dchoice .tile{width:34px;height:34px;border-radius:8px}
.dchoice .dnm{font-weight:700;font-size:14px}
.dchoice .dds{font-size:12px;color:var(--muted);margin-top:2px;line-height:1.4}
.ai-block{border-top:1px solid var(--line);margin-top:14px;padding-top:14px}
.ai-block .head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.ai-block .head strong{font-size:15px}
.dest-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-top:12px}
.dest-grid label{display:flex;flex-direction:column;gap:6px;font-size:13px;font-weight:600;color:var(--slate-deep)}
.dest-grid input,.dest-grid select{font:inherit;font-weight:500;padding:9px 11px;border:1px solid var(--line);border-radius:9px;background:#fff;color:var(--ink)}
.dest-grid input:focus,.dest-grid select:focus{outline:none;border-color:var(--slate);box-shadow:0 0 0 3px rgba(58,75,99,.12)}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden;width:max-content}
.seg-opt{padding:8px 16px;font-size:13px;font-weight:700;color:var(--muted);cursor:pointer;background:#fff}
.seg-opt.active{background:var(--slate-soft);color:var(--slate-deep)}
.seg-opt input{position:absolute;opacity:0;pointer-events:none}
.signin{max-width:430px;margin:11vh auto 0;text-align:center;background:#fff;border:1px solid var(--line);
  border-radius:18px;box-shadow:var(--shadow);padding:44px}
.signin img{height:120px;margin-bottom:14px}.muted{color:var(--muted);line-height:1.55}
@media(max-width:1080px){.fstep .ft{display:none}.fline{width:26px;margin:0 9px}}
@media(max-width:860px){.app{grid-template-columns:1fr}.nav{display:none}.topbar .flow{display:none}}
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
        "<div class='signin-wrap'><main class='signin'>"
        "<img src='/assets/oudseed-logo.png' alt='OudSeed'>"
        "<h1 style='font-size:24px;margin:0 0 10px'>Connect your ad data</h1>"
        "<p class='muted'>Sign in to connect Meta and Google Ads and get automatic "
        "AI performance reports.</p>"
        "<p style='margin-top:18px'><a class='btn' href='/auth/google/login'>Sign in with Google</a></p>"
        "</main></div>"
    )
    return render_page(body)


def _flow(current: int) -> str:
    labels = ["Connect source", "Select accounts", "Preview data", "Choose destination", "Done"]
    parts = []
    for i, label in enumerate(labels, start=1):
        state = "done" if i < current else ("active" if i == current else "")
        mark = "✓" if i < current else str(i)
        parts.append(
            f"<div class='fstep {state}'><span class='fn'>{mark}</span>"
            f"<span class='ft'>{html.escape(label)}</span></div>"
        )
        if i < len(labels):
            parts.append(f"<span class='fline {'done' if i < current else ''}'></span>")
    return "<div class='flow'>" + "".join(parts) + "</div>"


def render_connect_error(platform_label: str, reason: str) -> str:
    """A friendly error page when an ad-platform connect fails (no raw 500)."""
    body = (
        "<div class='signin-wrap'><main class='signin'>"
        "<img src='/assets/oudseed-logo.png' alt='OudSeed'>"
        f"<h1 style='font-size:22px;margin:0 0 10px'>Couldn't connect {html.escape(platform_label)}</h1>"
        f"<p class='muted'>{html.escape(reason)}</p>"
        "<p style='margin-top:18px'><a class='btn' href='/'>Back to dashboard</a></p>"
        "</main></div>"
    )
    return render_page(body, title="Connection error")


def _topbar(user_email: str, current_step: int) -> str:
    initial = html.escape(user_email[:1].upper() or "U")
    name = html.escape(user_email)
    return (
        "<header class='topbar'>"
        "<a class='logo' href='/'><img src='/assets/oudseed-horizontal-white.png' alt='OudSeed'></a>"
        + _flow(current_step)
        + "<div class='acct'>"
        f"<span class='nm'>{name}</span><span class='avatar'>{initial}</span>"
        "<form method='post' action='/auth/logout'><button class='linkbtn' type='submit'>Sign out</button></form>"
        "</div></header>"
    )


def _nav() -> str:
    def item(icon: str, label: str, active: bool = False) -> str:
        cls = " class='active'" if active else ""
        return f"<a{cls} href='#'><svg viewBox='0 0 24 24'>{_ICONS[icon]}</svg>{html.escape(label)}</a>"

    return (
        "<nav class='nav'>"
        + item("home", "Home")
        + item("plug", "Connections", active=True)
        + item("report", "Reports")
        + "<div class='grp'>Account</div>"
        + item("settings", "Settings")
        + "</nav>"
    )


def _tile(platform: str) -> str:
    icon = PLATFORM_ICON_FILE.get(platform)
    if icon:
        label = html.escape(PLATFORM_LABELS.get(platform, platform))
        return f"<div class='tile'><img src='/assets/{icon}' alt='{label}'></div>"
    return "<div class='tile fallback'>•</div>"


def _source_cards(platforms: list[PlatformView]) -> str:
    cards = []
    for p in platforms:
        if p.connected:
            st = f"<div class='st ok'>Connected · {p.selected_count}/{len(p.accounts)} syncing</div>"
            action = f"<a class='btn ghost sm block' href='/connect/{p.slug}/start'>Reconnect</a>"
        else:
            st = "<div class='st'>Not connected</div>"
            action = f"<a class='btn sm block' href='/connect/{p.slug}/start'>Connect</a>"
        cards.append(
            f"<div class='scard'><div class='top'>{_tile(p.platform)}"
            f"<div><div class='nm'>{html.escape(p.label)}</div>{st}</div></div>{action}</div>"
        )
    for platform in COMING_SOON:
        cards.append(
            f"<div class='scard soon'><div class='top'>{_tile(platform)}"
            f"<div><div class='nm'>{html.escape(PLATFORM_LABELS[platform])}</div>"
            "<div class='st'>Coming soon</div></div></div></div>"
        )
    return "<div class='sources'>" + "".join(cards) + "</div>"


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
    all_selected = "checked" if p.accounts and p.selected_count == len(p.accounts) else ""
    return (
        "<form class='acct-card' method='post' action='/accounts/select'>"
        f"<input type='hidden' name='platform' value='{html.escape(p.platform)}'>"
        "<div class='head'>"
        f"<strong>{html.escape(p.label)}</strong>"
        "<div class='head-right'>"
        "<label class='selall'>"
        f"<input type='checkbox' onclick='oudToggleAll(this)' {all_selected}>Select all</label>"
        f"<span class='pill'>{p.selected_count}/{len(p.accounts)} syncing</span></div></div>"
        + "".join(items)
        + "<div class='save'><button class='btn sm' type='submit'>Save selection</button></div></form>"
    )


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _intf(value: int) -> str:
    return f"{int(value):,}"


def _convf(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def _preview_window(win: PreviewWindow, *, window_id: str, hidden: bool) -> str:
    tiles = (
        "<div class='pv-tiles'>"
        f"<div class='pv-tile'><div class='k'>Spend</div><div class='v'>{_money(win.spend)}</div></div>"
        f"<div class='pv-tile'><div class='k'>Impressions</div><div class='v'>{_intf(win.impressions)}</div></div>"
        f"<div class='pv-tile'><div class='k'>Clicks</div><div class='v'>{_intf(win.clicks)}</div></div>"
        f"<div class='pv-tile'><div class='k'>Conversions</div><div class='v'>{_convf(win.conversions)}</div></div>"
        "</div>"
    )
    rows = []
    for c in win.top_campaigns:
        plat = PLATFORM_LABELS.get(c.platform, c.platform or "—")
        rows.append(
            "<tr>"
            f"<td><span class='pv-plat'>{html.escape(plat)}</span></td>"
            f"<td>{html.escape(c.campaign_name)}</td>"
            f"<td class='num'>{_money(c.spend)}</td>"
            f"<td class='num'>{_intf(c.impressions)}</td>"
            f"<td class='num'>{_intf(c.clicks)}</td>"
            f"<td class='num'>{_convf(c.conversions)}</td></tr>"
        )
    table = ""
    if rows:
        table = (
            "<table class='pv-table'><thead><tr>"
            "<th>Platform</th><th>Top campaigns</th><th class='num'>Spend</th>"
            "<th class='num'>Impr.</th><th class='num'>Clicks</th><th class='num'>Conv.</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        )
    return f"<div class='pv-win' id='{window_id}'{' hidden' if hidden else ''}>{tiles}{table}</div>"


def _preview_section(preview: PreviewData | None = None) -> str:
    head = (
        "<div class='preview'><div class='head'><h3>Preview data</h3>"
        "<div class='head-actions'>"
        "<span class='range'>"
        "<button type='button' class='active' data-days='7' onclick='oudPreviewTab(7)'>Last 7 days</button>"
        "<button type='button' data-days='30' onclick='oudPreviewTab(30)'>Last 30 days</button>"
        "</span>"
        "<form method='post' action='/sync/run' style='margin:0'>"
        "<button class='btn sm' type='submit'>Run first sync</button></form>"
        "</div></div>"
    )
    if preview is None or not preview.has_data:
        return (
            head + "<p class='note'>Confirm your selected accounts are pulling data "
            "correctly. A preview of recent spend and top campaigns appears here once "
            "your first sync has run.</p></div>"
        )
    body = (
        _preview_window(preview.short, window_id="pv-7", hidden=False)
        + _preview_window(preview.long, window_id="pv-30", hidden=True)
    )
    return head + body + "</div>"


_DEPTH_OPTIONS = (("standard", "Standard"), ("brief", "Brief"), ("deep", "Deep"))
_TZ_OPTIONS = ("Asia/Taipei", "America/Los_Angeles", "Europe/Berlin")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday")


def _options(pairs, selected: str) -> str:
    out = []
    for value, label in pairs:
        sel = " selected" if value == selected else ""
        out.append(f"<option value='{html.escape(value)}'{sel}>{html.escape(label)}</option>")
    return "".join(out)


def _dest_tile(kind: str) -> str:
    icon = DESTINATION_ICON_FILE.get(kind)
    if icon and (_ASSETS_DIR / icon).exists():
        return f"<div class='tile'><img src='/assets/{icon}' alt=''></div>"
    letter, color = _DEST_FALLBACK.get(kind, ("•", "#69748a"))
    return (
        f"<div class='tile fallback' style='background:{color};color:#fff;"
        f"border-color:transparent'>{html.escape(letter)}</div>"
    )


def _destinations_section(dest: DestinationView) -> str:
    cards = []
    for kind, label, desc in DESTINATIONS:
        checked = "checked" if kind in dest.selected else ""
        cards.append(
            "<label class='dchoice'>"
            f"<input type='checkbox' name='destination' value='{kind}' {checked}>"
            f"{_dest_tile(kind)}"
            f"<div><div class='dnm'>{html.escape(label)}</div>"
            f"<div class='dds'>{html.escape(desc)}</div></div></label>"
        )

    is_weekly = dest.report_type == "weekly"
    monthly_day = dest.delivery_day if (not is_weekly and dest.delivery_day.isdigit()) else "1"
    weekly_day = dest.delivery_day if is_weekly else "monday"
    email_checked = "checked" if dest.email_enabled else ""
    fields_hidden = "" if dest.email_enabled else " hidden"
    m_checked = "" if is_weekly else "checked"
    w_checked = "checked" if is_weekly else ""
    # Only offer the test send once a recipient has actually been saved. The
    # button reuses this same form but posts to /reports/send-now via formaction,
    # so it sends with the saved settings (it ignores the unsaved field edits).
    test_send = (
        "<button class='btn sm ghost' type='submit' formaction='/reports/send-now'>"
        "寄送測試報告</button>"
        if (dest.email_enabled and dest.email_to)
        else ""
    )

    return (
        "<form class='dest-card' method='post' action='/destination/save'>"
        "<p class='note' style='margin-top:0'>Pick where your data should land — we sync it "
        "for you and deliver it to each destination you choose.</p>"
        "<div class='dgrid'>" + "".join(cards) + "</div>"
        "<div class='ai-block'><div class='head'><strong>AI report email</strong>"
        "<label class='selall'><input type='checkbox' name='enabled' "
        f"onclick='oudEmailToggle(this)' {email_checked}> Email me reports</label></div>"
        "<p class='note'>Get an AI performance report by email on your schedule.</p>"
        f"<div class='dest-grid' id='email-fields'{fields_hidden}>"
        "<label>Report cadence<span class='seg'>"
        f"<label class='seg-opt {'' if is_weekly else 'active'}'>"
        f"<input type='radio' name='report_type' value='monthly' {m_checked} "
        "onclick=\"oudCadence('monthly')\">Monthly</label>"
        f"<label class='seg-opt {'active' if is_weekly else ''}'>"
        f"<input type='radio' name='report_type' value='weekly' {w_checked} "
        "onclick=\"oudCadence('weekly')\">Weekly</label></span></label>"
        f"<label id='f-monthly'{' hidden' if is_weekly else ''}>Monthly delivery day"
        f"<input type='number' name='monthly_day' min='1' max='28' value='{html.escape(monthly_day)}'></label>"
        f"<label id='f-weekly'{'' if is_weekly else ' hidden'}>Weekly delivery day"
        f"<select name='weekly_day'>{_options([(d, d.capitalize()) for d in _WEEKDAYS], weekly_day)}</select></label>"
        f"<label>Report depth<select name='depth'>{_options(_DEPTH_OPTIONS, dest.depth)}</select></label>"
        f"<label>Recipient email<input type='email' name='email_to' "
        f"value='{html.escape(dest.email_to)}' placeholder='you@example.com'></label>"
        f"<label>Timezone<select name='timezone'>{_options([(t, t) for t in _TZ_OPTIONS], dest.timezone)}</select></label>"
        "</div></div>"
        "<div class='save'><button class='btn sm' type='submit'>Save destination</button>"
        + test_send
        + "</div></form>"
    )


def _current_step(platforms: list[PlatformView], has_destination: bool) -> int:
    connected = any(p.connected for p in platforms)
    selected = any(p.selected_count > 0 for p in platforms)
    if not connected:
        return 1
    if not selected:
        return 2
    if not has_destination:
        return 3  # reviewing preview + choosing destination
    return 5  # destination configured → done


_PAGE_JS = (
    "<script>"
    "function oudToggleAll(cb){var f=cb.closest('form');if(!f)return;"
    "f.querySelectorAll(\"input[name='account']\").forEach(function(x){x.checked=cb.checked;});}"
    "function oudCadence(t){var m=document.getElementById('f-monthly'),w=document.getElementById('f-weekly');"
    "if(m)m.hidden=(t!=='monthly');if(w)w.hidden=(t!=='weekly');"
    "document.querySelectorAll('.seg-opt').forEach(function(o){var r=o.querySelector('input');"
    "o.classList.toggle('active',!!(r&&r.checked));});}"
    "function oudEmailToggle(cb){var f=document.getElementById('email-fields');if(f)f.hidden=!cb.checked;}"
    "function oudPreviewTab(d){var a=document.getElementById('pv-7'),b=document.getElementById('pv-30');"
    "if(a)a.hidden=(d!==7);if(b)b.hidden=(d!==30);"
    "document.querySelectorAll('.preview .range button').forEach(function(x){"
    "x.classList.toggle('active',x.getAttribute('data-days')===String(d));});}"
    "document.addEventListener('change',function(e){var t=e.target;"
    "if(!t||t.name!=='account')return;var f=t.closest('form');if(!f)return;"
    "var boxes=f.querySelectorAll(\"input[name='account']\");"
    "var master=f.querySelector('.selall input');if(!master)return;"
    "master.checked=boxes.length>0&&Array.prototype.every.call(boxes,function(b){return b.checked;});});"
    "</script>"
)


def _banner(notice: dict | None) -> str:
    if not notice:
        return ""
    kind = notice.get("kind", "ok")
    if kind not in {"ok", "warn", "error"}:
        kind = "ok"
    return f"<div class='banner {kind}'>{html.escape(str(notice.get('text', '')))}</div>"


def render_dashboard(
    user_email: str,
    platforms: list[PlatformView],
    destination: DestinationView | None = None,
    preview: PreviewData | None = None,
    notice: dict | None = None,
) -> str:
    dest = destination or DestinationView()
    connected = [p for p in platforms if p.connected]
    has_selection = any(p.selected_count > 0 for p in platforms)

    main = [
        _banner(notice),
        "<h1>Connect your ad data</h1>",
        "<p class='sub'>Link your ad platforms, choose the accounts to sync, and OudSeed "
        "turns them into dashboards and automatic AI performance reports.</p>",
        "<div class='sec'>Data sources</div>",
        _source_cards(platforms),
    ]
    if connected:
        main.append("<div class='sec'>Select accounts to sync</div>")
        main.extend(_account_form(p) for p in connected)
        if has_selection:
            main.append("<div class='sec'>Preview</div>")
            main.append(_preview_section(preview))
            main.append("<div class='sec'>Choose destination</div>")
            main.append(_destinations_section(dest))

    body = (
        _topbar(user_email, _current_step(platforms, dest.configured))
        + "<div class='app'>"
        + _nav()
        + "<main class='main'>"
        + "".join(main)
        + "</main></div>"
        + _PAGE_JS
    )
    return render_page(body)
