# paper-fixture

Illustrator の展開図から、Blender で確認・編集できる紙什器の assembly bundle を作るためのプロジェクトです。このページは初回の作業を、入力準備から `.blend` の確認・修正まで順に案内します。

この工程が扱うのは編集可能な assembly bundle までです。カメラ、照明、背景、納品レンダリングは Blender で通常どおり設定します。曲線fold、交差fold、両面印刷、折り半径・強度・製造可能性の保証は対象外です。対応する直線foldの範囲は [fold workflow](docs/fold-workflow.md) を参照してください。

## 全体の流れ

[工程図: `.ai` から Blender 組立を確認・編集するまで](docs/onboarding-workflow.md) は、Illustrator 担当、Blender 担当、agent の担当、渡すファイル、生成・検証、修正ループを GitHub 上で確認できる Mermaid 図です。以下のチュートリアルはこの図と同じ順序です。

## 0. 用意するもの

- macOS、Git、Blender **5.2.1 LTS**。Blender の生成・検証には追加の Python パッケージは不要です。
- 独自の `.ai` を書き出す場合は Adobe Illustrator 2026 と、[Illustrator exporter の準備](docs/illustrator-export.md) にある `py-ai-illustrator` 環境。
- agent を実行できる Codex の task。agent は入力を読み、必要な生成・検証コマンドを実行します。

