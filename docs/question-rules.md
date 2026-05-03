# Question Rules

When a future source is incomplete, ask only for the missing fields needed to generate the interpreting PDF.

All questions must be numbered. Tell the user they can answer with only the number and a short answer, for example:

```text
1. 2026-05-02
2. Beja
3. 39
```

Use `python scripts/intake_questions.py <intake-json>` to print numbered missing-information questions from a partial intake file.

The question script uses these rules:

- If a court or Ministério Público header is available, it can infer the payment entity.
- If no separate GNR/PSP/police clue exists, the same header can also be used as the service entity.
- If the source mentions GNR, PSP, police, `posto`, `esquadra`, `destacamento`, `hospital`, or `gabinete` but does not say the exact location, ask for the service entity.
- If the source mentions Polícia Judiciária, PJ, Diretoria, or Inspetor/a, require the local host building and city. PJ alone is not enough because it usually uses another local building, often GNR.
- Do not ask for the inspector name. Include it only when it is already visible in the source or volunteered by the user.
- If the image metadata date is available, use it as the priority service-date signal.
- If a printed document timestamp and the image metadata date conflict, ask which is the service date unless the user has already confirmed the exception.

## Missing Process Number

Ask:

```text
1. What is the Número de processo exactly as it appears on the document? (Example: 398/24.5T8BJA.)
```

## Missing Service Date

Ask:

```text
1. What date did you provide the in-person interpreting service? (Use YYYY-MM-DD. If the image metadata date is the service date, give that date.)
```

Do not ask for the document date if the problem is the service date.

## Conflicting Service Dates

Ask:

```text
1. The document date and image metadata date conflict. Which service date should I use? (Answer with YYYY-MM-DD, or say metadata/document.)
```

## Missing Service Place

Ask:

```text
1. Where did you attend in person for this interpreting service? (A short institution/city answer is enough, for example Tribunal de Beja, GNR de Cuba, or PSP de Moura.)
```

## Missing Polícia Judiciária Host Building

Ask when the source identifies Polícia Judiciária but does not identify the physical building/city used:

```text
1. Which building and city did Polícia Judiciária use for this service? (Example: Posto da GNR de Ferreira do Alentejo.)
```

## Missing Addressee

Ask:

```text
1. Which court, Ministério Público office, or other entity should this request be addressed to for payment? (A short court name is enough.)
```

## Missing Service Entity

Ask when the payment entity and physical service place may be different:

```text
1. Where did you attend in person for this interpreting service? (A short answer is enough, for example PSP de Moura or Posto Territorial da GNR de Cuba.)
```

## Missing Transport Decision

Ask:

```text
1. Should this request include transport expenses from Marmelar? (Answer yes or no.)
```

If yes and the destination is unknown, ask:

```text
2. What was the destination? (A city name is enough.)
3. How many kilometers is it one way from Marmelar? (A number is enough.)
```

## Translation Indicators

If the source mentions word counts or translation wording, do not generate the interpreting PDF. Say:

```text
This looks like a translation honorários request because it mentions word counts or translation work. I will set it aside from the in-person interpreting project.
```

## Missing Closing Date

Use today's date only when the user is asking to create a new request now. Otherwise ask:

```text
1. What date should appear in the closing line of the request? (Use YYYY-MM-DD.)
```
