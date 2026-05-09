# Template Patterns

These patterns come from the confirmed in-person interpreting honorários PDFs in the sent-mail review for 2026-02-02 through 2026-05-02.

## Core Structure

The documents follow this order:

1. Process number.
2. Addressee, usually a court, Ministério Público office, or prosecutor.
3. Applicant identity and address.
4. Request body stating the applicant was appointed as `interprete`.
5. Explicit service date, normally introduced by `no dia DD/MM/YYYY`.
6. Optional in-person place, such as court, GNR, or PSP.
7. Optional transport reimbursement details.
8. IVA/IRS statement.
9. IBAN payment line.
10. Closing phrase, city/date, and signature.

## Process Number

Observed label:

```text
Número de processo: 398/24.5T8BJA
```

Use the process number exactly as shown in the source. Do not normalize dots or slashes.

## Addressee Variants

Common patterns:

```text
Exmo. Senhor Procurador da República
Ministério Público de Beja
```

```text
Exma. Senhora Procuradora da República
Tribunal Judicial da Comarca de Beja
```

```text
Exmo. Senhor Procurador do Ministério Público de Ferreira do Alentejo
```

The intake should provide a final `addressee` string instead of forcing the generator to infer legal style.

## Payment Entity vs Service Entity

Use these structured fields when reading a new source:

```json
{
  "payment_entity": "Tribunal de Moita",
  "service_entity": "Esquadra da PSP de Moura",
  "service_entity_type": "psp",
  "entities_differ": true
}
```

Rules:

- A court or Ministério Público header normally identifies both the payment entity and service entity.
- If the source also points to GNR, PSP, police, or another non-court location, the service entity must be recorded separately.
- When `entities_differ` is true, the body must explicitly mention the service location.
- The email draft goes to the payment entity/court address, not to the physical service location unless that is also the payment entity.

## Applicant Block

Reusable personal profile data:

```text
Nome: Example Interpreter
Morada: Example Street 1, 1000-000 Example City
```

Keep real personal profile data private in ignored `config/profiles.local.json`. The app derives the legacy generator `config/profile.json` shape from the selected main personal profile so older CLI commands still use the same applicant, address, IBAN, IVA/IRS, and signature fields.

Do not confuse personal profiles with service profiles. Personal profiles describe the requester/payment/travel identity; service profiles in local `data/service-profiles.json` describe recurring service patterns, payment entities, recipients, service wording, and transport defaults. Public checkouts use `data/service-profiles.example.json` as the sanitized fallback.

## Interpreting Body

Base wording:

```text
Venho, por este meio, requerer o pagamento dos honorários devidos, em virtude de ter sido nomeado intérprete no âmbito do processo acima identificado, no dia {service_date}.
```

The `{service_date}` must come from the actual interpreting service date. For photographed documents, the date may come from visible image metadata (`photo_metadata_date`) when the document text contains only a procedural/document timestamp.

When the service place is known:

```text
..., no dia {service_date}, em {service_place}.
```

When the declaration gives a time period, include it immediately after the date:

```text
..., no dia {service_date}, no período das {service_start_time} às {service_end_time}, em {service_place}.
```

For police/GNR/PSP contexts:

```text
..., no dia {service_date}, no posto territorial da GNR de Cuba.
```

```text
..., no dia {service_date}, na esquadra da PSP de Moura.
```

These phrases are required when the payment entity and service entity differ, for example when payment is requested from Moita but the service happened at PSP de Moura.

For Polícia Judiciária contexts, the body must identify the physical host building and city used for the service. PJ commonly travels from elsewhere and uses a local GNR building, so do not generate a request from `Polícia Judiciária` or `Diretoria` alone. Valid wording:

```text
..., no dia {service_date}, em diligência da Polícia Judiciária realizada no Posto da GNR de Ferreira do Alentejo.
```

For PJ victim-accompaniment or medical-legal examination services, explicitly identify the medical-legal office and hospital:

```text
..., no dia {service_date}, em diligência da Polícia Judiciária, no acompanhamento da vítima ao Gabinete Médico-Legal de Beja, nas instalações do Hospital José Joaquim Fernandes - Beja.
```

If an inspector name is visible and useful, it can be appended:

```text
..., em diligência da Polícia Judiciária realizada no Posto da GNR de Ferreira do Alentejo, com o Inspetor Marco Guerreiro.
```

If the inspector name is missing, omit it without asking.

## Transport Pattern

Most interpreting requests include transport expenses:

```text
Mais requer o pagamento das despesas de transporte entre Marmelar e Beja, tendo percorrido 39 km para a ida e 39 km para a volta.
```

Alternative wording:

```text
..., 42 km em cada sentido.
```

Use `round_trip_phrase` from the intake when a particular precedent needs one wording. Default to `para a ida e ... para a volta`.

## IVA, IRS, And IBAN

Observed variants:

```text
Este serviço inclui a taxa IVA de 23% e não tem retenção de IRS.
```

```text
Este serviço inclui a taxa de IVA de 23% e não está sujeito a retenção de IRS.
```

Use the configured default in `config/profile.json`, unless a future precedent shows that a specific court needs a different phrase.

Payment line:

```text
O pagamento deverá ser efetuado para o seguinte IBAN: {iban}
```

## Closing

Observed closings:

```text
Melhores cumprimentos,
```

```text
Pede deferimento,
```

```text
Espera deferimento,
```

Common date line:

```text
Beja, 5 de fevereiro de 2026
```

The closing date is the document date, not the service date, unless the source explicitly says the service happened on the same day.
