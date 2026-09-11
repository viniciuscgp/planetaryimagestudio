import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import cv2
from PIL import Image
from image_adjustments import (auto_enhance_mars_image,detect_useful_area,gray_world_balance,
                               masked_luminance_clahe,percentile_stretch,apply_adjustments,
                               auto_enhance_masks,correct_illumination,save_auto_enhance_stages,
                               natural_percentile_stretch,protect_highlights,mars_scene_chroma)
from image_annotations import empty_state,validate_state,AnnotationDocument
from image_filters import is_edited
import test_download_navigation as navigation


class AutoEnhanceTests(unittest.TestCase):
    def test_limited_gray_world_and_zero_channels(self):
        rgb = np.full((20,20,3),[80,120,160],dtype=np.uint8)
        valid = np.ones((20,20),bool)
        balanced = np.asarray(gray_world_balance(Image.fromarray(rgb),valid))
        np.testing.assert_array_equal(balanced,np.full_like(rgb,[82,120,156]))
        rgb[:,:,0] = 0
        np.testing.assert_array_equal(gray_world_balance(Image.fromarray(rgb),valid),rgb)

    def test_clahe_only_changes_lab_l_with_reduced_strength(self):
        rgb = np.random.default_rng(3).integers(30,200,(64,80,3),dtype=np.uint8)
        lab = cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB)
        proposed = cv2.createCLAHE(clipLimit=1.8,tileGridSize=(8,8)).apply(lab[:,:,0])
        delta = np.clip(.65*(proposed.astype(float)-lab[:,:,0]),-18,18)
        delta = np.minimum(delta,np.maximum(240-rgb.max(axis=2).astype(float),0)/3)
        lab[:,:,0] = np.uint8(np.rint(np.clip(lab[:,:,0].astype(float)+delta,0,255)))
        expected = cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)
        actual = masked_luminance_clahe(Image.fromarray(rgb),np.ones((64,80),bool))
        np.testing.assert_array_equal(actual,expected)

    def test_exact_manual_preset_border_alpha_and_padding(self):
        rgb = np.random.default_rng(9).integers(35,180,(80,100,3),dtype=np.uint8)
        rgb[:10] = 0
        alpha = np.full((80,100),255,np.uint8);alpha[:5] = 0
        rgba = np.dstack([rgb,alpha]);source = Image.fromarray(rgba)
        actual = np.asarray(auto_enhance_mars_image(source))
        np.testing.assert_array_equal(actual,percentile_stretch(source,32,99))
        np.testing.assert_array_equal(actual[:,:,3],alpha)
        np.testing.assert_array_equal(source,rgba)
        padded = np.pad(rgba,((30,30),(30,30),(0,0)))
        larger = np.asarray(auto_enhance_mars_image(Image.fromarray(padded)))
        np.testing.assert_array_equal(larger[30:110,30:130],actual)

    def test_manual_and_auto_render_match_with_defaults(self):
        image = Image.fromarray(np.random.default_rng(19).integers(0,255,(80,100,3),dtype=np.uint8))
        manual = empty_state();manual.update(percentile_stretch=True,percentile_low=32,percentile_high=99)
        automatic = empty_state();automatic['auto_enhance_mars'] = True
        self.assertEqual(apply_adjustments(image,manual).tobytes(),apply_adjustments(image,automatic).tobytes())

    def test_hotspot_reduction_and_conservative_statistics(self):
        y,x = np.indices((200,200))
        radius = np.hypot(x-100,y-100)
        signal = 60+110*np.exp(-(radius/50)**2)
        rgb = np.repeat(np.uint8(signal)[:,:,None],3,axis=2)
        rgb[radius > 90] = 0
        rgb[(radius > 78)&(radius <= 90)] = 15
        image = Image.fromarray(rgb)
        support,valid = auto_enhance_masks(image)
        self.assertFalse(valid[radius > 82].any())
        corrected,field = correct_illumination(image,valid,support)
        old = cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB)[:,:,0].astype(float)
        new = cv2.cvtColor(np.array(corrected),cv2.COLOR_RGB2LAB)[:,:,0].astype(float)
        center = radius < 15
        annulus = (radius > 50)&(radius < 65)
        self.assertLess(new[center].mean()/new[annulus].mean(),
                        old[center].mean()/old[annulus].mean()*.85)
        self.assertTrue(np.isfinite(field).all())
        np.testing.assert_array_equal(np.asarray(corrected)[~support],rgb[~support])
        changed = rgb.copy();changed[support & ~valid] = 25
        _,same_field = correct_illumination(Image.fromarray(changed),valid,support)
        np.testing.assert_array_equal(field,same_field)

    def test_highlight_shoulder_keeps_order_and_warm_color(self):
        ramp = np.arange(210,321,dtype=float)[None,:,None]
        rgb = ramp*np.array([1,.8,.6])
        protected = protect_highlights(rgb)
        self.assertTrue((np.diff(protected[0,:,0]) > 0).all())
        self.assertLess(protected.max(),250)
        np.testing.assert_allclose(protected[:,:,0]/protected[:,:,2],1/.6)
        image = Image.fromarray(np.uint8(np.rint(np.clip(rgb,0,255))))
        valid = np.ones(rgb.shape[:2],bool)
        result = np.asarray(gray_world_balance(image,valid))
        self.assertTrue((result[:,:,0] > result[:,:,2]).all())

    def test_stretch_preserves_subtle_color_instead_of_equalizing_channels(self):
        light = np.linspace(50,180,800).reshape(20,40)
        rgb = np.uint8(np.rint(light[:,:,None]*[1.08,1,.92]))
        result = np.asarray(natural_percentile_stretch(Image.fromarray(rgb),np.ones((20,40),bool)))
        self.assertTrue((result[:,:,0] > result[:,:,1]).all())
        self.assertTrue((result[:,:,1] > result[:,:,2]).all())
        np.testing.assert_allclose(result[:,:,0]/result[:,:,2],rgb[:,:,0]/rgb[:,:,2],atol=.04)

    def test_explicit_mask_is_respected(self):
        rgb = np.random.default_rng(2).integers(20,220,(40,40,3),dtype=np.uint8)
        valid = np.zeros((40,40),bool);valid[10:30,10:30] = True
        image = Image.fromarray(rgb)
        expected = percentile_stretch(image,32,99,valid)
        np.testing.assert_array_equal(auto_enhance_mars_image(image,valid),expected)

    def test_cast_estimate_ignores_surround_and_preserves_local_differences(self):
        lab = np.full((40,40,3),[140,123,142],np.uint8)
        valid = np.zeros((40,40),bool);valid[8:32,8:32] = True
        lab[12:18,12:18,1:] = [125,144]
        result = mars_scene_chroma(lab,valid).astype(int)
        np.testing.assert_array_equal(result[14,14]-result[20,20],[2,2])
        altered = lab.copy();altered[~valid] = [20,10,250]
        np.testing.assert_array_equal(mars_scene_chroma(altered,valid)[valid],result[valid])
        for color in ([140,128,128],[140,134,142]):
            warm = np.full_like(lab,color)
            np.testing.assert_array_equal(mars_scene_chroma(warm,valid),warm[:,:,1:])

    def test_disabled_stages_do_not_recolor_or_relight(self):
        image = Image.fromarray(np.random.default_rng(13).integers(20,200,(60,80,3),dtype=np.uint8))
        stages = {};result = auto_enhance_mars_image(image,stages=stages)
        self.assertEqual(stages['illumination_corrected'].tobytes(),image.tobytes())
        self.assertFalse(stages['illumination'].any())
        for name in ('percentile','white_balance','final_clahe'):
            self.assertEqual(stages[name].tobytes(),result.tobytes())

    def test_stage_exports_and_auto_starts_from_clean_original(self):
        image = Image.fromarray(np.random.default_rng(4).integers(20,200,(60,80,3),dtype=np.uint8))
        state = empty_state();state.update(auto_enhance_mars=True,brightness=130,inverted=True)
        with patch('image_adjustments.auto_enhance_mars_image',wraps=auto_enhance_mars_image) as enhance:
            apply_adjustments(image,state)
        self.assertEqual(enhance.call_args.args[0].tobytes(),image.tobytes())
        with tempfile.TemporaryDirectory() as folder:
            first = save_auto_enhance_stages(image,folder)
            second = save_auto_enhance_stages(image,folder)
            self.assertNotEqual(first,second)
            self.assertEqual(len(list(first.glob('*.png'))),8)
            with Image.open(first/'00_original.png') as original:
                self.assertEqual(original.tobytes(),image.tobytes())
            with Image.open(first/'07_final_clahe.png') as final:
                self.assertEqual(final.tobytes(),auto_enhance_mars_image(image).tobytes())
            self.assertEqual(np.load(first/'illumination_lab_l.npy').dtype,np.float32)

    def test_empty_fields_legacy_defaults_and_repeat_render(self):
        for color in ((0,0,0,255),(140,100,80,0)):
            image = Image.new('RGBA',(20,20),color)
            self.assertEqual(auto_enhance_mars_image(image).tobytes(),image.tobytes())
        state = empty_state();state.pop('auto_enhance_mars')
        validate_state(state)
        self.assertFalse(state['auto_enhance_mars'])
        state['auto_enhance_mars'] = True
        image = Image.fromarray(np.random.default_rng(1).integers(20,220,(60,80,3),dtype=np.uint8))
        self.assertEqual(apply_adjustments(image,state).tobytes(),apply_adjustments(image,state).tobytes())


class AutoEnhanceIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def test_export_uses_original_even_with_visible_annotations(self):
        self.image(1,'marked.png')
        window = self.window()
        state = dict(window._annotation_document.state)
        state['drawings'] = [dict(kind='ellipse',points=[[5,5],[40,40]],color='#00ff00',width=4)]
        window._annotation_document.commit(state)
        window._render_current()
        original = window.original_image.tobytes()
        with tempfile.TemporaryDirectory() as folder, \
             patch('app.QFileDialog.getExistingDirectory',return_value=folder), \
             patch('app.QMessageBox.information'), \
             patch('image_adjustments.save_auto_enhance_stages',return_value=Path(folder)) as export:
            window.act_export_auto_stages.trigger()
        self.assertEqual(export.call_args.args[0].tobytes(),original)
        self.assertEqual(window._annotation_document.state,state)

    def test_working_image_undo_reset_toggle_and_original(self):
        path = self.image(1,'mars.png')
        pixels = np.random.default_rng(2).integers(40,180,(60,80,3),dtype=np.uint8)
        Image.fromarray(pixels).save(path)
        original = path.read_bytes()
        window = self.window()
        window._inline_changed('brightness',110)
        window._flush_inline_adjustments()
        before = window.processed_qimage.copy()
        window.image_view.scale(2,2);zoom = window.image_view.transform()
        window.act_auto_enhance_mars.trigger()
        self.assertTrue(window.auto_enhance_mars)
        self.assertNotEqual(window.processed_qimage,before)
        self.assertEqual(window.image_view.transform(),zoom)
        self.assertEqual(window.brightness,110)
        self.assertTrue(AnnotationDocument(path).state['auto_enhance_mars'])
        self.assertTrue(is_edited(path))
        window._undo_annotation()
        self.assertFalse(window.act_auto_enhance_mars.isChecked())
        self.assertEqual(window.processed_qimage,before)
        window._undo_annotation(redo=True)
        self.assertTrue(window.act_auto_enhance_mars.isChecked())
        window.act_auto_enhance_mars.trigger()
        self.assertEqual(window.processed_qimage,before)
        window.act_auto_enhance_mars.trigger()
        window._reset_adjustments()
        self.assertFalse(window.auto_enhance_mars)
        self.assertFalse(window.act_auto_enhance_mars.isChecked())
        self.assertEqual(path.read_bytes(),original)
        np.testing.assert_array_equal(window.original_image,pixels)


if __name__ == '__main__':
    unittest.main()
