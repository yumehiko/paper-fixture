# 開発者向け旧互換手順: 自作 `.ai` から assembly bundle を作る

> **通常の入稿手順ではありません。** Illustrator 担当は [Illustrator 入稿と寸法資料](operator-intake.md) に従い、`.ai` と人向けの寸法資料だけを Blender オペレーター経由で agent に渡します。path note、material / placement JSON、XYZ 座標、回転行列は入力しません。この文書は既存の JSON 配置 builder を再現・保守する開発者向けの旧互換経路です。

同梱サンプルを試したあとに、自作の Illustrator 展開図から Blender で確認・編集できる `assembly.blend` を作る手順です。対象は、片面印刷を持つ独立した平面部材を数値で配置する工程です。カメラ、照明、背景、納品レンダリングは、この bundle を開いた後の既存の手動工程で設定します。

例では `CUSTOM_PANEL` という 1 枚の板を使います。ID、寸法、位置、回転は自分の部材に読み替えてください。既存 fixture と過去の build は編集せず、新しい作業コピーと revision を使います。

## 前提

- macOS、Adobe Illustrator 2026、Blender 5.2.1 LTS。
- checkout と同じ親ディレクトリにある [py-ai-illustrator](https://github.com/yumehiko/py-ai-illustrator) の環境。未取得なら [Illustrator 書き出し試作](illustrator-export.md) の準備手順を使います。

Blender の生成・検証に追加 Python パッケージは不要です。Illustrator からの export とその検証だけが `py-ai-illustrator` を使います。

## 1. Illustrator の作業コピーを整理する

元の `.ai` を開き、**別名で保存したコピー**だけを編集します。exporter はそのコピーを読み取り専用で開き、保存せず閉じます。1 export package は **1 アートボードだけ**です。複数アートボードなら、対象の 1 枚を別ファイルにコピーし、印刷 PNG に不要な余白もそこで整理します。

レイヤーパネルに次を置きます。

| レイヤー | 内容 |
| --- | --- |
| `PF_CUT` | 切断外周と穴だけ。各部材の閉じたストロークパス、塗りなし。 |
| `PF_PRINT_FRONT` | 前面の印刷図柄だけ。色は自由で、赤も使えます。 |
| `PF_ANNOTATION`（任意） | パスを含まないメモなど。印刷 PNG には入りません。 |
| `PF_FOLD`（任意） | 折りガイド。現在のモデル生成では使いません。 |

各部材について、`PF_CUT` と `PF_PRINT_FRONT` の**直下**に同名のグループを作ります。部材 ID が `CUSTOM_PANEL` なら、両方に `PF_PART_CUSTOM_PANEL` を置きます。対象パスをそのグループへ移し、入れ子グループにはしません。部材 ID は export の `parts[].id` と placement の `part_id` で同じ文字列を使います。

### 旧規約の path note を付ける

対象パスを選び、Illustrator の **ウィンドウ → 属性** を開きます。属性パネル右上のメニューから **Show Note（ノートを表示）** を選んで Note 欄を出し、そこへ値を設定します。各 path の note は、次のように `py-ai-path:` に JSON を続けた 1 行です。対象 path はすべて閉じます。

| レイヤー | 用途 | note | 形状 |
| --- | --- | --- | --- |
| `PF_CUT` | 外周 | `py-ai-path:{"id":"cut.CUSTOM_PANEL.outer"}` | 閉じた、塗りなしのパスがちょうど 1 本 |
| `PF_CUT` | 穴 | `py-ai-path:{"id":"cut.CUSTOM_PANEL.hole.01"}` | 閉じた、塗りなしのパス。番号は部材内で一意 |
| `PF_PRINT_FRONT` | 印刷 | `py-ai-path:{"id":"print.CUSTOM_PANEL.base"}` | 閉じた path。複数可。`base` は任意の役割名 |

exporter はレイヤーにかかわらず文書中の **全 Illustrator pathItem** を読みます。したがってパスを含む寸法線、トンボ、ガイド、アウトライン文字、注釈は `PF_ANNOTATION` へ移しても無視されません。作業コピーから外すか、`PF_CUT` / `PF_PRINT_FRONT` の直下 `PF_PART_<ID>` に置き、上記の note と閉じた状態を設定してください。`PF_CUT` には `outer` と `hole.<番号>` 以外を置けません。`PF_PRINT_FRONT` の path も閉じたものが必要です。

通常のライブテキスト、配置画像、ラスタ画像は export.json の path 情報としては表現されません。`PF_PRINT_FRONT` をラスタ化した PNG に写る場合はありますが、文字・配置画像・ラスタ画像を含む自作入力はこの開発機 smoke で未検証です。アウトライン文字は通常 `CompoundPathItem` の下に pathItem を持ちますが、現行 exporter は path の親が `PF_PART_<ID>` group であることを要求するため拒否します。Compound Path の解除は穴や見た目を変え得るので推奨しません。アウトライン文字は現行契約では非対応です。複数アートボードは `exactly one artboard is required` で明示的に非対応です。

## 2. 明示入力を作る

作業コピーを `input/custom-panel-r1/custom-panel.ai` に保存し、同じ場所に `material.json` を作ります。紙厚は `.ai` ではなくこの明示入力で渡します。

```json
{
  "thickness_mm": 3.0,
  "front_side": "PF_PRINT_FRONT",
  "back_and_edge": "paper base color"
}
```

次に `input/custom-panel-r1/placement.json` を作ります。`sources` は repository-relative path です。`instance.id` は一意なら自由、`part_id` は Illustrator の部材 ID と一致させます。世界座標は X=右、Y=奥、Z=上、単位 mm。`translation_mm` は部材の左上原点・中央面の座標で、`rotation_deg_xyz` は固定世界軸の XYZ extrinsic 度です。

```json
{
  "schema_version": "0.1",
  "status": "custom-input",
  "unit": "mm",
  "world": {
    "origin": "floor, back mid-plane, left inner face",
    "x_axis": "right",
    "y_axis": "back",
    "z_axis": "up",
    "rotation_mode": "XYZ extrinsic degrees"
  },
  "sources": {
    "panels": "build/custom-ai-r1/export/export.json",
    "print_front": "build/custom-ai-r1/export/print-front.png"
  },
  "instances": [{
    "id": "custom-panel-on-floor",
    "part_id": "CUSTOM_PANEL",
    "translation_mm": [0, 0, 1.5],
    "rotation_deg_xyz": [0, 0, 0]
  }],
  "checks": {
    "expected_checks": [{
      "id": "panel-bottom-on-floor",
      "instance_id": "custom-panel-on-floor",
      "kind": "world_aabb_face",
      "face": "min_z",
      "target_mm": 0,
      "tolerance_mm": 0.05
    }],
    "expected_contacts": []
  }
}
```

厚み 3 mm の中央面は Z=0 なので、床に置くこの例は Z=1.5 です。複数部材や同一部材の複数配置は `instances` を追加します。ID から組立形状を推測せず、各 instance の移動・回転を明示します。接触や上面高さを確認したい場合だけ `checks` を追加します。詳しい契約は [数値配置と編集可能な `.blend` 受け渡し設計](assembly-placement.md) を参照してください。

## 3. export、検証、Blender bundle を作る

新規 output directory を使います。以下は `build/custom-ai-r1/` がまだ無い状態で、リポジトリ直下から実行する例です。

```bash
(
set -e
PYTHON=../py-ai-illustrator/.venv/bin/python
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender

"$PYTHON" tools/export_illustrator.py \
  input/custom-panel-r1/custom-panel.ai \
  --material input/custom-panel-r1/material.json \
  --output-dir build/custom-ai-r1/export

"$PYTHON" tools/verify_illustrator_export.py \
  build/custom-ai-r1/export --source input/custom-panel-r1/custom-panel.ai

python3 tools/verify_assembly_placement.py \
  --input input/custom-panel-r1/placement.json --repo-root .

"$BLENDER" --background --python-exit-code 1 --python tools/build_assembly_bundle.py -- \
  --input input/custom-panel-r1/placement.json --repo-root . \
  --output-dir build/custom-ai-r1/assembly

"$BLENDER" --background build/custom-ai-r1/assembly/assembly.blend \
  --python-exit-code 1 --python tools/verify_assembly_bundle.py -- \
  --bundle build/custom-ai-r1/assembly \
  --report build/custom-ai-r1/assembly-verification.json
)
```

export の検証は元 `.ai` を読み取り専用で開き、`PF_PRINT_FRONT` だけを fresh export して提出 PNG と復号済み RGBA 画素列を比較します。赤い印刷は制限しません。全コマンドが終了コード 0 なら、`build/custom-ai-r1/assembly/assembly.blend` を Blender で開きます。

`textures/print-front.png`、`build-manifest.json`、`verification.json`、2 枚の preview は bundle と同じディレクトリに残します。テクスチャは bundle 相対 path なので、`.blend` 単体では移動せず bundle ディレクトリ一式を扱います。Blender 内で `PF_PART_<ID>` mesh と instance は通常どおり確認・編集できます。

## 困ったとき・制約

| 症状 | 修正 |
| --- | --- |
| `exactly one artboard is required` | 対象を 1 アートボードの作業コピーへ分ける。 |
| `must be directly inside group` | path を対象レイヤー直下の `PF_PART_<ID>` へ移し、入れ子 group を外す。 |
| note が無い / duplicate | 対象レイヤーの全 path に上記 note を付け、ID を一意にする。 |
| `path must be closed` | 外周、穴、印刷図柄を閉じる。線だけの印刷やライブテキストは処理できない。 |
| `outer contour must be unfilled` | `PF_CUT` の外周・穴を塗りなしにする。 |
| `PF_PRINT_FRONT paths are missing` | 同じ部材 ID の print group と閉じた印刷 path を作る。 |
| placement の `part_id is unknown` | `part_id` を export.json の `parts[].id` に一致させる。 |
| PNG 検証失敗 | `print-front.png` を編集せず、新規 output directory に export をやり直す。 |
| bundle 再生成拒否 | 手編集済みなら新しい `--output-dir` を使う。置換してよい当該 bundle だけ `--force` を使う。 |

この旧互換経路の既存 fixture は開発用のものです。通常の無ノート入稿の実測結果は [Illustrator 入稿と寸法資料](operator-intake.md) の synthetic fixture 記録を正本とします。利用者の実案件での実機検証は [#6](https://github.com/yumehiko/paper-fixture/issues/6) で収集します。

折り、両面印刷、未整理 `.ai` の意味推定、アウトライン文字、複数アートボード、製造可能性・納品色管理の保証は対象外です。ライブテキスト、配置・ラスタ画像は上記のとおり未検証です。新しい入力機能が必要なら exporter を暗黙に拡張せず、別 Issue にしてください。
