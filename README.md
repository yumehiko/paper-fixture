# paper-fixture

Illustrator の展開図を起点に、Blender で紙什器を組み立て、確認・編集できるモデルへ受け渡す工程を補助するプロジェクトです。カメラ、照明、背景、納品レンダリングは既存の手動工程で設定します。

現在は試作の第1〜4段階まで完了しています。Illustrator から取り出した展開図を、印刷面・紙厚・穴を持つ編集可能な Blender の平面部材へ変換し、明示した instance 配置から編集可能な assembly bundle を生成できます。折りと両面印刷は対象外です。

組立前の配置入力は Blender なしでも検査できます。既存の7部材試作入力を検査し、
解決済みの4×4行列と任意の基準面・接触検査結果を出すには次を実行します。

```bash
python3 tools/verify_assembly_placement.py \
  --input samples/placement/three-shelf-placement.json \
  --repo-root .
```

入力契約と配置値の例は[数値配置と編集可能な `.blend` 受け渡し設計](docs/assembly-placement.md)を参照してください。

配置を含む bundle は次のように生成します。既存の出力先は manifest とすべての出力 hash が一致するときだけ再生成できます。手編集、欠落、未知ファイルを含む出力先は別の `--output-dir` を使うか、成果物ディレクトリだけを置換する `--force` を明示してください。

```bash
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
"$BLENDER" --background --python-exit-code 1 --python tools/build_assembly_bundle.py -- \
  --input samples/placement/three-shelf-placement.json --repo-root . \
  --output-dir build/local-assembly-check/three-shelf
```

成果物は `assembly.blend`、`textures/print-front.png`、2枚の preview、`verification.json`、`build-manifest.json` からなります。画像は bundle 内の相対パス `//textures/print-front.png` で参照されます。

### assembly bundle を使う

Blender 5.2.1 LTS があれば、追加の Python パッケージは不要です。初回は
`git clone https://github.com/yumehiko/paper-fixture.git`、更新時は checkout 内で
`git pull --ff-only` を実行します。次は入力検査、最短生成、生成物の別プロセス検証を
順に行う例です。検証 report は provenance を変えないよう bundle の外へ出します。

```bash
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
python3 tools/verify_assembly_placement.py \
  --input samples/placement/three-shelf-placement.json --repo-root .
mkdir -p build/local-assembly-check
"$BLENDER" --background --python-exit-code 1 --python tools/build_assembly_bundle.py -- \
  --input samples/placement/three-shelf-placement.json --repo-root . \
  --output-dir build/local-assembly-check/three-shelf
"$BLENDER" --background build/local-assembly-check/three-shelf/assembly.blend \
  --python-exit-code 1 --python tools/verify_assembly_bundle.py -- \
  --bundle build/local-assembly-check/three-shelf \
  --report /tmp/paper-fixture-assembly-verification.json
```

3つのコマンドが終了コード 0 なら、入力の全 instance の transform、ワールド AABB、
印刷面法線、指定した基準面・接触、閉じた mesh、UV、穴の既存フェーズ3相当の ray
検査、bundle 内の画像 hash が確認されています。開くのは bundle 内の
`assembly.blend` です。`textures/print-front.png`、`build-manifest.json`、
`verification.json`、`preview-perspective.png`、`preview-reference.png` も同じ
ディレクトリに保ってください。

bundle ディレクトリ全体は checkout の外へ移動できます。移動後も
`assembly.blend` を開くか、上記の最後の検証コマンドで確認します。画像は bundle
相対パスなので、`.blend` 単体を移動してはいけません。

同じ出力先への再生成は、前回 manifest の入力とすべての管理対象ファイルの hash が
一致する場合だけ許可されます。Blender で手編集した bundle、画像や preview を追加・
変更した bundle、未知ファイルを入れた bundle は通常の再生成が失敗します。改訂は新しい
`--output-dir` を使い、当該成果物の変更を破棄してよい場合だけ `--force` を使ってください。
`--force` は上流入力や別の bundle を変更しません。

## まず試す（macOS / Blender）

この手順は、リポジトリに含まれる `curve-hole` の書き出し束から Blender の板を生成し、保存後の `.blend` を再オープンして検証します。Illustrator は必要ありません。

### 前提環境

