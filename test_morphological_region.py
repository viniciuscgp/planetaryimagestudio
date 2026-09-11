import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import threading
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from annotation_editing import image_transform
from morphological_region_analyzer import MorphologicalRegionAnalyzer
from morphological_region_ui import annotation_mask, marked_regions, MorphologicalRegionDialog
import test_download_navigation as navigation


class MorphologyTests(unittest.TestCase):
    def test_explicit_nonempty_mask_required(self):
        image = np.zeros((100,100,3),np.uint8)
        for mask in (np.zeros((100,100)),np.ones((1,1))):
            with self.assertRaises(ValueError):
                MorphologicalRegionAnalyzer().analyze(image,mask)
        cancel = threading.Event();cancel.set()
        with self.assertRaises(InterruptedError):
            MorphologicalRegionAnalyzer().analyze(image,np.ones((100,100)),cancel)

    def test_horizontal_opening_and_outside_pixels_do_not_affect_analysis(self):
        image = np.full((150,180,3),180,np.uint8)
        mask = np.zeros(image.shape[:2],np.uint8)
        mask[20:130,20:160] = 1
        image[65:74,45:115] = 25
        before = image.copy()
        result = MorphologicalRegionAnalyzer().analyze(image,mask)
        openings = [s for s in result.structures if s['kind'] == 'abertura geométrica']
        self.assertTrue(openings,result.structures)
        self.assertAlmostEqual(openings[0]['length_px'],70,delta=2)
        self.assertLess(min(openings[0]['orientation_deg'],180-openings[0]['orientation_deg']),5)
        self.assertTrue(openings[0]['parallel_edges'])
        self.assertTrue(openings[0]['adjacent_larger_light_region'])
        self.assertIn('horizontal',result.summary)
        self.assertTrue(result.layers['fissures'].any())
        image[mask == 0] = np.random.default_rng(2).integers(0,255,(int((mask == 0).sum()),3),dtype=np.uint8)
        other = MorphologicalRegionAnalyzer().analyze(image,mask)
        self.assertEqual(result.metrics,other.metrics)
        self.assertEqual(result.structures,other.structures)
        for key in result.layers:
            np.testing.assert_array_equal(result.layers[key],other.layers[key])
            self.assertFalse((result.layers[key][result.mask == 0] != 0).any())
        np.testing.assert_array_equal(image[mask != 0],before[mask != 0])

    def test_cavity_silhouette_concavity_and_uniform_fallback(self):
        image = np.full((140,140,3),220,np.uint8)
        mask = np.zeros((140,140),np.uint8);mask[10:130,10:130] = 1
        polygon = np.array([[30,30],[110,30],[110,55],[65,55],[65,85],[110,85],[110,110],[30,110]])
        cv2.fillPoly(image,[polygon],(100,100,100))
        cv2.circle(image,(45,70),7,(15,15,15),-1)
        result = MorphologicalRegionAnalyzer().analyze(image,mask)
        self.assertIn('estimada',result.metrics['shape_source'])
        self.assertGreaterEqual(result.metrics['concavities'],1)
        self.assertTrue(result.layers['cavities'].any())
        self.assertTrue(result.layers['external'].any())
        self.assertGreater(result.metrics['symmetry'],.8)
        uniform = MorphologicalRegionAnalyzer().analyze(np.full_like(image,120),mask)
        self.assertFalse(uniform.layers['external'].any())
        self.assertEqual(uniform.structures,[])
        self.assertIn('marcação',uniform.metrics['shape_source'])
        for word in ('animal','estátua','rosto','boca'):
            self.assertNotIn(word,result.summary)


