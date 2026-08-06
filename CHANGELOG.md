# Changelog

Notable changes to this project will be documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and release versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Public contribution, conduct, support, and issue-reporting guidance.
- Installable console entry points and continuous-integration checks.
- An interactive-shell startup wordmark with independently sourced shell and
  kernel versions.

### Changed

- The Phase 2b comparative-evaluation research record—candidate ledger, stage
  evidence artifacts, JSON schemas, preregistration, evaluation protocol, and
  work log—moved to a separate private repository. It recorded screening
  verdicts naming third-party public repositories. No published claim depended
  on it: learned routing is disabled and no comparative agent run has been
  authorized.
- Package metadata now matches the public repository name.
- Process cleanup now isolates each POSIX invocation and uses a guarded Windows
  Job Object launch path so timeout or interruption stays within the owned tree.
- Repository licensing changes from MIT to Apache License 2.0 from this change
  forward; previously published MIT-licensed revisions remain available under
  their original terms.

### Fixed

- The package no longer fails to import on Windows. The event log and routing
  state store used POSIX-only `fcntl` file locking unconditionally; they now
  go through a small cross-platform lock helper that uses `msvcrt` on
  Windows.

The source currently identifies itself as version `0.1.0`, but no GitHub or
package-index release has been published. A versioned section and comparison
link will be added when the first release is tagged.
