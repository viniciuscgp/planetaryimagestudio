import json
import unittest
from unittest.mock import patch
from PIL import Image
from PySide6.QtWidgets import QDialog,QApplication
from image_smoothing import smooth_image,SmoothingDialog
from image_annotations import AnnotationDocument,empty_state
from image_filters import is_edited
import test_download_navigation as navigation

class SmoothingTests(unittest.TestCase):
    setUpClass=classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp=navigation.DownloadNavigationTests.setUp
    image=navigation.DownloadNavigationTests.image
    window=navigation.DownloadNavigationTests.window

    def test_noise_reduced_without_changing_alpha_or_dimensions(self):
        image=Image.new('RGBA',(9,9),(70,90,100,120));image.putpixel((4,4),(255,255,255,25))
        full=smooth_image(image,100);half=smooth_image(image,50)
        self.assertEqual(full.getpixel((4,4)),(70,90,100,25))
        self.assertEqual(full.size,image.size)
        self.assertEqual(full.getchannel('A').tobytes(),image.getchannel('A').tobytes())
        self.assertGreater(half.getpixel((4,4))[0],full.getpixel((4,4))[0])
        self.assertEqual(smooth_image(image,0).tobytes(),image.tobytes())

    def test_apply_undo_redo_reopen_reset_and_clipboard(self):
        path=self.image(1,'noise.png')
        noise=Image.new('RGB',(30,30),(70,90,100));noise.putpixel((15,15),(255,255,255));noise.save(path)
        original=path.read_bytes();window=self.window()
        with patch('app.SmoothingDialog') as dialog_type:
            dialog=dialog_type.return_value;dialog.exec.return_value=QDialog.DialogCode.Accepted;dialog.intensity.value.return_value=100
            window._smooth_image()
        self.assertEqual(window.smoothing,100)
        self.assertEqual(window.processed_qimage.pixelColor(15,15).red(),70)
        self.assertTrue(is_edited(path))
        self.assertEqual(AnnotationDocument(path).state['smoothing'],100)
        window._copy_image()
        self.assertEqual(QApplication.clipboard().image().pixelColor(15,15).red(),70)
        window._undo_annotation();self.assertEqual(window.smoothing,0)
        window._undo_annotation(redo=True);self.assertEqual(window.smoothing,100)
        reopened=self.window();self.assertEqual(reopened.smoothing,100)
        reopened._reset_adjustments();self.assertEqual(reopened.smoothing,0)
        self.assertEqual(path.read_bytes(),original)

    def test_cancel_does_not_create_edits_and_old_sidecars_default_to_zero(self):
        path=self.image(1,'old.png');document=AnnotationDocument(path);document.save()
        data=json.loads(document.path.read_text());del data['state']['smoothing'];document.path.write_text(json.dumps(data))
        self.assertEqual(AnnotationDocument(path).state['smoothing'],0)
        original=document.path.read_bytes();window=self.window()
        with patch('app.SmoothingDialog') as dialog_type:
            dialog_type.return_value.exec.return_value=QDialog.DialogCode.Rejected
            window._smooth_image()
        self.assertEqual(window.smoothing,0)
        self.assertEqual(document.path.read_bytes(),original)
        self.assertFalse(is_edited(path))

    def test_preview_does_not_modify_source(self):
        image=Image.new('RGB',(30,30),(80,80,80));image.putpixel((15,15),(255,255,255));before=image.tobytes()
        dialog=SmoothingDialog(image,0);self.addCleanup(dialog.close)
        dialog.slider.setValue(100)
        self.assertEqual(dialog.intensity.value(),100)
        self.assertEqual(dialog.preview.pixmap().toImage().pixelColor(15,15).red(),80)
        self.assertEqual(image.tobytes(),before)

if __name__=='__main__':unittest.main()