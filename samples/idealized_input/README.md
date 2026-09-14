# 理想化入力サンプル（試作専用）

`input.json` が正本である。単位、部材ID、輪郭、穴、紙厚、棚位置の試作値を明示し、`generate.py` が同じ編集可能な `.ai` を新規 revision に再生成する。ここにある値は実案件の図面仕様ではない。

第2段階の書き出しでは、`.ai` に保持されない紙厚だけを [`material.json`](material.json) の明示的な外部入力として渡す。形状・部材ID・印刷パスはこのJSONやIRから補完せず、Illustratorで開いた `.ai` DOM から抽出する。

生成物は次の二つである。

- `curve-hole/curve-hole-input.native.ai`: 240 × 160 mm、R20 の真のベジェ外周と中央 φ24 穴を持つ1部材。
- `three-shelf/three-shelf-input.native.ai`: 左右側面、棚3枚、背面、トップボードの7部材。背面だけは2つの φ24 穴を持つ。

リポジトリでレビュー・視覚承認の対象にする成果物は `build/input-samples-r2/` である。これは左上原点・+Y下の座標変換を検証済みの revision である。

各 `.ai` は `PF_CUT`、`PF_PRINT_FRONT`、`PF_ANNOTATION`、空の `PF_FOLD` を持つ。`PF_CUT` と `PF_PRINT_FRONT` の双方で同じ `PF_PART_<部材ID>` 名のグループに収める。前者では外周・穴を閉じたストロークパスにし、後者ではシアンの左帯とオレンジ矢印を含む非対称印刷にする。正本の座標は部材ローカルの mm、原点はアートボード左上、+X は右、+Y は下である。生成時には `X_ai = X_mm × 72 / 25.4`、`Y_ai = (artboard_height_mm - Y_mm) × 72 / 25.4` に変換する。アートボード上の部材配置は検査しやすいように並べたものであり、組み立て位置ではない。

再生成には macOS、Adobe Illustrator 2026、公開 MIT リポジトリ [illustrator-agent](https://github.com/yumehiko/illustrator-agent) のロック済み環境が必要である。`illustrator-agent` は必要な `py-ai-illustrator` commit を `uv.lock` で固定して取得する。`paper-fixture` と同じ親ディレクトリで、次のように取得する。このリポジトリはその環境を同梱しない。

```bash
git clone https://github.com/yumehiko/illustrator-agent.git
cd illustrator-agent
uv sync --locked
cd ../paper-fixture
```

リポジトリ直下で実行する。

```bash
PYTHON=../illustrator-agent/.venv/bin/python
"$PYTHON" samples/idealized_input/generate.py \
  --output-dir build/input-samples-local
```

既存 revision は上書きしない。各出力の `report.json` は純粋ゲート、Illustrator native compile、再オープン検査、プレビュー生成を分けて記録する。r2 の2枚の PNG はユーザーがツール外で確認し、2026-09-14T13:48:21+09:00 に `ok` と承認したため、両 report の視覚承認ゲートは `passed` である。
