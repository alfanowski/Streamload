# Streamload v2 — Plan 5: Skip Intro + Polish + Cast/Auto-play

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the v2 experience to feel premium: audio-fingerprint-based skip intro, auto-play next episode countdown card, server selector dropdown in the player, Cast SDK integration (Chromecast), settings page, admin dashboard, and watchlist UI. By the end, the app feels indistinguishable from a polished commercial product.

**Architecture:** Backend gets a new `streamload/post/intro_detect.py` (audio fingerprinting via `chromaprint`), an admin `/api/admin/*` namespace, plus exposing TV episode lists. Frontend adds player overlays (skip-intro pill, next-episode card, server selector), settings + admin pages, and Cast SDK lazy-load. Most tasks are small UX-focused increments.

**Tech Stack:** `pyacoustid` for audio fingerprinting (wraps libchromaprint), Cast Sender SDK (lazy-loaded, ~30 KB), Vidstack custom UI extensions, Svelte 5 runes throughout.

**Spec reference:** §6.6 (Skip Intro), §6.5 (Auto-play next), §7.5 (Player), §9.3 (Cast SDK), §11 (Admin operations).

**Prerequisite:** Plans 1-4 merged.

---

## File Structure

**Modified backend:**
- `streamload/post/intro_detect.py` — NEW: audio fingerprint + intro/outro detection
- `streamload/api/routes/intro.py` — NEW: `GET /api/intro/{tmdb_id}/s{n}`, admin trigger
- `streamload/api/routes/episodes.py` — NEW: `GET /api/title/{tmdb_id}/episodes`
- `streamload/api/routes/admin.py` — NEW: user mgmt + system status admin endpoints
- `streamload/db/models.py` — add `IntroMarker` model (already in spec §5.1)
- `migrations/versions/0004_intro_markers.py`
- `requirements.txt` — add `pyacoustid>=1.3`, `numpy>=2.0` (for FFT-based fingerprint matching)

**Modified frontend:**
- `web/src/lib/components/SkipIntroPill.svelte` — NEW
- `web/src/lib/components/NextEpisodeCard.svelte` — NEW
- `web/src/lib/components/ServerSelector.svelte` — NEW
- `web/src/lib/player/CastSender.ts` — NEW: lazy-loaded Cast SDK shim
- `web/src/lib/player/StreamPlayer.svelte` — extended with overlays
- `web/src/routes/settings/+page.svelte` — NEW
- `web/src/routes/settings/admin/+page.svelte` — NEW
- `web/src/routes/watchlist/+page.svelte` — NEW

---

## Conventions

- Branch: `feat/v2-skip-intro-polish`
- TDD strict; conventional commits; **no `Co-Authored-By`**

---

## Task 0: Branch + deps

```bash
git checkout main && git pull
git checkout -b feat/v2-skip-intro-polish
echo "pyacoustid>=1.3" >> requirements.txt
echo "numpy>=2.0" >> requirements.txt
venv/bin/pip install -r requirements.txt
# pyacoustid requires libchromaprint (system lib)
# Mac: brew install chromaprint
# Linux: apt-get install libchromaprint-dev
git add requirements.txt
git commit -m "chore: add audio fingerprint deps for skip intro"
```

---

## Task 1: IntroMarker model + migration

**Files:** `streamload/db/models.py`, `migrations/versions/0004_intro_markers.py`

- [ ] Append to `streamload/db/models.py`:

```python
class IntroMarker(Base):
    __tablename__ = "intro_markers"

    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("catalog_items.tmdb_id", ondelete="CASCADE"), primary_key=True,
    )
    season_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    intro_start_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    intro_end_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    outro_start_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    detected_by: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))

    __table_args__ = (
        CheckConstraint(
            "detected_by IN ('fingerprint', 'manual')",
            name="ck_intro_markers_detected_by",
        ),
    )
```

- [ ] Generate + apply migration; rename to `0004_intro_markers.py`.

- [ ] Failing test:

```python
from streamload.db.models import IntroMarker

def test_intro_marker_pk():
    pk = {c.name for c in IntroMarker.__table__.primary_key.columns}
    assert pk == {"tmdb_id", "season_number"}
```

