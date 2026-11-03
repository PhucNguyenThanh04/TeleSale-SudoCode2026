# Local dataset bundles

This directory holds local audio datasets and their downloaded/exported ZIP
bundles. Its contents, including audio, segment metadata, manifests and ground
truth, are excluded from Git. Removing a bundle from Git tracking does not
delete the local copy.

Keep source dialogues and reusable examples in [`speech/dialogues/`](../speech/dialogues/)
and [`speech/examples/`](../speech/examples/). See the [speech guide](../speech/README.md)
for dataset preparation and use. Scripts normally use `speech/data/datasets/`,
which is also excluded from Git; restore downloaded bundles there or pass their
local paths explicitly as described in that guide.

Use separately managed storage when sharing dataset bundles with the team.
Do not add audio exports, trace exports, model caches or evaluation run output
to the application repository. Reviewed test fixtures and benchmark scenario
definitions remain versioned in their existing source directories.
