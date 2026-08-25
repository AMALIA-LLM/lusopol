# Data notes

Each language file (`preferences_en.jsonl`, `preferences_pt.jsonl`) contains one preference pair
per line, with the fields:

| field | description |
| --- | --- |
| `prompt_id` | integer identifier of the underlying prompt, shared across the two languages |
| `paraphrase_id` | integer index of the paraphrase variant within a `prompt_id` |
| `category` | topical category of the prompt |
| `prompt` | the user prompt |
| `chosen` / `rejected` | chat-formatted turns (`role`, `content`), as in [UltraFeedback Binarized](https://huggingface.co/datasets/HuggingFaceH4/ultrafeedback_binarized) |
| `chosen_model` / `rejected_model` | which of the two compared models produced each response |
| `reasoning` | the judge's justification for the preference |

A row is uniquely identified by the pair (`prompt_id`, `paraphrase_id`).

The two full files are **not tracked in git** — together they are around 54 MB. They are produced by
the generation pipeline and kept alongside this file locally. What is tracked is the stratified,
language-aligned samples drawn from them for human annotation, under
`human-labeling/rounds/`, each with a manifest recording the seed and the exact selection.

The two compared models are `deepseek-r1-0528` and `command-r-plus-08-2024`; preferences were
assigned by `claude-opus-4.1` as judge.

## Excluded rows

The prompt set is built from 350 prompts per language (7 categories x 50 prompts), each with 11
variants (`paraphrase_id` 0-10), for 3,850 pairs. A small number of items were dropped during
quality control, so the released files contain 3,847 (English) and 3,841 (Portuguese) pairs.

**English — 3 rows dropped**, at (`prompt_id`, `paraphrase_id`) = (89, 6), (89, 8), (306, 1).
For these items one of the two models returned an empty response, leaving no valid pair to compare.
Because the judge was shown an empty candidate, the accompanying preference and justification are
not meaningful, and the rows were removed rather than repaired.

**Portuguese — 9 rows dropped**, at (157, 0), (183, 0), (183, 1), (183, 2), (183, 4), (183, 5),
(183, 8), (183, 9), (206, 7).
Portuguese prompts were obtained by translating the English prompts with an LLM. For these items the
translation step returned a refusal message instead of a translation, so the stored prompt text is
not a prompt at all and the responses collected for it are not interpretable. Prompt 183 concerns
racial profiling in immigration enforcement, which the translation model declined to render for most
of its variants; 7 of its 11 variants are affected, and the remaining 4 are kept.

No rows were removed on the basis of the preference outcome, the identity of the preferred model, or
the content of the judge's reasoning. Identifiers are preserved as originally assigned, so the
excluded rows are simply absent rather than renumbered, and English and Portuguese rows remain
alignable by (`prompt_id`, `paraphrase_id`) where both are present.
