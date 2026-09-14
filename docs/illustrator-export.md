# Illustrator 書き出し試作

`tools/export_illustrator.py` は PDF や `.ir.json` を解析せず、Adobe Illustrator 2026 で元 `.ai` を読み取り専用で開いた DOM を唯一の形状・印刷パスの情報源にする。閉じる際は `DONOTSAVECHANGES` を指定する。

入力規約は `PF_CUT` と `PF_PRINT_FRONT` レイヤー、各レイヤー直下の同名 `PF_PART_<部材ID>` グループ、各パスの `py-ai-path:{"id":"cut.<部材ID>.<役割>"}` または `print.<部材ID>.<役割>` note である。外周は `cut.<部材ID>.outer`、穴は `cut.<部材ID>.hole.<番号>` とする。曖昧なグループ所属、未閉鎖輪郭、重複 ID、欠けた印刷パス、単位不明の座標は停止する。これは r2 の事前整理規則を機械検査できるようにした暫定規約であり、一般の Illustrator ファイルを推定で受理しない。

紙厚は現在の `.ai` DOM に保存されていないため、`material.json` を明示入力として受け取り、`export.json` に `external-explicit-input` と出所を記録する。渡さない場合は厚みを作らず `material.status: missing` を記録する。

`py-ai-illustrator` と Adobe Illustrator 2026 を導入した macOS の Python 環境で実行する。依存ライブラリの導入は [py-ai-illustrator](https://github.com/yumehiko/py-ai-illustrator) の手順に従う。このリポジトリはその環境を同梱しない。

```bash
PYTHON=/実際の/py-ai-illustrator環境/bin/python
"$PYTHON" tools/export_illustrator.py \
  build/input-samples-r2/curve-hole/curve-hole-input.native.ai \
  --material samples/idealized_input/material.json \
  --output-dir build/illustrator-export-r2/curve-hole
"$PYTHON" tools/verify_illustrator_export.py build/illustrator-export-r2/curve-hole
```

出力の `export.json` は、左上原点・X右・Y下の mm 座標へ正規化した anchor と in/out Bézier handle、切断外周、穴、部材 ID、実寸、前面印刷パス、アートボード印刷範囲を保持する。`print-front.png` は Illustrator で `PF_PRINT_FRONT` だけを表示して144 dpiで出力するため、`PF_CUT`、注釈、折りガイドを含めない。`artboard.preview.png` は元アートボードとのレビュー用であり、Blender渡しの印刷PNGではない。

`validation.json` は live DOM から JSON への anchor / in-handle / out-handle の逆変換を検査する。試作の数値閾値は 0.000001 mm であり、実案件の寸法許容値ではない。`geometry-overlay.svg` は元アートボードPNG上に、書き出し外周（マゼンタ）、穴（黄）、印刷パス（シアン）を重ねる2D証跡である。
