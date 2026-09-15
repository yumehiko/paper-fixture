# Synthetic r3 note-removal evidence

`operator-intake.note-free.synthetic.ai` is a new copy of r2. The one-off [clear script](../../samples/operator-intake/clear-synthetic-r2-notes.jsx) opens r2, assigns `""` to every `documentRef.pageItems[i].note`, saves r3, reopens r3, and closes both documents without saving r2.

| Check | Result |
| --- | --- |
| r2 SHA-256 before / after save | `5d1318baafe8f261c3e5b74ccb3c412ff4a8117341e94d02e2f2ed93f68c4f9f` / same |
| r3 SHA-256 | `86de124946faab019a180e7966f04e39019493e52c757e0fd735a8b1f7aa2762` |
| path notes from r3 live export evidence | 0 nonempty |
| text notes from native read-only inspection | 0 nonempty |
| r2/r3 path geometry, layers, print PNG | equal |
| r2/r3 text geometry and style | equal |
| r3 `verify_illustrator_export.py` | passed: numeric live-DOM and fresh print-only PNG |

The dedicated read-only script [inspect-synthetic-r3-notes.jsx](../../samples/operator-intake/inspect-synthetic-r3-notes.jsx) was run to count every `pageItems` note, including groups. Its AppleEvent timed out after 120 seconds (`-1712`), leaving an empty `all-page-item-notes.json`; it does **not** constitute an all-item-note pass. No file was saved or altered by that inspection.
