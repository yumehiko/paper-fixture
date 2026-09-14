# Synthetic operator-intake fixture

`native-fixture.json` は、複数部材、穴、直線 fold、ライブテキスト、CompoundPath の印刷を持つ合成入力である。実案件ではない。`create-native-fixture.jsx` は Illustrator の通常 DOM だけで同じ契約を作る素材であり、path note を設定しない。

`build/operator-intake-native-r2/` は 2026-09-14 に Illustrator 30.8.1 で public `py-ai compile-native` から作った、曲線外周・曲線穴を含む draft の read-only export 証跡である。compile-native は stable identity のため path/text に `py-ai-*` note を自動付与する。そのため、この draft は geometry、Bézier handle、fold endpoint、PNG 分離、source SHA 不変の検証には使えるが、**path note が空の native fixture という受入を満たさない**。その操作は公開 CLI に存在しないため、無ノート fixture の実測は別の supported Illustrator 操作を追加するまで保留する。
