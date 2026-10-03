# Contributing

OwnedPulse is maintained by one person as a portfolio demonstrator. Contributions are welcome but reviewed as time allows.

## Issues

- **Bugs**: use the bug report template. Include your OwnedPulse version (shown in the UI sidebar, or `cat api/VERSION`), OS, GPU and driver, `DOCLING_VARIANT`, and the relevant part of `./install.sh` output or `docker logs <container>`.
- **Questions and ideas**: open an issue.
- **Security problems**: do not open an issue. See [SECURITY.md](SECURITY.md).

Remove passwords, API keys and hostnames from anything you paste.

## Pull requests

- Open an issue first for anything beyond a small fix, so we can agree on the approach.
- One concern per pull request.
- Do not commit `.env`, data directories, model files or generated artefacts.
- Changes to the base corpus (`config/corpus_manifest.json`) need a stated rationale; extending corpus scope is treated as a change control event.

## License

By contributing, you agree that your contributions are licensed under the Apache License 2.0, as the rest of the project.
