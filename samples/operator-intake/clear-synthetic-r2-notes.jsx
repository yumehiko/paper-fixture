#target illustrator
// One-off verification operation for the public synthetic r2 fixture only.
// It never saves the source and changes only page-item notes in a new r3 copy.
(function () {
  var source = new File("/Users/yumehiko/repository/paper-fixture-operator-intake/build/operator-intake-native-r2/operator-intake.synthetic.ai");
  var output = new File("/Users/yumehiko/repository/paper-fixture-operator-intake/build/operator-intake-native-r3/operator-intake.note-free.synthetic.ai");
  var documentRef = null;
  function quote(value) { return '"' + String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\r/g, "\\r").replace(/\n/g, "\\n") + '"'; }
  function json(value) { if (value === null) return "null"; if (typeof value === "string") return quote(value); if (typeof value === "number" || typeof value === "boolean") return String(value); if (value instanceof Array) { var a = []; for (var i = 0; i < value.length; i++) a.push(json(value[i])); return "[" + a.join(",") + "]"; } var o = []; for (var key in value) if (value.hasOwnProperty(key)) o.push(quote(key) + ":" + json(value[key])); return "{" + o.join(",") + "}"; }
  function parent(item) { try { return item.parent.typename + ":" + (item.parent.name || ""); } catch (error) { return ""; } }
  function signature(item) { var value = {type: item.typename, name: item.name || "", parent: parent(item), note: item.note || ""}; try { value.bounds = [item.geometricBounds[0], item.geometricBounds[1], item.geometricBounds[2], item.geometricBounds[3]]; } catch (error) {} try { value.contents = item.contents; } catch (error) {} return value; }
  function snapshot(documentRef) { var items = []; for (var i = 0; i < documentRef.pageItems.length; i++) items.push(signature(documentRef.pageItems[i])); var layers = []; for (var j = 0; j < documentRef.layers.length; j++) layers.push(documentRef.layers[j].name); return {layers: layers, artboard: documentRef.artboards[0].artboardRect, items: items}; }
  try {
    if (!source.exists || output.exists) throw new Error("source missing or output already exists");
    documentRef = app.open(source);
    var before = snapshot(documentRef);
    for (var i = 0; i < documentRef.pageItems.length; i++) documentRef.pageItems[i].note = "";
    var options = new IllustratorSaveOptions(); options.pdfCompatible = true; documentRef.saveAs(output, options);
    documentRef.close(SaveOptions.DONOTSAVECHANGES); documentRef = app.open(output);
    var after = snapshot(documentRef); var notes = 0;
    for (var k = 0; k < documentRef.pageItems.length; k++) if (documentRef.pageItems[k].note !== "") notes++;
    return json({status: "passed", source: source.fsName, output: output.fsName, before: before, after: after, nonempty_notes_after_reopen: notes});
  } catch (error) { return json({status: "failed", error: String(error), line: error.line || null}); }
  finally { if (documentRef !== null) documentRef.close(SaveOptions.DONOTSAVECHANGES); }
}());
