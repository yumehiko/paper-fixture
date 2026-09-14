# Internal fold plan contract

`paper-fixture-fold-plan-v1` is agent-generated internal state, never an operator form. It records source paths and each assembly's part, root face and fold edges. An edge references an intake `fold_id`, identifies parent and moving child faces, states `child_side` as `left` or `right` while walking the source endpoints from `[0]` to `[1]` on `print_front`, gives `mountain` or `valley` viewed from `print_front`, and stores `target_dihedral_deg` between 0 and 180. The generator cuts every named cell on those fixed source half-planes before it applies the face-tree transforms, and records the resolved signed rotation and matrices in its manifest.

Record files/pages/notes supporting each conclusion. Missing fixed side, viewing side, mountain/valley, or completed angle requires a named question rather than a default.
