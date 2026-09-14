# Illustrator 書き出し試作

`tools/export_illustrator.py` は PDF や `.ir.json` を解析せず、Adobe Illustrator 2026 で元 `.ai` を読み取り専用で開いた DOM を唯一の形状・印刷パスの情報源にする。閉じる際は `DONOTSAVECHANGES` を指定する。

入力規約は `PF_CUT`、`PF_PRINT_FRONT`、`PF_FOLD` レイヤーと、各レイヤー直下の `PF_PART_<部材ID>` グループである。path noteは使わない。`PF_CUT` の閉パスは包含関係から外周と穴を決め、曖昧な包含、未閉鎖輪郭、入れ子穴は停止する。`PF_FOLD` は部材group内の名前付き開直線として抽出する。詳しい入稿規則と寸法資料は[Illustrator 入稿と寸法資料](operator-intake.md)を参照する。

紙厚は現在の `.ai` DOM に保存されていないため、`material.json` を明示入力として受け取り、`export.json` に `external-explicit-input` と出所を記録する。渡さない場合は厚みを作らず `material.status: missing` を記録する。

macOS と Adobe Illustrator 2026 に加え、公開 MIT リポジトリ [py-ai-illustrator](https://github.com/yumehiko/py-ai-illustrator) の環境が必要である。`paper-fixture` と同じ親ディレクトリで、次のように取得する。このリポジトリはその環境を同梱しない。

```bash
git clone https://github.com/yumehiko/py-ai-illustrator.git
cd py-ai-illustrator
uv sync --extra dev
cd ../paper-fixture
```

```bash
PYTHON=../py-ai-illustrator/.venv/bin/python
"$PYTHON" tools/export_illustrator.py \
  build/input-samples-r2/curve-hole/curve-hole-input.native.ai \
  --material samples/idealized_input/material.json \
  --output-dir build/illustrator-export-r2/curve-hole
"$PYTHON" tools/verify_illustrator_export.py build/illustrator-export-r2/curve-hole \
  --source build/input-samples-r2/curve-hole/curve-hole-input.native.ai
```

出力の `export.json` は、左上原点・X右・Y下の mm 座標へ正規化した anchor と in/out Bézier handle、切断外周、穴、部材 ID、実寸、前面印刷パス、アートボード印刷範囲を保持する。`print-front.png` は Illustrator で `PF_PRINT_FRONT` だけを表示して144 dpiで出力するため、`PF_CUT`、注釈、折りガイドを含めない。`artboard.preview.png` は元アートボードとのレビュー用であり、Blender渡しの印刷PNGではない。

`validation.json` は live DOM から JSON への anchor / in-handle / out-handle の逆変換を検査する。試作の数値閾値は 0.000001 mm であり、実案件の寸法許容値ではない。さらに、検証時に元 `.ai` を読み取り専用で開き、`PF_PRINT_FRONT` だけを可視にした新しい PNG を出力して、提出された `print-front.png` の復号済み RGBA 画素列と一致することを確認する。これにより、赤を含む正当な印刷を拒否せず、色を問わず `PF_CUT`・注釈・折りガイドが混入した PNG を検出する。`geometry-overlay.svg` は元アートボードPNG上に、書き出し外周（マゼンタ）、穴（黄）、印刷パス（シアン）を重ねる2D証跡である。
