# Release process

Distribution: `enforce-type`; import: `enforce_type`; initial version: `0.1.0`.

1. Merge focused PRs in dependency order with fresh passing checks and verify final
   main. Preserve parent branches while any open dependent still targets them.
2. Run `uv run --frozen python scripts/check_distribution.py --tag v0.1.0 --output-dir /path/to/new/candidate`.
   Verify version, metadata, exact file allowlists, installed tests/examples and
   source rebuild parity. Review the printed SHA256 receipts.
3. Confirm the PyPI Trusted Publisher uses owner `outside-labs`, repository
   `enforce_type`, workflow `release.yaml` and environment `pypi`.
4. The GitHub `pypi` environment permits only the `v0.1.0` tag. Future releases need
   their intended tag allowed before publication.
5. When publication is authorized, push an immutable annotated `v0.1.0` tag on the
   verified main commit. This starts `.github/workflows/release.yaml`.
6. The workflow reruns checks, verifies tag/version/main agreement and exact
   distributions, then passes those artifacts to a separate OIDC publishing job.
   Only that job has `id-token: write` and uses the `pypi` environment.
7. Verify workflow success, exact PyPI file digests and actual downloaded bytes,
   and a fresh uncached registry installation. Publish the GitHub release with
   the same workflow files and verify its asset hashes too. Record receipts in
   the publication issue and Project.

Never replace released tags/files or rebuild artifacts between verification and
upload. No application deployment is part of package publication. License terms
remain unspecified.
