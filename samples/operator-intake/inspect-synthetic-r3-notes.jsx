#target illustrator
// Read-only companion to clear-synthetic-r2-notes.jsx.
(function () {
  var source = new File("/Users/yumehiko/repository/paper-fixture-operator-intake/build/operator-intake-native-r3/operator-intake.note-free.synthetic.ai");
  var documentRef = null;
  try {
    documentRef = app.open(source); var items = []; var nonempty = 0;
    for (var i = 0; i < documentRef.pageItems.length; i++) { var item = documentRef.pageItems[i]; var note = item.note || ""; if (note !== "") nonempty++; items.push({type: item.typename, name: item.name || "", note: note}); }
    return JSON.stringify({status: "passed", page_item_count: documentRef.pageItems.length, nonempty_notes: nonempty, items: items});
  } catch (error) { return JSON.stringify({status: "failed", error: String(error)}); }
  finally { if (documentRef !== null) documentRef.close(SaveOptions.DONOTSAVECHANGES); }
}());
