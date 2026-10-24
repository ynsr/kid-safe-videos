# kidsafe

**Fast, lossless cutting of unsafe scenes from cartoons for ages 3+. No blurring, no re-encoding.**

Parents pick a title, the tool finds candidate unsafe scenes (web research + image-grid vision), a human reviews every finding in a local UI, and accepted ranges are removed with **lossless `ffmpeg -c copy` stream copy only** — keyframe-snapped outward so no unsafe frame survives. A reusable per-video sidecar records everything.

## How it works

1. **Suitability gate** — deterministic hard rules from `rules.yaml` (certifications, genres) block unsuitable titles before spending money; agent research rates dimensions with cited evidence into `suitability.yaml`.
2. **Research** — the agent writes cited parental-guide entries to `research.yaml` (never timestamps without a source); `validate_research.py` rejects sourceless entries.
3. **Align + image-grid localisation** — reference times scale to the local file (`align.py`); `frames.py`/`grid.py` build numbered tiles and tile→time maps; `vision.py` asks an OpenAI-compatible vision role strict-JSON questions. Models only ADD flags, never remove; failures count as UNSURE.
4. **Sweep safety net** — coarse whole-title scan catches what guides miss (mild romance guides rarely list).
5. **Human review** — local Flask UI (`kidsafe review`) on 127.0.0.1: accept/reject/correct every candidate, set in/out from playhead, play joins, build final.
6. **Lossless cut + verify + sidecar** — `cut.py` inverts cuts to keep-ranges, snaps outward to keyframes, concat-demuxer stream copy for ALL streams. `verify.py` checks durations and stream preservation. `sidecar.py` writes `<stem>-inappropriate-parts.yml`.

## Jellyfin library support

Default layout `Movies/<Name> (<Year>)/…`, `Shows/<Show> (<Year>)/Season NN/…SNNENN…` with `[imdbid-…]/[tmdbid-…]/[tvdbid-…]` tags, multi-version suffixes, multi-part files, multi-episode files, Season 00 specials; extras/trailers ignored. `kidsafe scan <root>` → `library.yaml`; output goes to a **separate mirrored root** (`output_root`), never into the source library — except the sidecar file.

## Cost model

Every paid step shows calls/tokens and asks for confirmation. Cheap `frame_triage` role first, `escalation` only for UNSURE/conflicts, optional `extra_vote`. Series: `sweep_policy: full | sampled(N) | research_only` (default sampled). Costs live in work logs, keyed by grid hash + prompt version + model.

## Review UI

`kidsafe review <id>` — library status, title verdict + evidence, candidate list with category/origin/confidence, proxy player (browsers can't play many source codecs; proxy is UI-only), timeline highlight, Accept (A) / Reject (R) / Next (J/K) / Play range (Space), timing nudges, keyframe-snapped preview, play-join, manual cuts, merge/split, summary bar, per-episode propagation, Build button. Manual-only mode works with no model configured.

## Lossless cutting and the keyframe limitation

Cuts can only land on keyframes without re-encoding. Each cut snaps **outward** (more removed, never less); the report shows extra seconds removed per cut and warns when keyframe gaps exceed the limit. If lossless output is impossible, the tool fails loudly — never falls back silently.

## Configuration

- `config/rules.yaml` — your values (certifications, genres, thresholds, categories, pipeline, sidecar location). The tool encodes them, imposes none.
- `config/models.yaml` — roles with `base_url`, `model`, `api_key_env`; startup refuses titles marked private to `training_data_risk: true` providers. Verify exact model IDs and image support on the provider.
- `prompts/*.md` — versioned rubrics (rubric first for prompt caching, strict-JSON answers, no timestamps from models).

## Sidecar file

`<video-stem>-inappropriate-parts.yml` next to the source and/or output (config `sidecar.location`). Built only by `sidecar.py`, never by hand; schema-validated; stale detection by duration ±0.5 s, fps, size, sha256-partial fingerprint; `import-sidecar` replays accepted cuts and keeps rejected parts rejected.

## Privacy

Originals are read-only (sole source write: the sidecar). No local ML models. No audio/speech/dialogue/music analysis. No video to models — images only. Local UI on 127.0.0.1; keys from env vars, never logged or stored.

## Limitations

- No audio, dialogue, or music analysis; video motion is not analysed.
- Parental guides rarely list mild romance — research alone is never trusted (see sweep).
- Dub/edit/PAL-speedup timing can shift windows (tool warns beyond 5%).
- Subtle moments can be missed; verdicts are advice, never a claim of "safe"/"clean".
- Keyframe gaps may force wider cuts than requested.

## CLI

```
kidsafe scan <library_root> | init <video> | suitability <id>
kidsafe validate-research <id> | align <id> | localise <id> | sweep <id>
kidsafe merge <id> | review [<id>] | cut <id> | cut --manual cuts.yaml <video>
kidsafe verify <id> | sidecar <id> | import-sidecar <video> | sidecar-status <root>
kidsafe calibrate <samples> | run <video>
```

## Credits

Fork of [browser-use/video-use](https://github.com/browser-use/video-use), rewritten for lossless cartoon cutting.
