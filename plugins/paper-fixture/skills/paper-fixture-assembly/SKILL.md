---
name: paper-fixture-assembly
description: Interpret prepared paper-fixture Illustrator input and human-readable dimensions into a verified editable Blender assembly with supported straight folds.
---

# Paper fixture assembly

Use this skill when a Blender operator provides a prepared `.ai` file and a dimension drawing, PDF, image, or natural-language note. Do not ask the operator for path notes, JSON, XYZ coordinates, or matrices.

1. Inspect intake and reference material. Identify thickness, part correspondence, completed orientation, and every fold's mountain/valley, completed face angle, fixed side, and order; retain source evidence.
2. For missing or contradictory facts, ask one concrete question naming the part and fold. With sufficient evidence, continue without blanket approval.
3. Create the private `paper-fixture-fold-plan-v1`, validate it, generate the bundle, and run its separate-process verifier. Corrections create a new output directory.

Mountain/valley is always viewed from `PF_PRINT_FRONT`; the plan's child is the moving side. Supported folds are straight, non-crossing, and form a tree. The first model uses rigid panels rotating about mid-plane hinges; it does not model bend radius, thickness collision, manufacture, curved/cyclic folds, or reverse synchronization of hand edits.