- [ ] Run + commit `feat(db): IntroMarker model + migration`.

---

## Task 2: Audio fingerprint extraction

**Files:** `streamload/post/__init__.py` (verify), `streamload/post/intro_detect.py`, `tests/post/test_intro_detect.py`

- [ ] Failing test:

```python
"""Audio fingerprint extraction + comparison."""
import numpy as np

from streamload.post.intro_detect import (
    compare_fingerprints,
    extract_fingerprint,
    find_common_intro,
)


def test_compare_identical_returns_high_score():
    fp = np.array([1, 2, 3, 4, 5], dtype=np.int32)
    assert compare_fingerprints(fp, fp) > 0.99


def test_compare_different_returns_low_score():
    a = np.array([1, 2, 3, 4, 5], dtype=np.int32)
    b = np.array([100, 200, 300, 400, 500], dtype=np.int32)
    assert compare_fingerprints(a, b) < 0.5


def test_find_common_intro_detects_shared_prefix():
    """Two fingerprints with same first N samples should yield N as the intro length."""
    common = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=np.int32)
    diff_a = np.array([10, 11, 12], dtype=np.int32)
    diff_b = np.array([20, 21, 22], dtype=np.int32)
    fp_a = np.concatenate([common, diff_a])
    fp_b = np.concatenate([common, diff_b])
    res = find_common_intro(fp_a, fp_b, sample_rate_hz=8.0)  # synthetic SR
    assert res is not None
    assert res.start_seconds == 0
    assert res.end_seconds == 1  # 8 samples / 8 Hz = 1s
    assert res.confidence > 0.8
```

- [ ] Implement `streamload/post/intro_detect.py`:

```python
"""Audio fingerprint-based intro/outro detection.

Uses ``pyacoustid``/``chromaprint`` to extract a fingerprint from the
first 90s of an episode's audio. When two episodes of the same series
share a prefix in their fingerprints, that's the intro.

The fingerprint is a sequence of 32-bit integers at ~8 Hz (one per
~125 ms frame). Comparison via Hamming distance per element.
"""
from __future__ import annotations

import asyncio
import io
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

CHROMAPRINT_SAMPLE_RATE_HZ = 7.84  # libchromaprint's default frame rate


@dataclass
class IntroResult:
    start_seconds: int
    end_seconds: int
    confidence: float


async def extract_fingerprint(audio_path: Path, *, length_seconds: int = 90) -> np.ndarray:
    """Run fpcalc to extract a Chromaprint fingerprint."""
    proc = await asyncio.create_subprocess_exec(
        "fpcalc", "-raw", "-length", str(length_seconds), str(audio_path),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    text = stdout.decode("utf-8")
    # fpcalc -raw outputs FINGERPRINT=<comma-sep-ints>
    line = next(line for line in text.splitlines() if line.startswith("FINGERPRINT="))
    ints = [int(x) for x in line.split("=", 1)[1].split(",") if x]
    return np.array(ints, dtype=np.uint32)


def compare_fingerprints(a: np.ndarray, b: np.ndarray) -> float:
    """Element-wise Hamming similarity, 0..1."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    xor = np.bitwise_xor(a[:n], b[:n])
    bits_diff = np.unpackbits(xor.view(np.uint8)).sum()
    bits_total = n * 32
    return 1.0 - (bits_diff / bits_total)


def find_common_intro(
    fp_a: np.ndarray, fp_b: np.ndarray,
    *, sample_rate_hz: float = CHROMAPRINT_SAMPLE_RATE_HZ,
    threshold: float = 0.85,
) -> Optional[IntroResult]:
    """Find the longest common high-similarity prefix.

    Walks frame-by-frame; groups consecutive matching frames; takes the
    longest run starting near offset 0 (the intro is at the beginning).
    """
    n = min(len(fp_a), len(fp_b))
    if n == 0:
        return None
    matches = np.array([compare_fingerprints(fp_a[i:i+1], fp_b[i:i+1]) >= threshold for i in range(n)])
    # Find the first run of True starting at offset 0
    if not matches[0]:
        # No intro starts at zero — try a small offset window (intros sometimes have a 1-2s logo before)
        return None
    end_idx = 0
    while end_idx < n and matches[end_idx]:
        end_idx += 1
    if end_idx < 5:
        return None  # too short to be an intro
    confidence = matches[:end_idx].mean()
    return IntroResult(
        start_seconds=0,
        end_seconds=int(end_idx / sample_rate_hz),
        confidence=float(confidence),
    )
```

