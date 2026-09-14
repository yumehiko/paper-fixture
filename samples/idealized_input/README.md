# 理想化入力サンプル（試作専用）

`input.json` が正本である。単位、部材ID、輪郭、穴、紙厚、棚位置の試作値を明示し、`generate.py` が同じ編集可能な `.ai` を新規 revision に再生成する。ここにある値は実案件の図面仕様ではない。

生成物は次の二つである。

- `curve-hole/curve-hole-input.native.ai`: 240 × 160 mm、R20 の真のベジェ外周と中央 φ24 穴を持つ1部材。
- `three-shelf/three-shelf-input.native.ai`: 左右側面、棚3枚、背面、トップボードの7部材。背面だけは2つの φ24 穴を持つ。

各 `.ai` は `PF_CUT`、`PF_PRINT_FRONT`、`PF_ANNOTATION`、空の `PF_FOLD` を持つ。`PF_CUT` と `PF_PRINT_FRONT` の双方で同じ `PF_PART_<部材ID>` 名のグループに収める。前者では外周・穴を閉じたストロークパスにし、後者ではシアンの左帯とオレンジ矢印を含む非対称印刷にする。座標は部材ローカルの mm を正本とし、Illustrator 生成座標には `72 / 25.4 pt/mm` を用いる。アートボード上の部材配置は検査しやすいように並べたものであり、組み立て位置ではない。

再生成は Illustrator Agent のロック済み環境から行う。

```bash
uv --directory /Users/yumehiko/repository/illustrator-agent run --locked \
  python /Users/yumehiko/repository/paper-fixture/samples/idealized_input/generate.py \
  --output-dir /Users/yumehiko/repository/paper-fixture/build/input-samples-r1
```

各出力の `report.json` は純粋ゲート、Illustrator native compile、再オープン検査、プレビュー生成を分けて記録する。人によるプレビュー承認は別ゲートであり、記録されるまでは `awaiting-visual-acceptance` が正しい状態である。
