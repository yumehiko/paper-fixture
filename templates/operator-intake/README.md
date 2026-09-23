# Illustrator 入稿テンプレート

`operator-intake-template.ai` を Illustrator で開き、すぐに **別名で保存**してから編集します。保存名は `<project>-intake.ai` を目安にします。これは架空の見本であり、実案件や検証済みの製造データではありません。

1. `PF_CUT`、`PF_PRINT_FRONT`、`PF_FOLD` それぞれで、対応する `PF_PART_EXAMPLE_*` グループを複製し、同じ `PF_PART_<部材ID>` に名前を変えます。
2. 切断外周・穴、前面印刷、名前付き直線foldを各レイヤーの対応グループに置き換えます。寸法や作業メモは `PF_ANNOTATION` に置きます。
3. 全レイヤーから `PF_PART_EXAMPLE_*` を削除し、見本の形状が残っていないことを確認します。
4. [dimensions-template.md](dimensions-template.md) の部材 ID と折線名を `.ai` と一致させ、単位、紙厚、完成時の向き、寸法基準、配置関係、折り条件を記入します。

利用者が入力するのは Illustrator の通常のレイヤー、グループ、パス、名前とこの資料です。path note、JSON、XYZ 座標、回転行列は不要です。複数アートボード、入れ子の `PF_PART_*` グループ、`PF_CUT` に置く注釈、折線からの山谷・角度・完成形の自動推定はこのテンプレートの対象外です。

詳細な規約は [Illustrator 入稿と寸法資料](../../docs/operator-intake.md) を参照してください。
