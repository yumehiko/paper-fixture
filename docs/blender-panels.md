# Blender 平面部材生成（第3段階）

`tools/build_blender_panels.py` は、第2段階の `export.json` と同じディレクトリの `print-front.png` から、折りや組立配置を適用していない編集可能な平面部材を作る。入力元の `.ai`、`export.json`、PNG は変更しない。

## 再実行

Blender 4.4.1 で、リポジトリ直下から実行する。

```bash
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
$BLENDER --background --python tools/build_blender_panels.py -- \
  --export-json build/illustrator-export-r2/curve-hole/export.json \
  --print-png build/illustrator-export-r2/curve-hole/print-front.png \
  --output-dir build/blender-panels-r3/curve-hole
$BLENDER --background build/blender-panels-r3/curve-hole/panels.blend \
  --python tools/verify_blender_panels.py -- \
  --export-json build/illustrator-export-r2/curve-hole/export.json \
  --print-png build/illustrator-export-r2/curve-hole/print-front.png \
  --report build/blender-panels-r3/curve-hole/verification.json
```

`three-shelf` に対しても同じコマンドで入力と出力ディレクトリだけを替える。出力は `panels.blend`、表面と裏面のレビュー用 `preview-front.png` / `preview-back.png`、再オープン検証の `verification.json`、入力対応を記した `build-manifest.json` である。マニフェストはリポジトリ相対入力パスと各入力のSHA-256を保存する。`.blend` の画像リンクも同じチェックアウト内の相対パスで保存するため、リポジトリ一式を移動して再オープンできる。単体の `.blend` だけを別配布する用途は保証しない。

## 保存する局所基準

各 `PF_PART_<ID>` は Blender の編集可能な mesh で、カスタムプロパティにも次を保存する。

| 項目 | 規則 |
| --- | --- |
| 原点 | その部材の `placement_bounds_mm` の左上（AI座標） |
| 局所 X | アートボードの右（mm） |
| 局所 Y | アートボードの上（mm）。AI の下向きYを反転した軸 |
| 前面法線 | 局所 +Z |
| 厚み基準 | Z=0 が中央面。前面印刷は `+thickness_mm/2`、裏面は `-thickness_mm/2` |
| UV | アートボード全体の `print.range_mm` を `PF_PRINT_UV` に対応付け、PNGの上向き/下向き差をV反転で補正 |

従って第4段階は、配置指定をこの局所原点・軸・中央面に対する変換として適用できる。今回の scene 内の座標は元アートボード上の平面レイアウトをレビューしやすくするための位置であり、棚の完成配置ではない。

## 暫定値と対象外

曲線は各 cubic Bézier を Blender の 12 分割で評価する。この値は R20 曲線を視認できる形にする試作値であり、実案件の寸法許容値ではない。テクスチャは書き出しPNGを `print.range_mm` に無補間で対応付ける。出力解像度や色管理の納品要件はまだ決めていない。

前面だけに `PF_PRINT_FRONT` の画像材質を割り当て、裏面・外周・穴の断面には `PF_PAPER_BASE` を割り当てる。両面印刷、折り、組立の数値配置、実案件向けの曲線許容差およびテクスチャ要件は対象外である。

入力検査はスキーマ、座標系、正の明示厚み、PNGの存在、ユニーク部材ID、正の範囲、閉じた非ゼロ面積の外周・穴を停止条件として扱う。隙間を閉じるなどの形状変更を伴う自動修復は行わない。