class MorphologyUITests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def drawing(self,kind,points):
        return dict(kind=kind,points=points,color='#ff0000',width=3)

    def test_existing_geometry_masks(self):
        rectangle = annotation_mask(self.drawing('rectangle',[[10,10],[50,40]]),(80,60))
        self.assertEqual(int(rectangle.sum()),1200)
        ellipse = annotation_mask(self.drawing('ellipse',[[10,10],[50,40]]),(80,60))
        self.assertTrue(ellipse[25,30])
        self.assertFalse(ellipse[10,10])
        circle = annotation_mask(self.drawing('circle',[[30,30],[40,30]]),(80,60))
        self.assertAlmostEqual(circle.sum(),np.pi*100,delta=30)
        freehand = annotation_mask(self.drawing('pencil',[[10,10],[40,10],[40,40],[10,40]]),(80,60))
        self.assertTrue(freehand[20,20])
        for drawing in (self.drawing('pencil',[[10,10],[40,10]]),
                        self.drawing('rectangle',[[100,100],[120,120]]),dict(kind='text')):
            self.assertIsNone(annotation_mask(drawing,(80,60)))

    def test_selected_latest_and_rotated_selection_without_mutation(self):
        path = self.image(1,'morphology.png');window = self.window()
        drawings = [self.drawing('ellipse',[[5,5],[30,30]]),self.drawing('rectangle',[[40,10],[70,40]])]
        state = copy.deepcopy(window._annotation_document.state)
        state['drawings'] = drawings
        window._annotation_document.commit(state)
        choices,index = marked_regions(window)
        self.assertEqual(index,1)
        window._selected_drawing = 0
        choices,index = marked_regions(window)
        self.assertEqual(index,0)
        np.testing.assert_array_equal(choices[index][1],annotation_mask(drawings[0],(80,60)))
        window._selected_drawing = None
        window.rotation = 90
        window.image_view.region_rect = image_transform(90,80,60).mapRect(QRectF(5,10,20,25))
        choices,index = marked_regions(window)
        self.assertEqual(choices[index][0],'Seleção de área atual')
        self.assertEqual(int(choices[index][1].sum()),500)
        self.assertEqual(window._annotation_document.state,state)
        self.assertEqual(window.original_image.size,(80,60))

    def test_no_selection_message_and_action_preserves_edits(self):
        path = self.image(1,'morphology.png');window = self.window()
        with patch('app.QMessageBox.information') as message:
            window.act_morphological.trigger()
        self.assertEqual(message.call_args.args[2],'Marque primeiro a área que deseja analisar.')
        state = copy.deepcopy(window._annotation_document.state)
        state['drawings'] = [self.drawing('rectangle',[[5,5],[60,50]])]
        window._annotation_document.commit(state)
        window._adjust_contrast(.3)
        state = copy.deepcopy(window._annotation_document.state)
        pixels = window.processed_qimage.copy()
        original = window.original_image.tobytes()
        def exercise(dialog):
            result = MorphologicalRegionAnalyzer().analyze(dialog.image,dialog.choices[0][1])
            dialog.analysis_done(result)
            for check in dialog.layers.values():
                check.setChecked(True)
            self.assertFalse(dialog.details.isVisible())
            dialog.reject()
            return 0
        with patch.object(MorphologicalRegionDialog,'exec',exercise):
            window.act_morphological.trigger()
        self.assertEqual(state,window._annotation_document.state)
        self.assertEqual(pixels,window.processed_qimage)
        self.assertEqual(original,window.original_image.tobytes())

    def test_worker_completion_and_cancel_close(self):
        image = Image.new('RGB',(150,100),'gray')
        mask = np.zeros((100,150),np.uint8);mask[10:90,10:140] = 1
        dialog = MorphologicalRegionDialog(image,[('Marcação 1',mask)],0)
        dialog.show();dialog.start_analysis()
        for _ in range(1000):
            self.app.processEvents()
            if dialog.worker is None:
                break
            QTest.qWait(5)
        self.assertIsNotNone(dialog.result)
        dialog.start_analysis();dialog.reject()
        for _ in range(1000):
            self.app.processEvents()
            if dialog.worker is None:
                break
            QTest.qWait(5)
        self.assertIsNone(dialog.worker)
        self.assertFalse(dialog.isVisible())


if __name__ == '__main__':
    unittest.main()
