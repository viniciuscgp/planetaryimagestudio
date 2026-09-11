import copy
import unittest
import numpy as np
from PIL import Image
from image_adjustments import percentile_stretch,apply_adjustments
from image_annotations import empty_state,validate_state,AnnotationDocument
from image_filters import is_edited
import test_download_navigation as navigation


class PercentileTests(unittest.TestCase):
    def test_per_channel_formula_clipping_and_unchanged_input(self):
        rng = np.random.default_rng(12)
        rgb = rng.integers(20,220,(40,60,3),dtype=np.uint8)
        source = Image.fromarray(rgb)
        output = np.asarray(percentile_stretch(source))
        lower,upper = np.percentile(rgb.reshape(-1,3),[1,99],axis=0)
        expected = np.rint(np.clip((rgb.astype(float)-lower)*255/(upper-lower),0,255)).astype(np.uint8)
        np.testing.assert_array_equal(output,expected)
        np.testing.assert_array_equal(source,rgb)
        self.assertTrue((output.min(axis=(0,1)) == 0).all())
        self.assertTrue((output.max(axis=(0,1)) == 255).all())

    def test_dark_border_transparency_and_constant_channels(self):
        ramp = np.linspace(30,190,400).reshape(20,20).astype(np.uint8)
        rgb = np.stack([ramp,ramp, np.full_like(ramp,60)],axis=2)
        padded = np.full((100,100,4),3,np.uint8);padded[:,:,3] = 255
        padded[40:60,40:60,:3] = rgb
        padded[:5,:,:3] = 255;padded[:5,:,3] = 0
        output = np.asarray(percentile_stretch(Image.fromarray(padded)))
        expected = np.asarray(percentile_stretch(Image.fromarray(rgb)))
        np.testing.assert_array_equal(output[40:60,40:60,:3],expected)
        np.testing.assert_array_equal(output[:,:,3],padded[:,:,3])
        self.assertTrue((output[40:60,40:60,2] == 60).all())
        for mode,color in [('RGB','black'),('RGBA',(90,120,150,0))]:
            image = Image.new(mode,(20,20),color)
            self.assertEqual(percentile_stretch(image).tobytes(),image.tobytes())

    def test_legacy_defaults_and_disabled_pipeline(self):
        state = empty_state()
        for key in ('percentile_stretch','percentile_low','percentile_high'):
            state.pop(key)
        validate_state(state)
        self.assertFalse(state['percentile_stretch'])
        image = Image.new('RGB',(20,20),(80,100,140))
        self.assertEqual(apply_adjustments(image,state).tobytes(),image.tobytes())
        state['percentile_low'] = state['percentile_high']
        with self.assertRaises(ValueError):validate_state(state)


class PercentileIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def test_apply_undo_parameters_pending_reset_and_original_preserved(self):
        path = self.image(1,'stretch.png')
        pixels = np.random.default_rng(2).integers(50,180,(60,80,3),dtype=np.uint8)
        Image.fromarray(pixels).save(path)
        original = path.read_bytes()
        window = self.window()
        before = window.processed_qimage.copy()
        window.image_view.scale(2,2);zoom = window.image_view.transform()
        window.act_percentile_stretch.trigger()
        self.assertTrue(window.percentile_stretch)
        self.assertNotEqual(window.processed_qimage,before)
        self.assertEqual(window.image_view.transform(),zoom)
        self.assertTrue(is_edited(path))
        self.assertTrue(AnnotationDocument(path).state['percentile_stretch'])
        window._undo_annotation()
        self.assertFalse(window.act_percentile_stretch.isChecked())
        self.assertEqual(window.processed_qimage,before)
        window._undo_annotation(redo=True)
        self.assertTrue(window.act_percentile_stretch.isChecked())
        window._inline_controls['percentile_low'][1].setValue(5)
        window._flush_inline_adjustments()
        self.assertEqual(AnnotationDocument(path).state['percentile_low'],5)
        window._inline_controls['percentile_high'][1].setValue(90)
        window._reset_adjustments()
        self.assertFalse(window.percentile_stretch)
        self.assertEqual((window.percentile_low,window.percentile_high),(1,99))
        self.assertEqual(window.processed_qimage,before)
        self.assertEqual(path.read_bytes(),original)
        np.testing.assert_array_equal(window.original_image,pixels)
