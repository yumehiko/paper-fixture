---
name: paper-fixture-assembly
description: Interpret prepared paper-fixture Illustrator input and human-readable dimensions into a verified editable Blender assembly with supported straight folds.
---

# Paper fixture assembly

Use this skill when a Blender operator provides a prepared `.ai` file and a dimension drawing, PDF, image, or natural-language note. Do not ask the operator for path notes, JSON, XYZ coordinates, or matrices.

1. Inspect intake and reference material. Identify thickness, part correspondence, completed orientation, and every fold's mountain/valley, completed face angle, fixed side, and order; retain source evidence.
2. For missing or contradictory facts, ask one concrete question naming the part and fold. With sufficient evidence, continue without blanket approval.
3. Locate the checkout that owns the prepared export (or search the available checkouts for `tools/build_fold_assembly.py`); invoke its generator and verifier with absolute paths. Do not assume the plugin installation directory contains the Blender runtime.
4. For an unfolded multi-part fixture, create explicit instances with `tools/build_assembly_bundle.py`. For each straight-fold part, create the private `paper-fixture-fold-plan-v1` and run `tools/build_fold_assembly.py`. A plan may contain several independent assemblies.
5. Record the source files/pages/notes supporting every fold decision. If an angle, mountain/valley, print-facing convention, or moving side is absent or contradictory, stop before generation and ask one named question. Do not write an inferred default into the plan.
6. Run the separate-process verifier. The fold builder writes a staging directory, verifies it, hashes its plan/export/texture and output files, then publishes it. Corrections use a new output directory; use `--force` only when deliberately replacing a bundle whose provenance is unchanged and whose hand edits may be discarded.

Mountain/valley is always viewed from `PF_PRINT_FRONT`; the plan's child is the moving side. `child_side` means left or right while walking source endpoints `[0]` to `[1]` on that printed face. Supported folds are straight, non-crossing, and form a tree. The first model uses rigid panels rotating about mid-plane hinges; it does not model bend radius, thickness collision, manufacture, curved/cyclic folds, or reverse synchronization of hand edits.
