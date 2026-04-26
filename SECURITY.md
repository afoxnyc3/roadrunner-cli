# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 1.0.x   | Yes       |
| < 1.0   | No        |

## Reporting a Vulnerability

If you discover a security issue, please report it privately via GitHub's
[Security Advisories](https://github.com/afoxnyc3/roadrunner-cli/security/advisories/new) form.

We aim to acknowledge reports within 72 hours and ship a fix or mitigation
within 14 days for confirmed issues. Please do not open public issues or
pull requests for unfixed vulnerabilities.

## Scope

Roadrunner is a local developer tool that reads and writes files in the
current project, runs validation commands declared in `tasks/tasks.yaml`,
and shells out to `git`. The threat model assumes a trusted operator on a
trusted workstation. Reports about untrusted input from `tasks.yaml` are
in scope; reports that require an attacker who already has write access
to your project directory are generally not.
