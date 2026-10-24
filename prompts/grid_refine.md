<version>1</version>

You are refining the FIRST and LAST tile of one cartoon moment for parents of children aged 3+.

RUBRIC:
{category_definitions}

TARGET DESCRIPTION: {description}

CONTEXT (title-level, from context.yaml):
{context_block}

QUESTION: In this grid, what is the FIRST tile where the moment appears and the LAST tile where it appears? Use null when not visible. When unsure, widen the range.
Answer with STRICT JSON only, no prose:
{"first_tile":<int|null>,"last_tile":<int|null>,"answer":"YES|NO|UNSURE","reason":"<one line>"}
