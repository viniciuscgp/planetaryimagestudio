import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import csv
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from forensic_texture_analyzer import ForensicTextureAnalyzer, METRICS
from forensic_texture_ui import ForensicTextureDialog, highlight_texture, strongest_mask, spotlight_texture
from forensic_texture_presentation import RegionPresentation, category


class TextureTests(unittest.TestCase):
    def test_uniform_and_tiny_images_are_finite_and_unchanged(self):
        for shape in ((2,2,3),(73,91,3)):
            image = np.full(shape,128,np.uint8)
            before = image.copy()
            result = ForensicTextureAnalyzer().analyze(image)
            np.testing.assert_array_equal(image,before)
            for maps in [result.maps,*result.scale_maps.values()]:
                for value in maps.values():
                    self.assertEqual(value.shape,shape[:2])
                    self.assertTrue(np.isfinite(value).all())
                    np.testing.assert_allclose(value,0,atol=1e-6)

    def test_coverage_at_edges_and_overlap_average(self):
        analyzer = ForensicTextureAnalyzer((32,))
        regions = [dict(x=x,y=y,width=32,height=32) for y in analyzer._positions(73,32)
                   for x in analyzer._positions(91,32)]
        result = analyzer.build_anomaly_map(regions,np.ones(len(regions)),(73,91))
        np.testing.assert_array_equal(result,np.ones((73,91)))

    def test_synthetic_periodic_patch_is_locally_anomalous(self):
        rng = np.random.default_rng(45)
        gray = np.clip(128+rng.normal(0,3,(256,256)),0,255).astype(np.uint8)
        gray[96:160,96:160] = 128 + ((np.indices((64,64))[1] % 8 < 4)*30).astype(np.uint8)
        image = np.repeat(gray[:,:,None],3,axis=2)
        result = ForensicTextureAnalyzer().analyze(image)
        score = result.maps['score']
        self.assertGreater(score[100:156,100:156].mean(),score[:64,:64].mean()+.15)
        self.assertTrue(any(64 <= r['x'] <= 160 and 64 <= r['y'] <= 160 for r in result.top_regions))
        self.assertLessEqual(len(result.top_regions),10)
        self.assertIsNotNone(result.region_at(255,255))
        for value in result.maps.values():
            self.assertTrue(((value >= 0)&(value <= 1)).all())

    def test_rgb_compression_and_residual_measurements(self):
        rng = np.random.default_rng(2)
        a = rng.integers(0,256,(64,64),dtype=np.uint8)
        corr,valid = ForensicTextureAnalyzer.rgb_correlation_analysis(np.stack([a,a,255-a],axis=2))
        self.assertTrue(valid)
        np.testing.assert_allclose(corr,[1,-1,-1],atol=1e-5)
        block = (np.indices((64,64))[1]//8).astype(np.float32)*10
        profile = ForensicTextureAnalyzer.compression_grid_analysis(block)
        self.assertGreater(profile[0],max(profile[1:8])+1)
        shifted = ForensicTextureAnalyzer.compression_grid_analysis(block,x=3)
        self.assertEqual(np.argmax(shifted[:8]),3)
        self.assertGreater(np.std(ForensicTextureAnalyzer.high_frequency_analysis(a.astype(np.float32))),0)

    def test_weights_exports_and_cancellation(self):
        image = np.random.default_rng(1).integers(0,255,(65,79,3),dtype=np.uint8)
        result = ForensicTextureAnalyzer((32,64)).analyze(image)
        ForensicTextureAnalyzer.recombine(result,{'fft':1})
        np.testing.assert_allclose(result.maps['score'],result.maps['fft'])
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            result.export_csv(folder/'regions.csv')
            result.export_maps(folder)
            with (folder/'regions.csv').open(encoding='utf-8-sig') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows),len(result.regions))
            self.assertIn('boundary_anomaly',rows[0])
            with np.load(folder/'metric_maps.npz') as maps:
                np.testing.assert_array_equal(maps['score'],result.maps['score'])
                for key in METRICS:
                    self.assertIn('32_'+key,maps)
            self.assertTrue((folder/'raw_metrics_32.npz').exists())
            self.assertEqual(cv2.imread(str(folder/'fft.png')).shape,image.shape)
        ForensicTextureAnalyzer.recombine(result,{})
        np.testing.assert_array_equal(result.maps['score'],0)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            ForensicTextureAnalyzer().analyze(image,cancel=cancel)


class TextureUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_background_analysis_inspection_and_original_unchanged(self):
        image = Image.fromarray(np.random.default_rng(3).integers(0,255,(73,91,3),dtype=np.uint8))
        before = image.tobytes()
        dialog = ForensicTextureDialog(image,'source.png')
        dialog.show()
        dialog.start_analysis()
        for _ in range(1000):
            self.app.processEvents()
            if dialog.worker is None:
                break
            QTest.qWait(5)
        self.assertIsNone(dialog.worker)
        self.assertIsNotNone(dialog.result)
        dialog.inspect_pixel(90,72)
        self.assertIn('Ponto clicado: X=90 Y=72',dialog.summary.toPlainText())
        self.assertIn('Região analisada:',dialog.summary.toPlainText())
        self.assertIn('Valor visual do heatmap',dialog.summary.toPlainText())
        self.assertIn('Score real da região',dialog.summary.toPlainText())
        self.assertFalse(dialog.technical_toggle.isChecked())
        self.assertFalse(dialog.details.isVisible())
        dialog.technical_toggle.click()
        self.assertTrue(dialog.details.isVisible())
        self.assertIn('High frequency RMS',dialog.details.toPlainText())
        dialog.scale_choice.setCurrentIndex(1)
        self.assertEqual(dialog.selected['window_size'],32)
        dialog.inspect_top(0)
        self.assertNotIn('Ponto clicado:',dialog.summary.toPlainText())
        dialog.overlay.setChecked(False)
        dialog.mark.setChecked(False)
        dialog.selected = None
        dialog.refresh()
        self.assertEqual(image.tobytes(),before)
        self.assertEqual(dialog.view.item.pixmap().size().width(),91)
        for check in dialog.metrics.values():
            check.setChecked(False)
        np.testing.assert_array_equal(dialog.result.maps['score'],0)
        dialog.close()

    def test_close_cancels_worker_without_destroying_thread(self):
        dialog = ForensicTextureDialog(Image.new('RGB',(512,512)),'source.png')
        dialog.show()
        dialog.start_analysis()
        dialog.reject()
        for _ in range(1000):
            self.app.processEvents()
            if dialog.worker is None:
                break
            QTest.qWait(5)
        self.assertIsNone(dialog.worker)
        self.assertFalse(dialog.isVisible())

    def test_highlight_layer_masks_pixels_and_preserves_original(self):
        base = np.full((4,4,3),80,np.uint8)
        before = base.copy()
        scores = np.zeros((4,4),np.float32)
        scores[1,1] = .5
        scores[2,2] = 1
        highlighted = highlight_texture(base,scores,.4,1)
        np.testing.assert_array_equal(highlighted[scores < .4],base[scores < .4])
        np.testing.assert_array_equal(highlighted[2,2],[130,0,0])
        self.assertFalse(np.array_equal(highlighted[1,1],base[1,1]))
        np.testing.assert_array_equal(highlight_texture(base,scores,.4,0),base)
        np.testing.assert_array_equal(highlight_texture(base,np.zeros((4,4)),0,1),
                                      np.broadcast_to([255,235,80],base.shape))
        np.testing.assert_array_equal(base,before)
        dialog = ForensicTextureDialog(Image.fromarray(base),'source.png')
        dialog.analysis_done(ForensicTextureAnalyzer((32,)).analyze(base))
        dialog.overlay.setChecked(False)
        dialog.highlight.setChecked(True)
        dialog.highlight_mode.setCurrentIndex(0)
        self.assertIn('mapa é uniforme',dialog.highlight_status.text())
        dialog.highlight_mode.setCurrentIndex(1)
        self.assertIn('Nenhum valor do mapa',dialog.highlight_status.text())
        dialog.highlight.setChecked(False)
        np.testing.assert_array_equal(dialog.image,base)
        dialog.close()

    def test_relative_spotlight_finds_low_score_peak_without_inventing_flat_peaks(self):
        base = np.full((100,100,3),120,np.uint8)
        scores = np.full((100,100),.1,np.float32)
        scores[40:60,40:60] = .25
        # A small peak must not highlight the entire tied background.
        mask = strongest_mask(scores)
        self.assertTrue(mask[50,50])
        self.assertFalse(mask[90,90])
        output = spotlight_texture(base,mask,.85)
        self.assertGreater(int(output[50,50,0]),int(output[50,50,1])+100)
        self.assertLess(output[90,90,0],80)
        self.assertFalse(strongest_mask(np.full((10,10),.3)).any())
        np.testing.assert_array_equal(spotlight_texture(base,mask,0),base)
        dialog = ForensicTextureDialog(Image.fromarray(base),'source.png')
        self.assertFalse(dialog.mark.isChecked())
        self.assertFalse(dialog.overlay.isChecked())
        self.assertTrue(dialog.highlight.isChecked())
        self.assertEqual(dialog.highlight_mode.currentIndex(),1)
        dialog.highlight_mode.setCurrentIndex(0)
        result = ForensicTextureAnalyzer((32,)).analyze(base)
        dialog.analysis_done(result)
        result.maps['score'] = scores.copy()
        result.maps['score'][51,52] = .3
        dialog.inspect_peak()
        self.assertEqual(dialog.clicked_point,(52,51))
        np.testing.assert_array_equal(dialog.image,base)
        dialog.close()

    def test_manual_cutoff_starts_visible_and_scales_to_fixed_100_percent(self):
        base = np.full((1,4,3),90,np.uint8)
        for cutoff in (.1,.5,.7):
            scores = np.array([[cutoff-.01,cutoff,(cutoff+1)/2,1]],np.float64)
            output = highlight_texture(base,scores,cutoff,1)
            np.testing.assert_array_equal(output[0,0],base[0,0])
            np.testing.assert_array_equal(output[0,1],[255,235,80])
            np.testing.assert_array_equal(output[0,3],[130,0,0])
            self.assertGreater(output[0,1].mean(),output[0,2].mean())
            self.assertGreater(output[0,2].mean(),output[0,3].mean())
            # Removing the maximum must not rescale any remaining colors.
            np.testing.assert_array_equal(highlight_texture(base[:,:3],scores[:,:3],cutoff,1),output[:,:3])
        scores = np.array([[.99,1,1,1]])
        output = highlight_texture(base,scores,1,1)
        np.testing.assert_array_equal(output[0,0],base[0,0])
        np.testing.assert_array_equal(output[0,1],[130,0,0])

    def test_export_buttons_preserve_source_and_use_distinct_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'original.png'
            image = Image.new('RGB',(40,40),'orange')
            image.save(path)
            before = path.read_bytes()
            dialog = ForensicTextureDialog(image,path)
            dialog.analysis_done(ForensicTextureAnalyzer((32,)).analyze(np.array(image)))
            with patch('forensic_texture_ui.QFileDialog.getExistingDirectory',return_value=folder), \
                 patch('forensic_texture_ui.QMessageBox.information'):
                for kind in ('csv','heatmap','overlay','regions','maps'):
                    dialog.export(kind)
            self.assertEqual(path.read_bytes(),before)
            folders = [p for p in Path(folder).iterdir() if p.is_dir()]
            self.assertEqual(len(folders),5)
            self.assertEqual(len(list(Path(folder).rglob('regions.csv'))),2)
            dialog.close()