Blender は [公式ダウンロード](https://download.blender.org/release/Blender5.2/blender-5.2.1-macos-arm64.dmg) から入手できます。Intel Mac では対応する公式配布物を選んでください。以下では標準のアプリケーション配置を使います。

```bash
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
"$BLENDER" --version
```

`Blender 5.2.1` と表示されたら続けます。ここまでの環境確認はこのリポジトリの実機工程では未実測です。実案件での利用者検証は [#6](https://github.com/yumehiko/paper-fixture/issues/6) で収集します。

## 1. リポジトリを取得し、skill plugin を導入する

```bash
git clone https://github.com/yumehiko/paper-fixture.git
cd paper-fixture
git rev-parse --short HEAD
```

この checkout には [`plugins/paper-fixture/`](plugins/paper-fixture/) として **plugin のソース**が入っています。clone しただけでは Codex に導入・有効化されません。

1. checkout のルートで `codex plugin marketplace add .` を実行します。
2. `codex plugin add paper-fixture@paper-fixture` を実行します。
3. Codex を再起動するか、新しい task を開き、`$paper-fixture-assembly` を使えることを確認します。

この repo-scoped marketplace は [`.agents/plugins/marketplace.json`](.agents/plugins/marketplace.json) にあり、Paper Fixture の source `./plugins/paper-fixture` を指します。公式の marketplace とローカル plugin の導入手順は [OpenAI Developers: Package your plugin](https://developers.openai.com/plugins/build/plugins) に従います。上の Codex 導入操作は本PRでは未実測です。

plugin は agent の作業手順を追加するものです。Blender 本体や Illustrator exporter 用 Python 環境、そして対象の `.ai` と寸法資料を plugin 内へ導入するものではありません。agent の task から、この checkout と入力ファイルにアクセスできる必要があります。

## 2. テンプレートを作業用に複製して編集する

テンプレートは公開用の架空の見本です。実案件のデータや製造済みの仕様ではありません。テンプレート自体は変更せず、作業ディレクトリに複製します。

```bash
mkdir -p work/display-r1
cp templates/operator-intake/operator-intake-template.ai \
  work/display-r1/display-intake.ai
cp templates/operator-intake/dimensions-template.md \
  work/display-r1/display-dimensions.md
```

Illustrator で `work/display-r1/display-intake.ai` を開き、すぐに別名保存されていることを確認します。`PF_CUT`、`PF_PRINT_FRONT`、必要なら `PF_FOLD` の `PF_PART_EXAMPLE_*` を実部材のグループへ置き換え、見本の部材を削除します。寸法、紙厚、完成時の向き、部材同士の関係、折り条件は `display-dimensions.md` に書きます。PDF、寸法入り画像、完成写真、自然文メモでも構いません。

入力規則と提出前チェックは [Illustrator 入稿と寸法資料](docs/operator-intake.md)、テンプレートの詳しい編集手順は [templates/operator-intake/README.md](templates/operator-intake/README.md) にあります。人が path note、JSON、XYZ 座標、回転行列を作成・記入する必要はありません。

## 3. agent へ `.ai` と寸法資料を渡す

Codex の新しい task をこの checkout で開き、次のように渡します。

> `work/display-r1/display-intake.ai` と `work/display-r1/display-dimensions.md` から、検証済みの editable Blender assembly bundle を作ってください。資料が不足または矛盾していれば、部材名・折線名を示して質問してください。

導入済みの skill がこの入力を案内し、Illustrator exporter、fold の有無に応じた生成器、別プロセスの検証器を実行します。十分な資料なら承認待ちを挟みません。不足や矛盾があれば、たとえば `BODY` の `FOLD_02` の山谷・角度・可動側のように、必要な箇所だけ質問します。

## 4. 生成した bundle を確認する

agent が示す新しい output directory を bundle の単位で扱います。成功時には少なくとも次が同じディレクトリにあります。

- `assembly.blend` — Blender で編集するファイル
- `textures/print-front.png` — `.blend` から相対参照される前面画像
- `verification.json` と manifest — 生成・再オープン検証の記録
- fold がない bundle では `preview-perspective.png` と `preview-reference.png`

`assembly.blend` を Blender で開くときも、上の同伴ファイルを移動・削除しません。bundle 全体は checkout の外へ移動できますが、`.blend` 単体だけを移動すると画像参照が切れます。生成器と検証器が終了コード 0 で完了し、`verification.json` が作られていることを確認してから、形状・画像・配置を確認します。

## 5. Blender で修正する

確認後は `assembly.blend` の mesh、transform、材質を Blender で通常どおり編集・保存できます。手編集は生成済み bundle の変更です。入力を直して再生成する場合は、既存bundleを上書きせず、新しい revision の output directory を agent に指定します。これにより、検証済みのbundleと改訂版を比較できます。

## 同梱サンプルを先に試す

Illustrator を使わず、同梱された `curve-hole` の書き出し束で Blender の板生成と再オープン検証を試せます。出力先は新しく作成します。

```bash
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
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

両方が終了コード 0 なら、`panels.blend`、前後面preview、`verification.json`、`build-manifest.json` が作られます。このサンプルは通常の `.ai` 入稿からの全工程を実測するものではありません。

## 詳細・既存の利用経路

- [工程図と修正ループ](docs/onboarding-workflow.md)
- [Illustrator 入稿と寸法資料](docs/operator-intake.md)
- [直線foldを含む assembly の範囲と処理](docs/fold-workflow.md)
- [Illustrator exporter の規約と開発環境](docs/illustrator-export.md)
- [Blender平面部材生成](docs/blender-panels.md)
- [数値配置と編集可能な `.blend` 受け渡し設計](docs/assembly-placement.md)
- [開発者向け旧互換CLI: 自作 `.ai` から assembly bundle を作る](docs/custom-ai-workflow.md)
- [入力データ契約](docs/input-contract.md)、[理想化入力サンプル](samples/idealized_input/README.md)
- [目的と対象範囲](docs/vision.md)、[処理構成](docs/architecture.md)、[検証計画](docs/validation-plan.md)、[未決事項](docs/open-questions.md)

## 困ったとき・フィードバック

問題を報告する際は、実案件データや秘密情報を添付せず、macOSの版、CPU、`"$BLENDER" --version` の出力、checkoutのコミットID、実行コマンド、終了コード、エラー全文、可能なら manifest・検証結果・previewを添えてください。

[検証端末フィードバックを新規 Issue として報告する](https://github.com/yumehiko/paper-fixture/issues/new?template=verification-device-feedback.md) テンプレートがあります。Blender 5.2.1 LTS での利用者実機テストは、成功・失敗を問わず [#6](https://github.com/yumehiko/paper-fixture/issues/6) で収集します。
