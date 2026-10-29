# Local Release Readiness

Run from the repository root:

```sh
.venv/bin/python check_release.py
```

This read-only command checks the existing PostGIS/Redis services, active
screening-layer provenance, integrated master structure and source manifests,
the survival artifact contract, and staged Git content. It does not download,
publish, train, modify the Git index, or change private data. Exit status 1
means a release blocker was found. Redis failure is a warning because the
database fallback remains available.

The data audit reuses `demo/maintain_data.py:training_inventory`: source files
must exist at their declared sizes, SAMPLE inputs must remain reference-only,
and tract identifiers, geography, feature tables and dictionary must agree.
It audits files on disk rather than trusting the last saved inventory report.

## Immutable Map Layers

`groundwork_backend.pipeline.export_screening` records the integrated release
and a combined content hash of the application, scoring, evidence-policy and
hex-surface code. Both must match for the live tile resolver to serve that
snapshot. Outdated layers return HTTP 409; the dashboard uses the current
GeoJSON surface instead. Published snapshots are not overwritten. Redis tile
keys already include snapshot identifiers, so publishing a new snapshot does
not reuse obsolete cache entries.

On October 28 the default bistro layer was republished as
`screening_default_20261028_policy_v1`: 7,575 cells across resolutions 7, 8 and 9,
from release `20261028T130023Z_2fba02cd`. Earlier snapshots remain intact.
Other concepts retain the existing on-demand GeoJSON path.

After the property integration audit, the active replacement is
`screening_default_20261028_dashboard_v3`, with the same 7,575 cells and source
release but refreshed application-code provenance. The previous snapshot is
preserved.

The subsequent feature-heatmap release is
`screening_default_20261028_features_v4`: 9,601 published cells, including
eligible Staten Island coverage previously excluded by the grid builder.
The integrated source release is unchanged. Individual feature surfaces use
the metric-specific GeoJSON API; the default composite retains vector tiles.

`screening_default_20261028_boundary_v5` preserves the same 9,601 cells with
current application provenance after the city-boundary route was added.

## Assessment Basis

Overview, Compare and Reports distinguish Cuisine-Supported Fit, Limited Cuisine
Evidence and General Location Fit. These describe the evidence used for
screening, not measured customer demand or a probability of business success.
Related cuisine categories do not become verified demand substitutes.

## Git Safety And Scientific Scope

The staged-content check rejects private data paths, account databases,
credentials matching common token/private-key patterns, native model artifacts
and files larger than 5 MiB. It examines staged blobs, not unstaged replacements.
This is a preflight guard, not an exhaustive secret scanner or authorization to
upload datasets. Review the final staged diff manually before pushing.

`ready_for_screening_demo` does not mean ready for validated survival inference.
An absent admissible survival artifact is explicitly reported as screening-only.
An invalid configured artifact blocks release. Archive-disappearance research
models remain separate from verified permanent-closure outcomes and are not
silently deployed by this command.
