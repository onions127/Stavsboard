# Stavsboard on the phone: installable app (rough plan)

Status: draft outline, 2026-11-12. Not yet reviewed.

## Goal

Open Stavsboard from a home-screen icon on the phone and get a full-screen app: no address
bar, no tabs, no typing a URL. Same calm dashboard, same data, same read-only rules.

## Recommendation: make the existing page an installable web app (PWA)

The dashboard is now served over HTTPS at `https://sterver.<tailnet>.ts.net:8443` (Tailscale
Serve, see `--allow-host`). HTTPS is the one hard requirement for installing a web app, so
the phone can "Add to Home Screen" / "Install app" and launch it like a native app.

| Option | Effort | What you get | Why not (for now) |
|---|---|---|---|
| **PWA** (chosen) | ~1 day | Home-screen icon, full-screen launch, own app-switcher entry, splash in Stavsboard colors, works on Android and iPhone, updates automatically with each Stavsboard version | No home-screen widget; notifications are a separate, later step |
| Wrapper (Capacitor, or an Android TWA via Bubblewrap) | 2-3 days + upkeep | Real APK, possible Play Store listing | Same web UI inside, plus signing, sideloading and a second release process; gains little over a PWA for one user |
| Native app (Expo / React Native, Kotlin, Swift) | 1-3 weeks | Widgets, native feel, background refresh | Rebuilds the whole UI and the design system a second time; two codebases drift apart |

Nothing on the server changes in how it collects data, and no new dependency is needed.

## Phase 1: installable app (the work)

Server (`src/stavsboard/`):

1. **`static/manifest.webmanifest`**: `name` "Stavsboard", `short_name` "Stavsboard",
   `start_url` "/", `scope` "/", `display` "standalone", `background_color` `#E3E7E1`
   (ground), `theme_color` `#E3E7E1`, icons 192, 512 and a 512 maskable.
2. **Icons** in `static/icons/`: a simple mark on `ground` with `good` green, per DESIGN.md
   (needs a design pass; ask before inventing a new brand mark). Android-specific: the
   **maskable** icon is the one the launcher actually shows (adaptive icon shapes), so its mark
   must sit inside the central 80% safe zone; add a **monochrome** icon so Android 13+ themed
   icons render it in the wallpaper color instead of a white blob.
3. **App shortcuts** in the manifest: long-press the icon for "Trends" (`/?tab=trends`), if
   the page can open on a tab from the URL (small `app.js` change).
4. **`index.html` head**: link the manifest; `theme-color` meta twice, one per
   color scheme (`#E3E7E1` light, `#181C1E` dark); `viewport-fit=cover` so the page can sit
   under the notch.
5. **Service worker at `/sw.js`** (new route in `app.py`, `Cache-Control: no-cache`, served
   from the root so its scope covers `/`). It caches only the app shell (index, css, js, fonts,
   icons) so the app opens instantly. It never caches `/api/*`: stale numbers would be lying.
   Bump a cache version string per release so updates land on the next launch.
6. **Content-Type**: serve the manifest as `application/manifest+json`.
7. **CSP check**: current `default-src 'self'` already covers `manifest-src` and
   `worker-src`; confirm in the browser, no loosening.

Client (`static/app.js`, `app.css`):

8. **Pause polling when hidden, refresh on return** (`visibilitychange`). Today polling only
   slows when the phone throttles it; a reopened app should show fresh data at once, not
   after a timeout.
9. **Unreachable state copy**: the existing `disconnected` state should say what a phone
   user can fix, e.g. "Can't reach sterver. Is Tailscale on?"
10. **Safe areas**: pad the header and bottom with `env(safe-area-inset-*)` in standalone mode.
11. **No install prompt banner.** Installing is a one-time step from the browser menu; a
    nagging button doesn't fit "calm". README explains it instead.

Tests:

- TestClient: `/static/manifest.webmanifest` content type and required fields; `/sw.js`
  headers and that it is still behind the Host guard (400 for a foreign Host).
- Wheel test: icons and manifest ship in the wheel (extend the existing C2 test).
- Manual on the Android phone: install from Chrome, launch from icon (no browser chrome,
  own entry in Recents and the app drawer), themed icon on, rotate, dark mode, back
  gesture on the first screen (should leave the app, not reload), Tailscale off
  (unreachable message), Tailscale back on (recovers by itself), new Stavsboard version
  (picked up on next launch).
- Chrome DevTools on the PC (Application > Manifest, Lighthouse "Installable") over USB
  remote debugging, to catch manifest mistakes before trying the phone.

Docs: README section "Put it on your Android phone":

1. Turn on Tailscale on the phone (tip: Android Settings > Network > VPN > Tailscale >
   Always-on VPN, so the app never opens to "Can't reach sterver").
2. Open the Serve URL **in Chrome** and choose menu > **Install app**. Chrome installs it as
   a real Android app (a WebAPK): app-drawer entry, App info page, own icon in Recents.
   Other browsers (Opera, Firefox) may only add a home-screen shortcut that opens in the
   browser, so Chrome is the one to use for the install, even if Opera stays the daily browser.
3. Uninstall like any app.

## Phase 2 (optional, later): alerts

Only if wanted after living with Phase 1. Two routes:

- **ntfy / Pushover from the server**: Stavsboard (or a tiny sidecar) posts a message when
  status turns amber/red. Simple, works when the app is closed. Needs an outbound HTTP call
  and a config value, which breaks "no config file in v1", so it needs a decision.
- **Web Push in the PWA**: no third party, but needs VAPID keys, a subscription store and a
  new write endpoint. Works well on Android Chrome, including when the app is closed. More
  code and more attack surface for a no-login app.

Later still, if a Play Store listing or a home-screen widget is ever wanted: wrap the same PWA
as a Trusted Web Activity (Bubblewrap). Widgets would need native Android code.

## Open questions

- Platform: **Android** (decided 2026-11-12). Install via Chrome; no iPhone-specific work.
- Icon: reuse an existing mark, or design one with /design-consultation?
- Deploy first: sterver must actually be on the pinned `--allow-host` build behind Serve
  (port 8420 was still on `0.0.0.0` at last check).
