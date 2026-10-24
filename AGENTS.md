# AGENTS.md — instructions for any coding agent working one title

You perform ONLY: suitability research (`suitability.yaml`), scene research
(`research.yaml`), and answering the human. Everything else runs via the CLI.
One title at a time. Never modify originals. Never write or edit a sidecar by
hand. Never edit `cuts.yaml` without the human's approval.
Never write timestamps without a source.

## Numbered checklist for one title

1. `kidsafe init <video>` — probe + keyframes + `work/<id>/` skeleton.
2. `kidsafe suitability <id>` — read the deterministic gate result.
3. Research suitability per `prompts/suitability_research.md`, write
   `work/<id>/suitability.yaml`, run `kidsafe validate-suitability`, fix errors.
4. Research scenes (IMDb parental guide, Common Sense Media, Kids-In-Mind,
   Plugged In, Dove + detailed plot summaries; match year + IMDb ID), write
   `work/<id>/research.yaml` with `reference_runtime_seconds`,
   `matched_imdb_id`, `items[]` (id, description, category, approx time or
   null, `time_basis`, `source_url`, `evidence_snippet`, confidence low/med/high).
   Estimates carry `time_basis != explicit` + confidence low. Keep descriptions
   short and neutral. No source means no entry.
5. `kidsafe validate-research work/<id>/research.yaml` — fix every error.
6. `kidsafe align <id>` — note scale warnings; add `landmarks` to
   `context.yaml` (1–3 guide/local pairs) if dub/edit drift is known, re-run.
7. `kidsafe localise <id>` (two-stage vision per window: triage then refine;
   UNSURE widens, never drops), then `kidsafe sweep <id>`
   (default ON; `--skip` only with explicit human approval + reason).
8. `kidsafe merge <id>` — inspect `candidates.yaml`.
9. `kidsafe review <id>` — human reviews every candidate; decisions persist to
   `cuts.yaml` and regenerate the sidecar automatically.
10. `kidsafe cut <id>` then `kidsafe verify <id> <output>` — report the
    verification; on failure, diagnose, never re-encode.
11. `kidsafe sidecar <id>` — confirm the sidecar path; attach its summary.

## Rules

- Judge ONLY against `config/rules.yaml` (family_values, categories), never
  your own opinions. No source means "unknown", not a guess.
- Never state a verdict as certain. Always include limitations
  (no audio/dialogue/music analysis, guides miss mild romance, dub/edit drift,
  subtle moments can be missed, verdicts are advice, never "safe"/"clean").
- Timestamps come only from code (tile mapping, scaled research windows),
  never from numbers you write. You may name scenes, not times.
- Models (including you for research, vision roles for frames) can only ADD
  flags, never remove them.
- Manual mode (`kidsafe cut --manual cuts.yaml <video>`) always works with no
  model configured.

## Troubleshooting

- `ffmpeg/ffprobe not found` — install ffmpeg ≥ 4.x on PATH, re-run `init`.
- API errors (401/429/5xx) — check `*_KEY` env vars, retry with backoff; 401 =
  wrong key, stop and ask. Transport/parse failures count as UNSURE (flagged).
- Large keyframe gaps — widen the cut outward (shown in UI), note extra seconds;
  if unacceptable, fail loudly rather than re-encode.
- Proxy failures — check source codec support; proxy is UI-only, final never uses it.
- Unparsed filenames — mark `needs_identification` in `library.yaml` and ask the
  user; never guess titles/IDs.
