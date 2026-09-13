import copy
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import test_download_navigation as navigation
from app import MainWindow
from adjustment_profiles import PROFILE_KEYS,load_profiles
from config import load_app_state
from image_annotations import empty_state,AnnotationDocument


SAVE_STATE = MainWindow._save_state


class ProfileDataTests(unittest.TestCase):
    def test_three_slots_validation_and_no_geometry(self):
        good = {key:empty_state()[key] for key in PROFILE_KEYS}
        bad = dict(good,percentile_low=99,percentile_high=32)
        self.assertEqual(load_profiles(None),[None,None,None])
        self.assertEqual(load_profiles([good,bad,{},good]),[good,None,None])
        result = load_profiles([dict(good,drawings=['ignored'],rotation=90)])
        self.assertNotIn('drawings',result[0]);self.assertNotIn('rotation',result[0])
        result[0]['brightness'] = 180
        self.assertEqual(good['brightness'],100)


class ProfileIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(navigation.DownloadNavigationTests.setUpClass.__func__)
    setUp = navigation.DownloadNavigationTests.setUp
    image = navigation.DownloadNavigationTests.image
    window = navigation.DownloadNavigationTests.window

    def test_save_pending_apply_all_controls_and_single_undo_on_other_image(self):
        first=self.image(1,'a.png');second=self.image(1,'b.png')
        pixels=np.random.default_rng(4).integers(20,220,(60,80,3),dtype=np.uint8)
        Image.fromarray(pixels).save(first);Image.fromarray(pixels).save(second)
        original=second.read_bytes();w=self.window()
        settings=dict(brightness=130,contrast=1.4,saturation=1.3,gamma=1.2,black_point=12,white_point=230,
                      sharpness=35,smoothing=5,percentile_low=32,percentile_high=99,
                      color_balance=True,inverted=True,percentile_stretch=True,auto_enhance_mars=True)
        for key,value in settings.items():
            if key in w._inline_controls:
                w._inline_changed(key,value)
            else:
                setattr(w,key,value)
        w._profile_buttons[0][1].click()
        self.assertFalse(w._inline_pending)
        self.assertEqual(w._adjustment_profiles[0],settings)
        expected=w.processed_qimage.copy()
        w._load_image(second)
        state=copy.deepcopy(w._annotation_document.state)
        state.update(rotation=90,drawings=[dict(kind='rectangle',points=[[4,4],[20,20]],color='#ff0000',width=2)])
        w._annotation_document.commit(state);w._apply_annotation_state();w._render_current()
        before=copy.deepcopy(w._annotation_document.state);undo=len(w._annotation_document.undo)
        w.image_view.scale(2,2);zoom=w.image_view.transform()
        w._profile_buttons[0][0].click()
        self.assertEqual(len(w._annotation_document.undo),undo+1)
        for key,value in settings.items():
            self.assertEqual(getattr(w,key),value)
            if key in w._inline_controls:
                slider,spin,_,_,factor=w._inline_controls[key]
                self.assertAlmostEqual(spin.value(),value)
                self.assertEqual(slider.value(),round(value*factor))
        self.assertTrue(w.act_auto_enhance_mars.isChecked());self.assertTrue(w.act_percentile_stretch.isChecked())
        self.assertTrue(w.act_balance.isChecked());self.assertTrue(w.act_invert.isChecked())
        self.assertEqual(w.rotation,90);self.assertEqual(w._annotation_document.state['drawings'],before['drawings'])
        self.assertEqual(w.image_view.transform(),zoom)
        self.assertEqual(second.read_bytes(),original)
        self.assertEqual(AnnotationDocument(second).state['brightness'],130)
        w._undo_annotation();self.assertEqual(w._annotation_document.state,before)
        self.assertFalse(w.act_auto_enhance_mars.isChecked());self.assertFalse(w._profile_buttons[0][0].isChecked())
        w._undo_annotation(redo=True);self.assertTrue(w._profile_buttons[0][0].isChecked())
        w._reset_adjustments()
        self.assertEqual(w._adjustment_profiles[0],settings)
        w._profile_buttons[0][0].click()
        # Reset retains drawings, so compare only the adjustment base pixels.
        from app import pil_to_qimage
        from image_adjustments import apply_adjustments
        self.assertEqual(w._annotation_base,pil_to_qimage(apply_adjustments(Image.fromarray(pixels),dict(empty_state(),**settings))))

    def test_slots_persist_to_disk_and_remain_global_across_missions(self):
        self.image(1,'a.png')
        with patch.object(MainWindow,'_save_state',SAVE_STATE), \
             patch('config._state_file_candidates',return_value=[self.root/'session.json']), \
             patch('config._legacy_state_candidates',return_value=[]):
            w=self.window()
            for i,value in enumerate((110,130,150)):
                w._inline_changed('brightness',value);w._profile_buttons[i][1].click()
            saved=load_app_state()
            self.assertEqual([p['brightness'] for p in saved['adjustment_profiles']],[110,130,150])
            restored=load_profiles(saved['adjustment_profiles'])
            w.missions.library_root=str(self.root/'Library');w._choose_source('perseverance')
            self.assertEqual(w._adjustment_profiles,restored)
            self.assertEqual(load_app_state()['adjustment_profiles'],restored)
            reopened=MainWindow(self.root,saved);self.addCleanup(reopened.close)
            self.assertEqual(reopened._adjustment_profiles,restored)
            reopened._profile_buttons[0][0].click();self.assertEqual(reopened.brightness,110)
            reopened._inline_changed('brightness',175);reopened._profile_buttons[1][1].click()
            self.assertEqual([p['brightness'] for p in load_app_state()['adjustment_profiles']],[110,175,150])

    def test_save_error_is_not_reported_as_saved_and_empty_slots_are_disabled(self):
        self.image(1,'a.png');w=self.window()
        self.assertTrue(all(not apply.isEnabled() for apply,_ in w._profile_buttons))
        with patch.object(w,'_save_state',return_value=False),patch('adjustment_profiles.QMessageBox.warning') as warning:
            w._profile_buttons[0][1].click()
        warning.assert_called_once()
        self.assertEqual(w._adjustment_profiles,[None,None,None])


if __name__=='__main__':
    unittest.main()
