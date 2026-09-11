import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import unittest
from unittest.mock import patch

import numpy as np
from PySide6.QtTest import QTest
from PySide6.QtCore import QPointF
from PIL import Image

from magic_wand import select_connected,mask_to_annotation
from magic_wand_ui import MagicWandDialog
from image_annotations import AnnotationDocument,empty_state,validate_state
from morphological_region_ui import annotation_mask,marked_regions
import test_download_navigation as navigation


class WandTests(unittest.TestCase):
    def test_fixed_tolerance_connectivity_and_original_preserved(self):
        gradient = np.tile(np.arange(100,dtype=np.uint8),(20,1))
        image = np.repeat(gradient[:,:,None],3,axis=2)
        before = image.copy()
        selected = select_connected(image,(30,10),10)
        self.assertEqual(int(selected.sum()),20*21)
        self.assertFalse(selected[10,41])
        self.assertGreater(select_connected(image,(30,10),20).sum(),selected.sum())
        np.testing.assert_array_equal(image,before)
        image = np.zeros((8,8,3),np.uint8)
        image[2,2] = image[3,3] = 100
        self.assertEqual(select_connected(image,(2,2),0,connectivity=4).sum(),1)
        self.assertEqual(select_connected(image,(2,2),0,connectivity=8).sum(),2)

    def test_holes_and_disconnected_regions(self):
        image = np.zeros((80,100,3),np.uint8)
        image[10:60,10:60] = 100
        image[25:40,25:40] = 0
        image[10:30,75:95] = 100
        mask = select_connected(image,(15,15),0)
        self.assertFalse(mask[15,80])
        self.assertFalse(mask[30,30])
        drawing = mask_to_annotation(mask)
        self.assertEqual(len(drawing['rings']),2)
        state = empty_state();state['drawings'] = [drawing]
        validate_state(state)
        restored = annotation_mask(drawing,(100,80))
        self.assertFalse(restored[30,30])
        self.assertTrue(restored[15,15])
        intersection = np.count_nonzero((restored != 0)&(mask != 0))
        union = np.count_nonzero((restored != 0)|(mask != 0))
        self.assertGreater(intersection/union,.9)
        with self.assertRaises(ValueError):
            mask_to_annotation(np.ones((1,20),np.uint8))

    def test_luminosity_mode_and_invalid_seed(self):
        image = np.zeros((20,20,3),np.uint8)
        image[:,:10] = [100,0,0]
        image[:,10:] = [0,51,0]
        self.assertEqual(select_connected(image,(2,2),0,luminosity=False).sum(),200)
        self.assertEqual(select_connected(image,(2,2),0,luminosity=True).sum(),400)
        with self.assertRaises(ValueError):
            select_connected(image,(-1,2))


class WandIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def wait_wand(self,dialog):
        for _ in range(1000):
            self.app.processEvents()
            if dialog.worker is None and not dialog.timer.isActive():
                return
            QTest.qWait(5)
        self.fail('Seleção não terminou')

    def test_preview_tolerance_rotation_and_cancel(self):
        image = np.zeros((60,80,3),np.uint8)
        image[10:40,20:60] = 50
        dialog = MagicWandDialog(Image.fromarray(image),90)
        dialog.show()
        dialog.click_image(59-20,30)
        self.wait_wand(dialog)
        self.assertEqual(dialog.seed,(30,20))
        self.assertEqual(int(dialog.mask.sum()),1200)
        self.assertTrue(dialog.apply_button.isEnabled())
        dialog.value.setValue(80)
        self.wait_wand(dialog)
        self.assertEqual(int(dialog.mask.sum()),4800)
        dialog.value.setValue(0)
        dialog.start_selection()
        dialog.reject()
        self.wait_wand(dialog)
        self.assertFalse(dialog.isVisible())
        np.testing.assert_array_equal(dialog.image,image)

    def test_apply_persist_undo_redo_and_morphology(self):
        path = self.image(1,'wand.png');window = self.window()
        original = path.read_bytes()
        window._adjust_contrast(.3)
        state_before = copy.deepcopy(window._annotation_document.state)
        mask = np.zeros((60,80),np.uint8)
        mask[5:50,10:70] = 1;mask[20:30,30:40] = 0
        drawing = mask_to_annotation(mask)
        def choose(dialog):
            dialog.annotation = drawing
            return 1
        with patch.object(MagicWandDialog,'exec',choose):
            window.act_magic_wand.trigger()
        self.assertEqual(len(window._annotation_document.state['drawings']),1)
        self.assertEqual(window._selected_drawing,0)
        choices,index = marked_regions(window)
        self.assertFalse(choices[index][1][25,35])
        self.assertIn('varinha',choices[index][0])
        saved = AnnotationDocument(path)
        self.assertIsNone(saved.read_error)
        self.assertEqual(saved.state['drawings'][0]['rings'],drawing['rings'])
        window._undo_annotation()
        self.assertEqual(window._annotation_document.state,state_before)
        window._undo_annotation(redo=True)
        self.assertEqual(len(window._annotation_document.state['drawings']),1)
        self.assertEqual(path.read_bytes(),original)
        window._selected_drawing = 0
        window._edit_event('press',QPointF(20,15))
        window._edit_event('release',QPointF(25,15))
        moved = window._annotation_document.state['drawings'][0]
        self.assertEqual(moved['rings'],drawing['rings'])
        moved_mask = annotation_mask(moved,(80,60))
        self.assertFalse(moved_mask[25,40])
        self.assertTrue(moved_mask[15,20])


if __name__ == '__main__':
    unittest.main()
