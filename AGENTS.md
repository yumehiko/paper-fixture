# Worktreeの配置

- 実装・レビュー用のworktreeは、メインcheckoutの `.worktrees/<作業名>/` に作成する。リポジトリの隣に `paper-fixture-*` フォルダを増やさない。
- linked worktree内で作業している場合も、配置先はメインcheckout直下の `.worktrees/` とする。メインcheckoutは `git worktree list --porcelain` の最初の `worktree` 行で確認する。
- 移動には `git worktree move` を使う。未コミット変更、未追跡の生成物、検証証跡を保持し、確認なしにworktreeや成果物を削除しない。
