# Case 001: Opaque Professional Wording

## Source and privacy

The user supplied one AI-generated sentence and a wording preference. The generator, whether this skill was active, and the rest of the document are unknown. This case calibrates the desired behavior; it is not evidence of a reproduced failure of this skill.

Only the necessary sentence and a summary of the feedback are retained. Privacy review found no names, organizations, project identifiers, internal paths, accounts, credentials, or unpublished results or numeric data in the retained excerpt. The additional contexts below are hypothetical, not recovered facts about the original document.

## Input and user feedback

> 首次部署与重复到访实验分别评价锚定成功率、配置投入和观察恢复代价。

The user finds this too artificial and professionally packaged, especially “恢复代价”. The desired register is professional but plain. Useful terms with clear definitions and repeated use should remain; occasional self-coined labels usually do not need a special name.

## With only the supplied excerpt

The sentence does not establish:

- What “配置投入” measures, or its unit.
- What must be restored in “观察恢复”, and what “代价” measures.
- How the metrics correspond to the two experiments, or whether all three are measured in both.
- Whether these terms are defined in an earlier section or glossary, or used repeatedly later.

Revise the wording whose meaning is clear and gather the remaining questions after the revision. Do not pause every clear edit, invent metric definitions, or claim that the complete document lacks definitions. A conservative preliminary edit can change “重复到访” to “再次到访” while leaving the unresolved metric names for confirmation. This alone does not resolve the user's main concern.

## Hypothetical context: occasional labels

For this example only, suppose the source explicitly establishes all of the following:

- Both experiments record all three metrics.
- “配置投入” means the time needed to complete configuration.
- “观察恢复代价” means the number of operations needed to restore observation.
- The two labels occur only occasionally and are not required names in tables or cross-references.

An illustrative rewrite is:

> 首次部署和再次到访的实验都记录锚定成功率、配置所需时间，以及恢复观察所需的操作次数。

The rewrite preserves the supplied measurements and their different units. It is not a definitive rewrite of the context-free original or the only acceptable wording.

## Contrast: a useful recurring term

In a separate hypothetical document, suppose “观察恢复代价” is clearly defined in the glossary as the number of operations needed to restore observation, uses the symbol `C_rec`, and recurs across sections and tables. Keep the term and symbol consistent instead of expanding or renaming them at every occurrence.

If the meaning is already established by that document but its first use lacks an explanation, a possible first-use definition is:

> 本文将恢复观察所需的操作次数称为“观察恢复代价”，记为 `C_rec`。

Add that definition only when the supplied source supports it. If the measurement remains unknown, flag the uncertainty instead. An established precise term such as “置信区间” also need not be removed merely because it appears once.

## Review criteria

- Does the revision explain the action or measurement more clearly without changing facts, units, symbols, or experiment-to-metric relationships?
- Does it distinguish an unnecessary occasional label from a useful defined recurring term?
- When the source is incomplete, does it still improve supported wording and collect the uncertainties without guessing?
- For a full-document request, does it check the supplied document and terminology consistently rather than treating this sentence as the whole review?

Judge the actual result, not whether it matches the example, removes particular words, or becomes shorter. No universal behavioral improvement or live platform-model validation is claimed by this case.
