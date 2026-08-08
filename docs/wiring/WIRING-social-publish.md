# WIRING-social-publish — C14 direct publish / scheduling to social platforms

> **Status:** ACTIVE

C14 was originally declined in [`../plans/v1.5/competitor-research.md`](../plans/v1.5/competitor-research.md)
(line 23: *"social scheduler/publish (needs cloud/OAuth → at most 'platform-ready export presets')"*),
and the substitute shipped: `sidecar/media_studio/features/export_presets.py` plus
`app/renderer/src/features/ExportPresetsPanel.tsx`. The owner overruled that decision, so C14 is
being built **on top of** the preset catalog rather than around it.

This document is the honest scope record: what each platform actually permits a
local desktop app to do, what is built, what is not built, and what only the owner
can do.

---

## 1. Per-platform feasibility (read from the platforms' own docs, 2026-08-08)

Reframe is a **local desktop app with no server and no public domain**. That single
constraint decides most of the table. Every row below is encoded as data in
`sidecar/media_studio/features/social_publish.py` (`CAPABILITIES`) with its source
URL attached, so the UI cannot offer a publish the platform would refuse.

| platform | personal account? | desktop loopback OAuth? | scheduling | verdict |
|---|---|---|---|---|
| **YouTube** | yes (personal channel) | yes — `http://127.0.0.1:<port>` + PKCE S256 | **native** (`status.publishAt`) | VIABLE-WITH-OWNER-ACTION |
| **TikTok** | yes | yes — desktop config allows only `localhost`/`127.0.0.1`, PKCE **required** | **none** — API has no scheduling parameter | VIABLE-WITH-OWNER-ACTION |
| **Instagram Reels** | **NO** | no | none | **NOT VIABLE** |
| **Facebook** | **NO** (personal timeline) / yes for a **Page** | no | native for a Page (`scheduled_publish_time`) | Page-only, needs a hosted callback |

Sources (each fetched directly):