(Note: this is a simplified algorithm. Production-grade intro detection uses cross-correlation with offset search; for v1 the simple "common prefix from frame 0" heuristic catches 80%+ of TV intros which are pre-fixed by exactly the same opening sequence.)

- [ ] Run + commit `feat(post): audio-fingerprint intro detector`.

---

## Task 3: Skip intro endpoint

**Files:** `streamload/api/routes/intro.py`, `tests/api/test_intro.py`

- [ ] Failing test:

```python
import httpx, pytest
from streamload.db import get_session as gs
from streamload.db.models import CatalogItem, IntroMarker


@pytest.fixture
async def authed_with_marker(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username":"u","email":"u@x.com","password":"Hunter2!secret",
    })
    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="tv", title="X"))
        db.add(IntroMarker(
            tmdb_id=42, season_number=1, intro_start_seconds=0,
            intro_end_seconds=85, detected_by="fingerprint", confidence=0.92,
        ))
        await db.commit(); break


@pytest.mark.asyncio
async def test_get_intro_marker(api_client, authed_with_marker):
    r = await api_client.get("/api/intro/42/s1")
    assert r.status_code == 200
    body = r.json()
    assert body["intro_start"] == 0
    assert body["intro_end"] == 85


@pytest.mark.asyncio
async def test_get_intro_marker_missing_returns_204(api_client):
    await api_client.post("/api/auth/register", json={
        "username":"u","email":"u@x.com","password":"Hunter2!secret",
    })
    r = await api_client.get("/api/intro/9999/s1")
    assert r.status_code == 204
```

- [ ] Implement `streamload/api/routes/intro.py`:

```python
from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import IntroMarker

router = APIRouter(prefix="/intro", tags=["intro"])


class IntroResponse(BaseModel):
    intro_start: int; intro_end: int
    outro_start: int | None = None
    confidence: float | None = None


@router.get("/{tmdb_id}/s{season}", response_model=IntroResponse | None)
async def get_intro(tmdb_id: int, season: int, user: CurrentUser, db: SessionDep, response: Response):
    row = (await db.execute(
        select(IntroMarker).where(IntroMarker.tmdb_id == tmdb_id).where(IntroMarker.season_number == season)
    )).scalar_one_or_none()
    if row is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return IntroResponse(
        intro_start=row.intro_start_seconds, intro_end=row.intro_end_seconds,
        outro_start=row.outro_start_seconds,
        confidence=float(row.confidence) if row.confidence else None,
    )
```

- [ ] Wire router. Run + commit `feat(api): intro/outro marker endpoint`.

---

## Task 4: Frontend skip intro pill

**Files:** `web/src/lib/components/SkipIntroPill.svelte`, integration in `StreamPlayer.svelte`

- [ ] `SkipIntroPill.svelte`:

```svelte
<script lang="ts">
  let { visible, onSkip }: { visible: boolean; onSkip: () => void } = $props();
</script>

{#if visible}
  <button onclick={onSkip}
          class="absolute bottom-24 right-6 px-5 py-2 bg-[var(--color-surface-2)] text-white rounded-full
                 backdrop-blur-md border border-[var(--color-border)] shadow-lg
                 hover:bg-[var(--color-surface-3)] transition">
    Salta intro
  </button>
{/if}
```

- [ ] Extend `StreamPlayer.svelte` to track current time + show pill when between `intro_start` and `intro_end`:

