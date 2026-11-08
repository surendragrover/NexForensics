# NexForensics (InvestigatorAI)

AI-assisted case analysis for investigators, journalists and fraud teams. NexForensics reads a case narrative and its evidence, and produces a structured investigation report: crime classification, applicable statutes, a risk score, name-matches against watchlists, hypotheses, an investigation roadmap and a PDF report.

> **Status:** private, pre-launch. Not a substitute for legal advice, a charge sheet or a court finding. Every name-match is a lead that must be verified.

## What it does

- **Crime classification:** financial crime (bank fraud, LoU/SWIFT fraud, accounting fraud, bribery, diversion of funds) and violent crime (murder, attempt to murder, kidnapping, rape, dacoity, robbery, extortion, burglary, theft, hurt).
- **Statutes:** IPC sections with their BNS equivalents (for example IPC 302 → BNS 103, IPC 201 → BNS 238), plus the Prevention of Corruption Act where relevant.
- **Crime-severity risk score:** the score starts from the most serious crime in the case, adds points for further crime types and for aggravating factors (weapon, absconding, amount involved, organised or shell-company activity, many victims, fugitive name-match), and is capped at 95. Bands: High 70+, Medium 40+, else Low. Used when no validated risk model applies.
- **Watchlist name-matching:** sanctions, debarment and Interpol-style lists. Matches are reported as unverified name-matches, never as charges.
- **Guidance engine:** knowledge bases for financial fraud, accounting fraud, bank-guarantee fraud, inside jobs, professional gangs, security collusion and homicide, giving hypotheses, investigation paths and the next evidence to collect.
- **Investigation roadmap:** one ranked, de-duplicated list of next steps (for example SWIFT vs CBS reconciliation in an LoU fraud, or post-mortem, CDRs and last-seen evidence in a murder case).
- **Reports:** text report and a multi-page PDF with charts.
- **Journalist research toolkit** (`journalist_research/`): connectors, entity intelligence, extraction, evidence handling, validation and safety modules.
- **Deepfake check (experimental):** face-crop based image classifier for evidence images.

## Repository layout

| Path | Contents |
|---|---|
| `gradio_app.py` | Investigator UI (Gradio) |
| `investigator_integration.py` | Main analysis pipeline glue |
| `analysis/` | Evidence analysis, reasoning, report rules (`report_rules.json` holds crime-severity rules) |
| `engines/` | Hybrid rules, matching, ML and NLI engines |
| `guidance_engine/` | Guidance engine and its knowledge bases |
| `reports/` | Charts, HTML renderers, PDF export |
| `routes/` | Flask API: auth, set-password, WordPress sync |
| `journalist_research/` | Research toolkit |
| `templates/` | Dashboard template |
| `tests_hybrid/` | Rule and report tests |

## Running

The app runs on Ubuntu with Python 3, behind Apache:

- Flask API: gunicorn on `127.0.0.1:5001`, served under `/app/`
- Investigator UI: `gradio_app.py`
- Database: MySQL (`investigator`)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your own values; never commit .env
python3 gradio_app.py
```

Models (`models/`) and datasets are not stored in this repository; they are kept on the server.

## Tests

```bash
python3 tests_hybrid/test_hybrid_rules.py
python3 tests_hybrid/test_report_rules_p23.py
```

## Security

- Secrets (API keys, SMTP, WordPress sync secret, JWT key) come from environment variables only.
- Do not commit `.env`, model files, datasets, logs or case data.

## Author

Surendra Grover — [nexforensics.com](https://nexforensics.com)

All rights reserved. This code is proprietary and may not be copied or used without permission.
