import json, shutil, tempfile, unittest
from pathlib import Path
from tools.fold_plan import validate_plan
from tools.panel_input import InputError
ROOT=Path(__file__).resolve().parents[1]
class FoldPlanTests(unittest.TestCase):
 def payload(self):
  return {"schema":"paper-fixture-fold-plan-v1","sources":{"export_json":"build/illustrator-export-r2/curve-hole/export.json","print_png":"build/illustrator-export-r2/curve-hole/print-front.png"},"assemblies":[{"id":"card","part_id":"SAMPLE_CURVE_HOLE","root_face":"face-a","folds":[{"fold_id":"FOLD_01","parent_face":"face-a","child_face":"face-b","child_side":"right","mountain_valley":"valley","viewed_from":"print_front","target_dihedral_deg":90}]}]}
 def test_requires_ir_fold_id(self):
  with self.assertRaisesRegex(InputError,"absent"):
   validate_plan(self.payload(),ROOT)
 def test_rejects_ambiguous_root_or_cycle_before_blender(self):
  p=self.payload(); p["assemblies"][0]["folds"]=[{**p["assemblies"][0]["folds"][0],"child_face":"face-a"}]
  with self.assertRaisesRegex(InputError,"self-connect"): validate_plan(p,ROOT)
 def test_accepts_a_resolved_fold_id_from_synthetic_intake(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d); (d/'build').mkdir(); shutil.copy(ROOT/'build/illustrator-export-r2/curve-hole/print-front.png',d/'build/print.png')
   export=json.loads((ROOT/'build/illustrator-export-r2/curve-hole/export.json').read_text()); export['parts'][0]['folds']=[{'id':'FOLD_01','endpoints_mm':[[30,0],[30,160]],'boundary_relation':'not-evaluated-by-intake','status':'angle-and-direction-required-in-assembly-plan'}]
   (d/'build/export.json').write_text(json.dumps(export)); p=self.payload();p['sources']={'export_json':'build/export.json','print_png':'build/print.png'}
   self.assertEqual(validate_plan(p,d)['assemblies'][0]['root_face'],'face-a')
 def test_requires_explicit_child_side(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d); (d/'build').mkdir(); shutil.copy(ROOT/'build/illustrator-export-r2/curve-hole/print-front.png',d/'build/print.png')
   export=json.loads((ROOT/'build/illustrator-export-r2/curve-hole/export.json').read_text()); export['parts'][0]['folds']=[{'id':'FOLD_01','endpoints_mm':[[30,0],[30,160]],'boundary_relation':'not-evaluated-by-intake','status':'angle-and-direction-required-in-assembly-plan'}]
   (d/'build/export.json').write_text(json.dumps(export)); p=self.payload(); p['sources']={'export_json':'build/export.json','print_png':'build/print.png'}; del p['assemblies'][0]['folds'][0]['child_side']
   with self.assertRaisesRegex(InputError, 'fields'): validate_plan(p,d)