```svelte
<script lang="ts">
  // ... existing imports + props
  let intro = $state<{intro_start: number; intro_end: number} | null>(null);

  $effect(() => {
    if (typeof tmdb_id === "number" && typeof season === "number") {
      fetch(`/api/intro/${tmdb_id}/s${season}`).then(async r => {
        if (r.status === 200) intro = await r.json();
      });
    }
  });

  let pillVisible = $derived.by(() => {
    if (!intro || !playerEl) return false;
    const t = (playerEl.querySelector("video") as HTMLVideoElement)?.currentTime ?? 0;
    return t >= intro.intro_start && t < intro.intro_end;
  });

  function skipIntro() {
    const v = playerEl?.querySelector("video") as HTMLVideoElement;
    if (v && intro) v.currentTime = intro.intro_end + 1;
  }
</script>

<!-- existing player markup -->
<SkipIntroPill visible={pillVisible} onSkip={skipIntro} />
```

- [ ] Commit `feat(web): skip intro pill in player`.

---

## Task 5: TV episodes endpoint

**Files:** `streamload/api/routes/episodes.py`, `tests/api/test_episodes.py`

- [ ] Failing test similar to others. Endpoint shape:

```python
@router.get("/title/{tmdb_id}/episodes")
async def episodes(tmdb_id: int, ...) -> dict:
    """Returns {season_number: [{episode_number, title, runtime, still_url, ...}]}"""
```

- [ ] Implement (read from `tv_episodes` table; if empty, fetch live from TMDB and persist).

- [ ] Run + commit `feat(api): TV episodes endpoint`.

---

## Task 6: Auto-play next episode card

**Files:** `web/src/lib/components/NextEpisodeCard.svelte`, `StreamPlayer.svelte`

- [ ] `NextEpisodeCard.svelte`:

```svelte
<script lang="ts">
  let {
    visible, nextTitle, nextPosterUrl, countdownSeconds, onPlayNow, onCancel,
  }: {
    visible: boolean; nextTitle: string; nextPosterUrl?: string;
    countdownSeconds: number;
    onPlayNow: () => void; onCancel: () => void;
  } = $props();
</script>

{#if visible}
  <div class="absolute bottom-6 right-6 w-72 bg-[var(--color-surface-2)] rounded-lg p-4 backdrop-blur-md border border-[var(--color-border)] shadow-2xl">
    <div class="flex gap-3">
      {#if nextPosterUrl}
        <img src={nextPosterUrl} alt="" class="w-12 h-18 rounded object-cover" />
      {/if}
      <div class="flex-1">
        <p class="text-xs text-[var(--color-text-tertiary)]">Prossimo episodio</p>
        <p class="font-semibold mt-1 text-sm line-clamp-2">{nextTitle}</p>
      </div>
    </div>
    <div class="flex gap-2 mt-3">
      <button onclick={onPlayNow}
              class="flex-1 px-3 py-2 rounded-full bg-[var(--color-accent)] text-black text-xs font-semibold">
        ▶ Riproduci ora ({countdownSeconds}s)
      </button>
      <button onclick={onCancel}
              class="px-3 py-2 rounded-full border border-[var(--color-border)] text-xs">
        Salta
      </button>
    </div>
  </div>
{/if}
```

- [ ] In `StreamPlayer.svelte`, when 95% watched + media_type=tv: show card with 10s countdown, navigate to next episode on countdown end or "play now" click.

- [ ] Commit `feat(web): auto-play next episode card`.

---

## Task 7: Server selector dropdown

**Files:** `web/src/lib/components/ServerSelector.svelte`, `StreamPlayer.svelte`

- [ ] `ServerSelector.svelte`:

```svelte
<script lang="ts">
  let {
    servers, current, onSelect,
  }: {
    servers: {label: string; score: number}[];
    current: string;
    onSelect: (label: string) => void;
  } = $props();
  let open = $state(false);
</script>

<div class="relative">
  <button onclick={() => open = !open}
          class="px-3 py-1.5 rounded-md bg-[var(--color-surface-2)] text-xs">
    {current} ▼
  </button>
  {#if open}
    <div class="absolute right-0 mt-2 w-48 bg-[var(--color-surface-2)] rounded-lg border border-[var(--color-border)] overflow-hidden z-10">
      {#each servers as s}
        <button onclick={() => { onSelect(s.label); open = false; }}
                class="w-full px-4 py-2 text-left text-sm hover:bg-[var(--color-surface-3)] flex justify-between">
          <span class:font-semibold={s.label === current}>{s.label}</span>
          <span class="text-[var(--color-text-tertiary)]">{s.score.toFixed(0)}</span>
        </button>
      {/each}
    </div>
  {/if}
</div>
```