- macOS
- Git
- Blender **5.2.1 LTS**。このプロジェクトの開発・検証は 5.2.1 を基準にします。macOS ARM64 用公式配布物は [Blender 公式ダウンロード](https://download.blender.org/release/Blender5.2/blender-5.2.1-macos-arm64.dmg) から取得できます。

Python のパッケージ追加は、この Blender 生成・検証手順には不要です。スクリプトは Blender に同梱された Python で実行されます。

### 取得と実行

ターミナルで、任意の作業場所に新しく取得して実行します。`BLENDER` は Blender.app の実際の場所に合わせて変更してください。

```bash
git clone https://github.com/yumehiko/paper-fixture.git
cd paper-fixture

BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
"$BLENDER" --version

mkdir -p build/local-blender-check/curve-hole
"$BLENDER" --background --python-exit-code 1 --python tools/build_blender_panels.py -- \
  --export-json build/illustrator-export-r2/curve-hole/export.json \
  --print-png build/illustrator-export-r2/curve-hole/print-front.png \
  --output-dir build/local-blender-check/curve-hole
"$BLENDER" --background build/local-blender-check/curve-hole/panels.blend --python-exit-code 1 \
  --python tools/verify_blender_panels.py -- \
  --export-json build/illustrator-export-r2/curve-hole/export.json \
  --print-png build/illustrator-export-r2/curve-hole/print-front.png \
  --report build/local-blender-check/curve-hole/verification.json
```

`--python-exit-code 1` により、生成または検証スクリプトが失敗すると Blender も終了コード 1 を返します。

`"$BLENDER" --version` の出力が `Blender 5.2.1` であることを確認してから続けてください。

### 成功の確認と成果物

両方のコマンドが終了コード 0 で終わり、次のファイルができていれば成功です。

- `build/local-blender-check/curve-hole/panels.blend` — 編集可能な mesh の平面部材
- `build/local-blender-check/curve-hole/preview-front.png` / `preview-back.png` — 前後面のレビュー画像
- `build/local-blender-check/curve-hole/verification.json` — 再オープン後の形状、厚み、穴、材質、UV、画像リンクの検証結果
- `build/local-blender-check/curve-hole/build-manifest.json` — 入力パスと SHA-256 を含む生成記録

生成済みの閲覧用成果物は [`build/blender-panels-r3/curve-hole/`](build/blender-panels-r3/curve-hole/) と [`build/blender-panels-r3/three-shelf/`](build/blender-panels-r3/three-shelf/) にもあります。`.blend` の前面画像はリポジトリ内の相対パスでリンクされます。画像を含む正しい表示には、`.blend` 単体ではなくリポジトリ一式を保持したまま開いてください。

## Illustrator を含むフル工程

最短手順で使う `export.json` と `print-front.png` は、リポジトリに同梱されています。独自の `.ai` から作る場合は、macOS、Adobe Illustrator 2026、Illustrator を読み取り専用で操作する公開 MIT リポジトリ [py-ai-illustrator](https://github.com/yumehiko/py-ai-illustrator) が必要です。取得と環境作成のコマンドは [Illustrator 書き出し試作](docs/illustrator-export.md) に記載しています。

独自の `.ai` を渡す場合は、[Illustrator 入稿と寸法資料](docs/operator-intake.md)を先に読んでください。Blender オペレーターが `.ai` と人向けの寸法資料を agent に渡します。path note、JSON、XYZ座標、回転行列は不要です。

[Illustrator 書き出し試作](docs/illustrator-export.md) は exporter の規約と出力形式の詳細です。理想化サンプルの `.ai` 再生成は、追加で公開 MIT リポジトリ [illustrator-agent](https://github.com/yumehiko/illustrator-agent) を必要とする開発者向け手順であり、Blender を試すための前提ではありません。

## 困ったとき・フィードバック

問題を報告する際は、秘密情報や実案件データを添付せず、次を添えてください。

- macOS の版、CPU（Apple Silicon / Intel）、`"$BLENDER" --version` の出力
- 試したリポジトリのコミット ID（`git rev-parse HEAD`）と実行したコマンド
- 期待した結果、実際の結果、終了コード、エラー全文
- 可能なら `verification.json`、`build-manifest.json`、前後面プレビュー画像
- 影響度（実行不能・検証失敗・表示差異・質問）

[検証端末フィードバックを新規 Issue として報告する](https://github.com/yumehiko/paper-fixture/issues/new?template=verification-device-feedback.md) ためのテンプレートも用意しています。Blender 5.2.1 LTS での実機テスト結果は、成功・失敗を問わず後続フェーズでこの導線へ記録してください。

## ドキュメント

- [目的と対象範囲](docs/vision.md)
- [入力データの契約案](docs/input-contract.md)
- [処理構成とモデル表現](docs/architecture.md)
- [試作と検証の計画](docs/validation-plan.md)
- [設計インタビューと未決事項](docs/open-questions.md)
- [理想化入力サンプル（再生成手順）](samples/idealized_input/README.md)
- [Illustrator書き出し試作](docs/illustrator-export.md)
- [自作 `.ai` から assembly bundle を作る](docs/custom-ai-workflow.md)
- [Illustrator 入稿と寸法資料](docs/operator-intake.md)
- [Blender平面部材生成（第3段階）](docs/blender-panels.md)
- [数値配置と編集可能な `.blend` 受け渡し設計（第4段階）](docs/assembly-placement.md)

各文書では、ユーザーが示した要望と、検証前の設計提案を区別する。未回答の項目を決定事項として扱わない。
