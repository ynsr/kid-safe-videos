<version>1</version>

You are researching whether a cartoon title is suitable at all for children aged 3+.

Judge ONLY against rules.yaml (family_values and categories below). Never use your own opinions.
No source means "unknown", never a guess. No timestamps in this file.

RULES:
{rules_block}

TITLE: {title}
YEAR: {year}
IDS: {ids}

Search IMDb parental guide, Common Sense Media, Kids-In-Mind, Plugged In, Dove, and detailed plot summaries for this EXACT title (match year and IMDb ID).
Rate each dimension none|minor|moderate|major|unknown with evidence items (source_url + short paraphrased snippet, no long quotes):
- romance_prevalence, romance_as_central_plot, horror_scary, violence, mature_themes, values_concerns
Note whether romance is interleaved throughout or limited to a few scenes.
If evidence is thin or conflicting choose "unknown" with low confidence.
Always include limitations: no audio/dialogue/music analysis, guides rarely list mild romance, dub/edit timing risk, subtle moments can be missed, verdicts are advice, never claim safe/clean.
Describe sensitive content briefly and neutrally. Max 5 plain sentences in summary.

Write suitability.yaml with schema:
title_level: {verdict: recommended|recommended_after_cuts|not_recommended|unknown, confidence: low|med|high, dimensions: {...}, summary: str, limitations: [...]}
decisions: []

Then run validate_suitability and fix every error.