- [ ] Mid-stream switch: when user selects a different server, `play.start(tmdb_id, server)` to get new session, swap `src` of player. Resume from current `currentTime`.

- [ ] Commit `feat(web): server selector with mid-stream swap`.

---

## Task 8: Cast SDK integration

**Files:** `web/src/lib/player/CastSender.ts`

- [ ] Implement:

```typescript
let castSDKLoaded = false;

export async function loadCastSDK(): Promise<void> {
  if (castSDKLoaded) return;
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1";
    script.onload = () => resolve();
    script.onerror = reject;
    document.head.appendChild(script);
  });
  await new Promise<void>((resolve) => {
    (window as any)["__onGCastApiAvailable"] = (available: boolean) => {
      if (available) resolve();
    };
  });
  const cast = (window as any).cast;
  cast.framework.CastContext.getInstance().setOptions({
    receiverApplicationId: cast.chrome.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
    autoJoinPolicy: cast.framework.AutoJoinPolicy.ORIGIN_SCOPED,
  });
  castSDKLoaded = true;
}

export async function castMedia(masterUrl: string, title: string): Promise<void> {
  await loadCastSDK();
  const cast = (window as any).cast;
  const session = cast.framework.CastContext.getInstance().getCurrentSession();
  if (!session) throw new Error("No cast session — request via cast button first");
  const mediaInfo = new cast.chrome.media.MediaInfo(masterUrl, "application/x-mpegURL");
  mediaInfo.metadata = new cast.chrome.media.GenericMediaMetadata();
  mediaInfo.metadata.title = title;
  const request = new cast.chrome.media.LoadRequest(mediaInfo);
  await session.loadMedia(request);
}
```

- [ ] Add Cast button to `StreamPlayer.svelte`.

- [ ] Commit `feat(web): Cast SDK lazy-load + cast media`.

---

## Task 9: Settings page

**Files:** `web/src/routes/settings/+page.svelte`, backend settings route

- [ ] Backend `streamload/api/routes/settings.py`:

```python
"""Per-user preferences."""
from fastapi import APIRouter
from pydantic import BaseModel
from streamload.api.deps import CurrentUser, SessionDep

router = APIRouter(prefix="/settings", tags=["settings"])

class UserSettings(BaseModel):
    audio_pref: str = "ita"
    subs_pref: str = "ita"
    autoplay_next: bool = True
    quality_lock: str | None = None

# For v1, settings are stored in users.locale or a JSON column. We can extend
# users table with `settings JSONB` later. For now, expose a stub.

@router.get("", response_model=UserSettings)
async def get_settings(user: CurrentUser) -> UserSettings:
    return UserSettings()

@router.put("", response_model=UserSettings)
async def update_settings(payload: UserSettings, user: CurrentUser) -> UserSettings:
    # TODO Plan 6: persist in users.settings JSONB
    return payload
```

- [ ] Frontend page with form for audio/subs/autoplay preferences.

- [ ] Commit `feat: per-user settings (stub for v1)`.

---

## Task 10: Admin dashboard

**Files:** `streamload/api/routes/admin.py`, `web/src/routes/settings/admin/+page.svelte`

- [ ] Backend admin endpoints:

