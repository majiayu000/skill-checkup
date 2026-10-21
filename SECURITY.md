# Security Policy

skill-checkup reads local skill folders and agent session logs and writes a report. It is designed to be read-only and offline.

Please report anything that breaks those guarantees (a write outside the report and cache paths, network access, or private text leaking into `--summary-json --anonymize` output) through [GitHub Security Advisories](https://github.com/majiayu000/skill-checkup/security/advisories/new). Do not open a public issue for these.

Only the latest commit on `main` is supported.