- YouTube upload + audit restriction — <https://developers.google.com/youtube/v3/docs/videos/insert>
  ("All videos uploaded via the `videos.insert` endpoint from unverified API projects
  created after 28 July 2020 will be restricted to private viewing mode.")
- Google installed-app OAuth — <https://developers.google.com/identity/protocols/oauth2/native-app>
  (loopback `http://127.0.0.1:port` / `http://[::1]:port` for desktop; PKCE S256
  supported; the copy/paste **OOB** redirect "is no longer supported").
- TikTok Content Posting audit rule — <https://developers.tiktok.com/doc/content-posting-api-get-started>
  ("All content posted by unaudited clients will be restricted to private viewing mode.")
- TikTok **desktop** login — <https://developers.tiktok.com/doc/login-kit-desktop>
  ("Only `localhost` or loopback IP `127.0.0.1` are allowed host names in URI";
  "TikTok requires the Proof Key for Code Exchange (PKCE) protocol for desktop apps.")
  **This corrects the obvious assumption**: it is the *web* config
  (<https://developers.tiktok.com/doc/login-kit-web>) that requires `https`, and
  reading only that page would wrongly rule TikTok out for a desktop app.
- Instagram account-type requirement — <https://developers.facebook.com/docs/instagram-platform/overview>
  ("To use the APIs, your app users must have an **Instagram professional account**.")
  A personal/consumer account is not served by the API at all, so this is an
  account setting the user changes in the Instagram app — not something Reframe can
  engineer around. Content publishing additionally expires an unpublished media
  container after 24 h and caps publishing at 100 posts / 24 h
  (<https://developers.facebook.com/docs/instagram-platform/content-publishing>).
- Facebook personal-timeline publishing — the `publish_actions` permission was
  **removed on 2018-04-24** and is not granted to new apps, so posting to a user's
  own profile via the API is no longer possible. Page posts DO support
  `published=false` + `scheduled_publish_time`, bounded to "between 10 minutes and
  30 days from the time of the API request"
  (<https://developers.facebook.com/docs/pages-api/posts>).

### Why Instagram and Facebook get no stub

`instagram_reels` is present in the capability matrix **only** as a blocked row
carrying its reason, and `facebook_timeline` does not exist at all. Neither has an
entry in `app/main/socialAuth.ts` `OAUTH_ENDPOINTS`, because Meta's login does not
offer a loopback desktop redirect. Shipping endpoint constants we cannot complete
would be a stub that lies about being wired.

---

## 2. Scheduling honesty (the part a desktop app usually gets wrong)

A local app is **off when the machine is off**. `plan_schedule` therefore:

1. prefers handing a future publish time to the **platform** whenever the platform
   can hold it (YouTube `publishAt`, Facebook Page `scheduled_publish_time`) — that
   survives a powered-off laptop;
2. falls back to a **local queue** only when the platform has no scheduling API
   (TikTok), or when the requested time is beyond the platform's own documented
   horizon (Facebook's 30 days);
3. makes the fallback's disclosure structural: a `local-queue` plan always carries
   `requiresAppRunning: true` plus the verbatim `LOCAL_QUEUE_WARNING`, so a caller
   cannot render it without also receiving the sentence that says the post goes out
   when Reframe next runs, not at the chosen time.

`PublishQueueStore.due()` deliberately **excludes** platform-held rows, so a
natively-scheduled post is never also published by the local runner (a double-post).

---

## 3. Credentials — no new secret store

Social OAuth tokens live in the **existing** keystore, `app/main/keystore.ts`
(`safeStorage` → DPAPI/Keychain/libsecret), in a new `social` section of
`secure-keys.json`. No second store was introduced, no token is ever written to
`settings.json`, a log, a manifest, or the publish queue.

Two structural guarantees, each with a regression test:

- **The queue cannot hold a token.** A queue entry is assembled from the
  `ENTRY_FIELDS` **allowlist**, so an unrecognised (possibly secret-bearing) field
  cannot be persisted at all — `social_queue.py`, and the test that scans the
  persisted bytes in `sidecar/tests/test_social_queue.py`.
- **A provider write cannot wipe a social token.** `saveDecryptedKeys` REBUILDS the
  whole keystore document, so any section a caller forgets to copy forward is erased
  on the next write. `keyBridge.ts` funnels every non-provider section through one
  `withNonProviderSections` helper, replacing three inline ternaries where adding a
  second section would have silently destroyed it. Both directions are pinned in
  `app/main/socialTokens.test.ts`.

### Bring-your-own OAuth app

Every one of these platforms requires a **client secret** at the token exchange, and
a distributed desktop binary cannot embed a confidential secret (anyone can extract
it from the download). So Reframe does not ship credentials: the user registers
their own OAuth app and supplies its client id / secret, which are stored in the
same keystore. This is the only honest arrangement for a local app, and it also
means each user's quota and audit state is their own.

---

## 4. What is NOT built (residuals)

- **The loopback HTTP listener and the live token exchange.** `socialAuth.ts` provides
  the PKCE pair, the authorize URL, the callback parse, and the exchange body — all
  pure and fully unit-tested — but nothing here opens a socket yet.
- **The uploaders.** No YouTube resumable upload and no TikTok publish call is
  implemented, so `social.enqueue` records an intent that nothing yet performs.
- **A real OAuth round-trip has NOT been performed** (NOT-CHECKED): it requires a
  registered OAuth app, which is an owner action. Nothing in this feature has been
  proven end-to-end against a live platform, and no claim here should be read as
  saying otherwise.

---

## 5. OWNER ACTIONS (only the owner can do these)

1. **YouTube** — create a Google Cloud project, enable the YouTube Data API v3,
   create an OAuth client of type **Desktop app**, and (to lift the forced-private
   restriction) submit the project for YouTube's **API audit**. Until the audit
   passes, every upload is private.
2. **TikTok** — register a TikTok developer app, add the **Content Posting API** and
   **Login Kit** products, configure a `http://127.0.0.1:*/oauth/callback` desktop
   redirect, request the `video.publish` scope, and submit the app for **audit**.
   Until audited, all posts are `SELF_ONLY`.
3. **Instagram** (optional, and only if wanted) — convert the Instagram account to a
   **professional** (Business or Creator) account, then create a Meta app and pass
   **App Review** for `instagram_content_publish`. Reframe still cannot host the
   https callback Meta requires, so this needs a hosted redirect the owner runs.
4. **Facebook Page** (optional) — create a Meta app and pass **App Review** for
   `pages_manage_posts`; same hosted-callback requirement.
5. **Decide whether the Meta platforms are worth a hosted callback at all.** If not,
   YouTube + TikTok are the two Reframe can support purely locally.
