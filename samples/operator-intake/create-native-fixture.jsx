#target illustrator
// Synthetic contract fixture.  It is not a user-supplied production drawing.
(function () {
  var output = new File(arguments[0]);
  var documentRef = app.documents.add(DocumentColorSpace.RGB, 720, 360);
  documentRef.artboards[0].artboardRect = [0, 360, 720, 0];
  function layer(name) { var result = documentRef.layers.add(); result.name = name; return result; }
  function group(parent, name) { var result = parent.groupItems.add(); result.name = name; return result; }
  function rectangle(parent, name, left, top, width, height, filled) {
    var item = parent.pathItems.rectangle(top, left, width, height); item.name = name;
    item.closed = true; item.filled = filled; item.stroked = !filled; return item;
  }
  function line(parent, name, first, second) {
    var item = parent.pathItems.add(); item.name = name; item.setEntirePath([first, second]);
    item.closed = false; item.filled = false; item.stroked = true; return item;
  }
  var cut = layer("PF_CUT"), print = layer("PF_PRINT_FRONT"), fold = layer("PF_FOLD"), annotation = layer("PF_ANNOTATION");
  var bodyCut = group(cut, "PF_PART_BODY"), sideCut = group(cut, "PF_PART_SIDE");
  rectangle(bodyCut, "BODY curved-cut surrogate", 40, 320, 300, 220, false);
  var hole = bodyCut.pathItems.ellipse(230, 150, 48, 48); hole.name = "BODY hole"; hole.filled = false; hole.stroked = true;
  rectangle(sideCut, "SIDE cut", 410, 320, 180, 220, false);
  var bodyPrint = group(print, "PF_PART_BODY"), sidePrint = group(print, "PF_PART_SIDE");
  var bodyFill = rectangle(bodyPrint, "BODY color", 40, 320, 300, 220, true); bodyFill.fillColor = new RGBColor(); bodyFill.fillColor.cyan = 0;
  var text = bodyPrint.textFrames.add(); text.name = "BODY print text"; text.contents = "FRONT / BODY"; text.position = [75, 220]; text.textRange.characterAttributes.size = 26;
  rectangle(sidePrint, "SIDE color", 410, 320, 180, 220, true);
  var bodyFold = group(fold, "PF_PART_BODY"); line(bodyFold, "FOLD_BODY_SIDE", [190, 320], [190, 100]);
  var sideFold = group(fold, "PF_PART_SIDE"); line(sideFold, "FOLD_SIDE_TAB", [500, 320], [500, 100]);
  var note = annotation.textFrames.add(); note.contents = "CUT/PRINT annotation must not become geometry"; note.position = [20, 25];
  var options = new IllustratorSaveOptions(); options.pdfCompatible = true; documentRef.saveAs(output, options);
  documentRef.close(SaveOptions.DONOTSAVECHANGES);
  return "ok";
})();