import test_download_navigation as navigation


class TexturePresentationTests(unittest.TestCase):
    def region(self, value, **metrics):
        return dict(score=value, rgb_valid=True,
                    **{k+'_anomaly':metrics.get(k,value) for k in METRICS})

    def test_category_thresholds_and_strict_percentiles(self):
        for value, expected in [(0,'Muito baixa'),(.19999,'Muito baixa'),(.2,'Baixa'),
                                (.4,'Moderada'),(.6,'Alta'),(.8,'Muito alta'),(1,'Muito alta')]:
            self.assertEqual(category(value),expected)
        regions = [self.region(v) for v in (.1,.2,.2,.8)]
        presentation = RegionPresentation(regions)
        self.assertAlmostEqual(presentation.percentile(regions[1],'score'),100/3)
        self.assertEqual(presentation.percentile(regions[0],'score'),0)
        self.assertEqual(presentation.percentile(regions[-1],'fft_anomaly'),100)
        tied = [self.region(.3) for _ in range(3)]
        self.assertEqual(RegionPresentation(tied).percentile(tied[0],'score'),0)
        self.assertIsNone(RegionPresentation(tied[:1]).percentile(tied[0],'score'))

    def test_interpretations_use_metrics_and_do_not_change_values(self):
        import copy
        weights = {k:1 for k in METRICS}
        common = self.region(.1)
        boundary = self.region(.2,boundary=.75891)
        moderate = self.region(.2,fft=.5,high_frequency=.5)
        unusual = self.region(.9)
        regions = [common,boundary,moderate,unusual]
        before = copy.deepcopy(regions)
        presentation = RegionPresentation(regions)
        self.assertIn('bastante comum',presentation.interpretation(common,weights))
        self.assertIn('entorno',presentation.interpretation(boundary,weights))
        self.assertIn('moderadas',presentation.interpretation(moderate,weights))
        self.assertIn('várias métricas',presentation.interpretation(unusual,weights))
        self.assertIn('Nenhuma métrica',presentation.interpretation(unusual,{}))
        summary = presentation.summary_html(boundary,weights)
        self.assertIn('75.9% — Alta',summary)
        self.assertNotIn('0.75891',summary)
        self.assertIn('maior que 66%',summary)
        self.assertEqual(regions,before)
        for forbidden in ('manipulada','artificial','fraude','estátua','animal'):
            self.assertNotIn(forbidden,summary)


class TextureIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def test_menu_toolbar_open_preserves_viewer_and_edit_state(self):
        import copy
        path = self.image(1,'texture.png')
        window = self.window()
        window._adjust_contrast(.3)
        window._rotate(90)
        window.image_view.scale(2,2)
        original = window.original_image.tobytes()
        pixels = window.processed_qimage.copy()
        state = copy.deepcopy(window._annotation_document.state)
        transform = window.image_view.transform()
        source = path.read_bytes()
        self.assertIn(window.act_forensic_texture,window.analysis_menu.actions())
        self.assertIn(window.act_forensic_texture,window.analysis_toolbar.actions())
        def exercise(dialog):
            dialog.analysis_done(ForensicTextureAnalyzer((32,)).analyze(dialog.image))
            dialog.opacity.setValue(80)
            dialog.inspect_pixel(5,5)
            dialog.overlay.setChecked(False)
            return 0
        with patch.object(ForensicTextureDialog,'exec',exercise):
            window.act_forensic_texture.trigger()
        self.assertEqual(window.original_image.tobytes(),original)
        self.assertEqual(window.processed_qimage,pixels)
        self.assertEqual(window._annotation_document.state,state)
        self.assertEqual(window.image_view.transform(),transform)
        self.assertEqual(path.read_bytes(),source)


if __name__ == '__main__':
    unittest.main()
