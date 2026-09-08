import json
import unittest
from unittest.mock import patch
from PIL import Image
from PySide6.QtWidgets import QDialog
from image_adjustments import apply_adjustments,AdjustmentDialog
from image_annotations import AnnotationDocument,empty_state
from image_filters import is_edited
import test_download_navigation as navigation

class DetailTests(unittest.TestCase):
    setUpClass=classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp=navigation.DownloadNavigationTests.setUp
    image=navigation.DownloadNavigationTests.image
    window=navigation.DownloadNavigationTests.window

    def test_levels_map_endpoints_and_preserve_alpha(self):
        image=Image.new('RGBA',(3,1));image.putdata([(40,40,40,10),(100,100,100,80),(180,180,180,200)])
        state=empty_state();state.update(black_point=40,white_point=180)
        result=apply_adjustments(image,state)
        self.assertEqual(result.getpixel((0,0)),(0,0,0,10))
        self.assertEqual(result.getpixel((2,0)),(255,255,255,200))
        state['gamma']=2
        self.assertGreater(apply_adjustments(image,state).getpixel((1,0))[0],result.getpixel((1,0))[0])

    def test_sharpness_changes_edges_and_zero_is_identity(self):
        image=Image.new('RGB',(9,9),(80,80,80));image.putpixel((4,4),(130,130,130))
        state=empty_state();self.assertEqual(apply_adjustments(image,state).tobytes(),image.tobytes())
        state['sharpness']=100
        self.assertGreater(apply_adjustments(image,state).getpixel((4,4))[0],130)

    def test_persist_undo_reset_and_compare_preserve_original(self):
        path=self.image(1,'test.png');original=path.read_bytes();window=self.window()
        for kind,changes in [('levels',{'gamma':2}),('sharpness',{'sharpness':100})]:
            state=dict(window._annotation_document.state);state.update(changes)
            with patch('app.AdjustmentDialog') as dialog_type:
                dialog_type.return_value.exec.return_value=QDialog.DialogCode.Accepted
                dialog_type.return_value.state=state;window._adjust_detail(kind)
        self.assertTrue(is_edited(path));self.assertEqual(AnnotationDocument(path).state['gamma'],2)
        self.assertEqual(AnnotationDocument(path).state['sharpness'],100)
        window.image_view.scale(2,2);transform=window.image_view.transform()
        before=window._annotation_document.path.read_bytes();rendered=window.processed_qimage.copy()
        window.act_original.trigger();self.assertTrue(window.act_original.isChecked())
        self.assertEqual(window.image_view.transform(),transform)
        self.assertEqual(window.processed_qimage,rendered)
        self.assertEqual(window._annotation_document.path.read_bytes(),before)
        window.act_original.trigger();self.assertFalse(window.act_original.isChecked())
        window._undo_annotation();self.assertEqual(window.sharpness,0)
        window._undo_annotation(redo=True);self.assertEqual(window.sharpness,100)
        reopened=self.window();self.assertEqual(reopened.gamma,2)
        reopened._reset_adjustments();self.assertEqual((reopened.gamma,reopened.sharpness),(1,0))
        self.assertEqual(path.read_bytes(),original)

    def test_cancel_and_legacy_defaults(self):
        path=self.image(1,'old.png');doc=AnnotationDocument(path);doc.save()
        data=json.loads(doc.path.read_text())
        for key in ('black_point','white_point','gamma','sharpness'):del data['state'][key]
        doc.path.write_text(json.dumps(data));before=doc.path.read_bytes();window=self.window()
        self.assertEqual((window.black_point,window.white_point,window.gamma,window.sharpness),(0,255,1,0))
        with patch('app.AdjustmentDialog') as dialog_type:
            dialog_type.return_value.exec.return_value=QDialog.DialogCode.Rejected
            window._adjust_detail('levels')
        self.assertEqual(doc.path.read_bytes(),before)
        dialog=AdjustmentDialog(window.original_image,empty_state(),'levels');self.addCleanup(dialog.close)
        dialog.controls['black_point'].setValue(250)
        dialog.controls['white_point'].setValue(10)
        self.assertLess(dialog.state['black_point'],dialog.state['white_point'])

if __name__=='__main__':unittest.main()