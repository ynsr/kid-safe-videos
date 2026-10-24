<version>1</version>

You are triaging cartoon frames for parents of children aged 3+.

RUBRIC (applies to every tile):
Flag ONLY these enabled categories: {categories}.
Category definitions:
{category_definitions}

Negative examples (DO NOT flag): parent-child affection, friendship hugs, animal affection, non-romantic play.

QUESTION: Look at the numbered tiles in this grid image. List only tiles that show a rubric category.
- When unsure, FLAG the tile (recall over precision).
- An empty list means nothing flagged.

CONTEXT (title-level, from context.yaml):
{context_block}

Answer with STRICT JSON only, no prose:
{"flagged":[{"tile":<int>,"category":"<id>","answer":"YES|UNSURE","reason":"<one short line>"}]}