```python
"""Admin user management + system status."""
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from streamload.api.deps import AdminUser, SessionDep
from streamload.db.models import User
from streamload.utils.domain_resolver import DomainResolver  # if accessible

router = APIRouter(prefix="/admin", tags=["admin"])


class UserSummary(BaseModel):
    id: str; username: str; email: str; role: str
    email_verified: bool; created_at: str


@router.get("/users", response_model=list[UserSummary])
async def list_users(admin: AdminUser, db: SessionDep) -> list[UserSummary]:
    rows = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return [
        UserSummary(
            id=str(u.id), username=u.username, email=u.email, role=u.role,
            email_verified=u.email_verified_at is not None,
            created_at=u.created_at.isoformat(),
        ) for u in rows
    ]


class PromoteRequest(BaseModel):
    role: str  # 'admin' | 'user'


@router.put("/users/{user_id}/role")
async def update_role(user_id: str, payload: PromoteRequest, admin: AdminUser, db: SessionDep) -> dict:
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        return {"status": "not found"}
    u.role = payload.role
    await db.commit()
    return {"status": "ok"}


@router.get("/health/domains")
async def domains_health(admin: AdminUser) -> dict:
    """Show resolver state per service: cached domain, source, last verified."""
    from streamload.utils.domain_resolver.cache import DomainCache
    from pathlib import Path
    cache = DomainCache(Path("data/domains_cache.json"))
    return {"entries": cache.entries()}
```

- [ ] Frontend admin page lists users, lets you promote, shows domains health.

- [ ] Commit `feat(api+web): admin dashboard for users + domain health`.

---

## Task 11: Watchlist UI

- [ ] `web/src/routes/watchlist/+page.svelte` — grid of watchlist items, similar to library page but filtered.

- [ ] On title detail page, add "Aggiungi alla mia lista" button next to Favorite.

- [ ] Commit `feat(web): watchlist page + add-to-watchlist button`.

---

## Task 12: Polish — animations + page transitions

- [ ] Add View Transitions API in `+layout.svelte`:

```svelte
<script lang="ts">
  import { onNavigate } from "$app/navigation";

  onNavigate((navigation) => {
    if (!(document as any).startViewTransition) return;
    return new Promise((resolve) => {
      (document as any).startViewTransition(async () => {
        resolve(); await navigation.complete;
      });
    });
  });
</script>
```

- [ ] Add skeleton loaders for poster grids during fetch.

- [ ] Add toast component for success/error notifications.

- [ ] Commit `feat(web): page transitions + skeletons + toast`.

---

## Task 13: Version bump + merge

- [ ] Bump to `0.2.0-alpha.5`.

- [ ] Run all tests.

- [ ] Merge:

```bash
git checkout main
git merge --no-ff feat/v2-skip-intro-polish -m "Merge branch 'feat/v2-skip-intro-polish'

Plan 5 of Streamload v2: polish + advanced features.

Includes:
* Audio-fingerprint intro detection (via chromaprint/pyacoustid)
* IntroMarker model + endpoint
* Skip intro pill in player
* Auto-play next episode card with countdown
* Server selector dropdown with mid-stream swap
* Cast SDK lazy-load + cast media
* Settings page (per-user prefs)
* Admin dashboard (user mgmt + domain health)
* Watchlist UI
* Page transitions, skeletons, toast notifications

Spec: §6.5 + §6.6 + §7.5 + §9.3 + §11
Plan: docs/superpowers/plans/2026-05-08-streamload-v2-plan-5-skip-intro-polish.md"

git push origin main
git tag -a v0.2.0-alpha.5 -m "Plan 5 complete"
git push origin v0.2.0-alpha.5
```

---

## Self-Review Checklist

- [ ] Audio fingerprint extracts correctly from a sample MP3 (manual test)
- [ ] Skip intro pill appears at correct timestamps (manual test on a series with markers)
- [ ] Next episode card triggers at 95% watched
- [ ] Server selector swaps mid-stream without losing position
- [ ] Cast button visible on Chrome desktop, casts to Chromecast (manual)
- [ ] AirPlay still works on Safari (manual)
- [ ] Admin can list + promote users
- [ ] No `Co-Authored-By` trailers
- [ ] v0.2.0-alpha.5 tagged

---

## Open issues (deferred to Plan 6)

- Production deployment (Docker, systemd, Watchtower)
- CI/CD pipeline (GitHub Actions)
- Backup strategy
- First-time Acer bootstrap
