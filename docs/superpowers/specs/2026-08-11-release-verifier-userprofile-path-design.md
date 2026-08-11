# Release Verifier User-Profile Path Safety Design

Date: 2026-08-11

## Context

`README.md` documents running `scripts/verify_release.ps1` with a test directory below the repository-owned `work` directory. The current verifier also places the whole `%USERPROFILE%` directory in its symmetric protected-path overlap list. When the repository is checked out anywhere below `%USERPROFILE%`, every valid `work` test directory overlaps that ancestor, so preflight always fails before release verification begins.

The failure is deterministic and occurred before mutex acquisition, backup creation, installer launch, registry mutation, or user-data mutation.

## Decision

Remove only `%USERPROFILE%` from the verifier's symmetric protected-path overlap list.

No other path-safety rule changes. In particular, ordinary and upgrade test roots must remain strict descendants of the verifier-owned repository `work` directory. They must continue to avoid overlap with:

- the installer;
- `%APPDATA%` and `%LOCALAPPDATA%`;
- DesktopCompanion roaming, local-data, and installed-program paths;
- recorded DesktopCompanion installation locations;
- repository metadata, approved input, artifacts, build, dist, packaging, scripts, source, and tests.

This is the smallest change that makes the documented command usable from a normal checkout below the user's profile while retaining protection for every concrete sensitive location.

## Safety Rationale

The verifier never accepts an arbitrary descendant of `%USERPROFILE%`. `Assert-TestRoot` first requires the target to be a strict child of the repository-owned `work` root and rejects reparse components. Recursive removal remains constrained to that same `work` root. The broad `%USERPROFILE%` ancestor therefore adds no useful protection for the documented layout; it only rejects the entire valid domain.

Concrete user data and installation paths remain protected independently. A target outside `work`, equal to `work`, overlapping a named protected path, containing reparse components, or overlapping the ordinary/upgrade peer remains invalid.

## Verification Design

Use the production script itself as the acceptance boundary:

1. RED: record the current `-PreflightOnly` failure for the documented `work\release-smoke` target below `%USERPROFILE%`.
2. GREEN: after the one-line protected-list correction, the same preflight must exit successfully without creating an install root or mutating product state.
3. Negative safety checks must still reject a test root outside `work` and a test root equal to `work`.
4. Re-run focused script/static checks and `git diff --check`.
5. Independently review the code and evidence before production execution.
6. Run the original release-verification workflow against the freshly built installer, covering ordinary install/self-test/uninstall and upgrade install/self-test/uninstall.
7. Confirm the isolated roots and backups are removed, no DesktopCompanion process remains, protected registry/data state is restored, and the existing installed application tree matches the pre-run snapshot.

## Scope

This change does not modify application runtime code, pet-pack behavior, installer contents, product installation paths, or the user's current DesktopCompanion installation. It does not authorize uploading or pushing. If any later verifier failure reveals a different defect, stop after safe rollback and diagnose it separately.
