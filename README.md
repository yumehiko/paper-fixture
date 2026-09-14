# paper-fixture

Illustrator の展開図を起点に、Blender で紙什器を組み立て、納品用レンダリングを制作する工程を補助するプロジェクトです。

現在は試作の第1〜3段階まで完了しています。Illustrator から取り出した展開図を、印刷面・紙厚・穴を持つ編集可能な Blender の**平面部材**へ変換できます。折り、複数部材の組立配置、両面印刷、納品レンダリングはまだ実装していません。

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

独自入力には、`PF_CUT` と `PF_PRINT_FRONT` レイヤー、部材ごとの `PF_PART_<ID>` グループ、パス ID、紙厚を記した `material.json` が必要です。規約、コマンド、出力内容は [Illustrator 書き出し試作](docs/illustrator-export.md) を参照してください。理想化サンプルの `.ai` 再生成は、追加で公開 MIT リポジトリ [illustrator-agent](https://github.com/yumehiko/illustrator-agent) を必要とする開発者向け手順であり、Blender を試すための前提ではありません。

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
- [Blender平面部材生成（第3段階）](docs/blender-panels.md)
- [数値配置と編集可能な `.blend` 受け渡し設計（第4段階）](docs/assembly-placement.md)

各文書では、ユーザーが示した要望と、検証前の設計提案を区別する。未回答の項目を決定事項として扱わない。
