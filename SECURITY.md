# Security Policy

## Supported versions

Security fixes are applied to the latest release and the next patch/minor
release being prepared. Pre-1.0 releases are considered alpha and receive best
effort support only.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | Best effort        |

## Reporting a vulnerability

Please report security issues by opening a private issue at
<https://github.com/anomalyco/django-workflow-kit/issues> or emailing the
maintainers. Please include:

- A description of the vulnerability.
- The affected versions.
- Steps to reproduce.
- Impact assessment.

## Security guidance

- Never pass untrusted input to `eval()` or arbitrary code execution paths.
- Conditions and workflows are configured in Python, never in the database.
- Django authorization is always respected; admin and API code must not
  bypass transition permissions.